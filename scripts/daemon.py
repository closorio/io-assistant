#!/usr/bin/env python3
"""Daemon del narrador: recibe frases por un socket unix y las dice de una en una.

Órdenes (una línea JSON por conexión): decir, saltar, vaciar, recargar, estado, salir.
Abre el socket antes de cargar el motor para que el primer hook no espere al modelo.
Dos hilos se reparten la voz: el sintetizador prepara la frase siguiente mientras el
reproductor dice la actual, así entre frase y frase no hay un hueco de dos segundos
(Kokoro tarda unos 2 s por frase y el audio de cada una dura 3 o 4).
Cada corte queda en el log con quién lo ordenó: el «origen» que declara la orden, su sesión
y el proceso que la envió (y sus padres), que el kernel da por el socket.
"""

import fcntl
import json
import os
import re
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from comun import LOCK, LOG, RUNTIME, leer_config, ruta_socket
from motores import MOTORES, cadena

INACTIVIDAD_MAX = 45 * 60
TEXTO_MAX = 400
PREPARAR_MAX = 1  # frases sintetizadas por adelantado mientras suena otra
ORDENES_DE_CORTE = ("saltar", "vaciar", "recargar", "salir")  # las que pueden callar la voz

cfg = leer_config()
cola: deque = deque()  # (texto, recibido, sesion): pendientes de sintetizar
preparadas: deque = deque()  # Frase: sintetizadas, esperando a sonar
cond = threading.Condition()
estado = {
    "proc": None, "motor": None, "actividad": time.monotonic(),
    "cortada": None,  # quién cortó la frase que suena
    "vaciada_por": None,  # quién vació la cola por última vez
    "sesion": None,  # sesión de Claude Code de la frase que suena
    "generacion": 0,  # cuántos vaciados ha habido (solo informativo)
}
vaciados: dict = {}  # sesión (o "*" para todas) -> (momento del último vaciado, quién lo ordenó)
motores_cargados: dict = {}  # nombre -> (firma de config, instancia)
carga = threading.Lock()  # la precarga y el sintetizador no deben cargar a la vez
servidor = None
socket_retirado = False


@dataclass
class Frase:
    texto: str
    recibido: float  # monotonic de cuando llegó la orden «decir»
    sesion: str | None
    nombre: str  # motor que la sintetizó
    orden: list
    tmp: Path | None
    sintesis: float  # ms


def log(mensaje: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {mensaje}\n")


def limpiar(texto: str) -> str:
    texto = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", texto)  # [enlace](url) -> enlace
    texto = re.sub(r"https?://\S+", "", texto)
    texto = re.sub(r"[`*_#>~|]", "", texto)
    texto = "".join(
        c for c in texto
        if unicodedata.category(c) not in ("So", "Sk", "Cs", "Co", "Cn") and c not in "️‍"
    )
    texto = " ".join(texto.split())
    if len(texto) > TEXTO_MAX:
        texto = texto[:TEXTO_MAX].rsplit(" ", 1)[0] + "…"
    return texto


def motor(nombre: str):
    firma = json.dumps([cfg.get(nombre), cfg["reproductor"], cfg.get("destino")], sort_keys=True)
    with carga:
        cargado = motores_cargados.get(nombre)
        if cargado and cargado[0] == firma:
            return cargado[1]
        t0 = time.monotonic()
        instancia = MOTORES[nombre](cfg)
        motores_cargados[nombre] = (firma, instancia)
    log(f"motor {nombre} cargado en {(time.monotonic() - t0) * 1000:.0f} ms")
    return instancia


def describir(pid: int) -> str:
    """El proceso en pocas palabras: «claude «Ío»» o el programa y sus primeros argumentos."""
    try:
        args = [a.decode("utf-8", "replace") for a in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if a]
    except OSError:
        return "ya terminado"
    if "--name" in args[:-1]:
        return f"claude «{args[args.index('--name') + 1]}»"
    if args and Path(args[0]).name in ("bash", "sh", "zsh"):
        return Path(args[0]).name  # su -c lleva todo el entorno de Claude Code: no aporta
    return " ".join(Path(a).name if a.startswith("/") else a for a in args[:3])[:40] or "?"


def padre(pid: int) -> int:
    try:
        for linea in Path(f"/proc/{pid}/status").read_text().splitlines():
            if linea.startswith("PPid:"):
                return int(linea.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def quien(conexion: socket.socket, orden: dict) -> str:
    """Quién manda una orden de corte: lo que declara (origen, sesión) y su proceso con sus padres hasta
    la sesión de Claude Code que lo lanzó, si la hay."""
    partes = [str(orden["origen"])] if orden.get("origen") else []
    if orden.get("sesion"):
        partes.append(f"sesión {str(orden['sesion'])[:8]}")
    try:
        credenciales = conexion.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid = struct.unpack("3i", credenciales)[0]
    except OSError:
        pid = 0
    if pid:
        cadena, actual = [], pid
        while actual > 1 and len(cadena) < 4:
            cadena.append(describir(actual))
            if cadena[-1].startswith("claude") or cadena[-1] == "ya terminado":
                break
            actual = padre(actual)
        partes.append(f"pid {pid} " + " ← ".join(cadena))
    return " · ".join(partes) or "desconocido"


# --- vaciar y cortar --------------------------------------------------------------------

def vaciada(recibido: float, sesion: str | None) -> str | None:
    """Quién vació la cola después de que llegara esta frase, si alguien lo hizo (la frase ya no debe sonar)."""
    marcas = [vaciados.get("*")] + ([vaciados.get(sesion)] if sesion is not None else [])
    for marca in marcas:
        if marca and recibido < marca[0]:
            return marca[1]
    return None


def detener_actual(motivo: str) -> None:
    proc = estado["proc"]
    if proc and proc.poll() is None:
        estado["cortada"] = motivo
        proc.terminate()
    if estado["motor"]:
        estado["motor"].cancelar()


def _borrar(frase: "Frase") -> None:
    if frase.tmp:
        frase.tmp.unlink(missing_ok=True)


def vaciar(sesion: str | None = None, motivo: str = "desconocido") -> None:
    """Sin sesión lo descarta todo; con sesión, solo lo que dijo esa sesión. Alcanza a lo que espera en cola,
    a lo ya sintetizado y a lo que se esté sintetizando ahora mismo."""
    with cond:
        vaciados[sesion if sesion is not None else "*"] = (time.monotonic(), motivo)
        estado["generacion"] += 1
        mia = (lambda s: True) if sesion is None else (lambda s: s == sesion)
        antes = len(cola) + len(preparadas)
        quedan = [frase for frase in cola if not mia(frase[2])]
        cola.clear()
        cola.extend(quedan)
        for frase in [f for f in preparadas if mia(f.sesion)]:
            preparadas.remove(frase)
            _borrar(frase)
        descartadas = antes - len(cola) - len(preparadas)
        suena_otra = sesion is not None and estado["sesion"] != sesion  # lo que suena es de otra sesión
        if not suena_otra:
            estado["vaciada_por"] = motivo
        cond.notify_all()
    if descartadas:
        log(f"vaciadas {descartadas} frase(s) en cola ← {motivo}")
    if not suena_otra:
        detener_actual(motivo)


# --- sintetizar y reproducir ------------------------------------------------------------

def sintetizar(texto: str, recibido: float, sesion: str | None) -> "Frase | None":
    """La frase con su audio ya preparado por el primer motor de la cadena que funcione, o None."""
    for nombre in cadena(cfg["motor"]):
        try:
            m = motor(nombre)
            t0 = time.monotonic()
            orden, tmp = m.preparar(texto)
            return Frase(texto, recibido, sesion, nombre, orden, tmp, (time.monotonic() - t0) * 1000)
        except Exception as e:
            log(f"fallo {nombre}: {e}")
    log(f"ningún motor pudo decir «{texto[:60]}»")
    return None


def sintetizador() -> None:
    """Saca frases de la cola y las deja sintetizadas en `preparadas`, como mucho PREPARAR_MAX por delante."""
    while True:
        with cond:
            while not cola or len(preparadas) >= PREPARAR_MAX:
                cond.wait()
            texto, recibido, sesion = cola.popleft()
        frase = sintetizar(texto, recibido, sesion)
        if frase is None:
            continue
        with cond:
            motivo = vaciada(frase.recibido, frase.sesion)
            if motivo:
                _borrar(frase)
                log(f"{frase.nombre} descartada antes de sonar «{frase.texto[:60]}» ← {motivo}")
            else:
                preparadas.append(frase)
            cond.notify_all()


def reproducir(frase: "Frase") -> None:
    espera = (time.monotonic() - frase.recibido) * 1000
    try:
        estado["motor"] = motor(frase.nombre)
        estado["cortada"] = None
        estado["proc"] = subprocess.Popen(frase.orden, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rc = estado["proc"].wait()
        final = "cortada" if estado["cortada"] else f"rc={rc}"
        por = f" ← {estado['cortada']}" if estado["cortada"] else ""
        log(f"{frase.nombre} sintesis={frase.sintesis:.0f}ms hasta_sonar={espera:.0f}ms {final} «{frase.texto[:60]}»{por}")
    except OSError as e:
        log(f"no se pudo reproducir con {frase.orden[0]}: {e}")
    finally:
        estado["proc"] = None
        estado["motor"] = None
        _borrar(frase)


def reproductor() -> None:
    while True:
        with cond:
            while not preparadas:
                cond.wait()
            frase = preparadas.popleft()
            motivo = vaciada(frase.recibido, frase.sesion)
            if motivo:
                _borrar(frase)
                log(f"{frase.nombre} descartada antes de sonar «{frase.texto[:60]}» ← {motivo}")
                cond.notify_all()
                continue
            estado["sesion"] = frase.sesion
            cond.notify_all()  # ya hay sitio para preparar la siguiente mientras suena esta
        reproducir(frase)
        with cond:
            estado["sesion"] = None
        estado["actividad"] = time.monotonic()


def vigilante() -> None:
    while True:
        time.sleep(30)
        ocioso = time.monotonic() - estado["actividad"] > INACTIVIDAD_MAX
        if ocioso and not cola and not preparadas and estado["proc"] is None:
            log("apagado por inactividad")
            servidor.shutdown()
            return


# --- órdenes ----------------------------------------------------------------------------

def procesar(orden: dict, motivo: str = "desconocido"):
    """`motivo` dice quién manda la orden; solo cuenta en las que pueden cortar la voz."""
    global cfg
    estado["actividad"] = time.monotonic()
    cmd = orden.get("cmd")
    if cmd == "decir":
        texto = limpiar(str(orden.get("texto", "")))
        if not texto or cfg.get("silencio"):
            return None
        with cond:
            cola.append((texto, time.monotonic(), orden.get("sesion")))
            while len(cola) > max(1, int(cfg.get("cola_max", 4))):
                descartada = cola.popleft()[0]
                log(f"descartada por cola llena «{descartada[:60]}»")
            cond.notify_all()
    elif cmd == "saltar":
        detener_actual(f"saltar · {motivo}")
    elif cmd == "vaciar":
        vaciar(orden.get("sesion"), f"vaciar · {motivo}")
    elif cmd == "recargar":
        cfg = leer_config()
        if cfg.get("silencio"):
            vaciar(motivo=f"silencio · {motivo}")
    elif cmd == "estado":
        return {
            "pid": os.getpid(),
            "motor": cfg["motor"],
            "silencio": bool(cfg.get("silencio")),
            "en_cola": len(cola) + len(preparadas),
            "hablando": estado["proc"] is not None,
            "cargados": sorted(motores_cargados),
        }
    elif cmd == "salir":
        vaciar(motivo=f"salir · {motivo}")
        retirar_socket()  # los clientes nuevos ya arrancan otro daemon
        threading.Thread(target=servidor.shutdown, daemon=True).start()
    return None


def retirar_socket() -> None:
    """Borra el socket una sola vez: después puede ser de otro daemon."""
    global socket_retirado
    if not socket_retirado:
        socket_retirado = True
        ruta_socket().unlink(missing_ok=True)


class Manejador(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            orden = json.loads(self.rfile.readline().decode("utf-8"))
            motivo = quien(self.request, orden) if orden.get("cmd") in ORDENES_DE_CORTE else ""
            respuesta = procesar(orden, motivo)
        except Exception as e:
            log(f"orden inválida: {e}")
            return
        if respuesta is not None:
            self.wfile.write((json.dumps(respuesta, ensure_ascii=False) + "\n").encode("utf-8"))


def main() -> None:
    global servidor
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cerrojo = open(LOCK, "w")
    limite = time.monotonic() + 3  # margen por si el anterior se está cerrando
    while True:
        try:
            fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > limite:
                sys.exit(0)  # ya hay otro daemon
            time.sleep(0.1)
    if LOG.exists() and LOG.stat().st_size > 1_000_000:
        LOG.write_text("", encoding="utf-8")

    sock = ruta_socket()
    sock.unlink(missing_ok=True)
    servidor = socketserver.ThreadingUnixStreamServer(str(sock), Manejador)
    servidor.daemon_threads = True
    log(f"daemon {os.getpid()} escuchando; motor {cfg['motor']}")

    threading.Thread(target=sintetizador, daemon=True).start()
    threading.Thread(target=reproductor, daemon=True).start()
    threading.Thread(target=vigilante, daemon=True).start()
    # Precarga el motor en segundo plano para que la primera frase tarde menos.
    threading.Thread(target=_precargar, daemon=True).start()
    try:
        servidor.serve_forever()
    finally:
        retirar_socket()
        log(f"daemon {os.getpid()} parado")


def _precargar() -> None:
    try:
        motor(cadena(cfg["motor"])[0])
    except Exception as e:
        log(f"precarga fallida: {e}")


if __name__ == "__main__":
    main()
