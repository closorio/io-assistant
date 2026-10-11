#!/usr/bin/env python3
"""Daemon del narrador: recibe frases por un socket unix y las dice de una en una.

Órdenes (una línea JSON por conexión): decir, saltar, vaciar, recargar, estado, salir.
Abre el socket antes de cargar el motor para que el primer hook no espere al modelo.
"""

import fcntl
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import time
import unicodedata
from collections import deque

from comun import LOCK, LOG, RUNTIME, leer_config, ruta_socket
from motores import MOTORES, cadena

INACTIVIDAD_MAX = 45 * 60
TEXTO_MAX = 400

cfg = leer_config()
cola: deque = deque()
cond = threading.Condition()
estado = {
    "proc": None, "motor": None, "cortada": False, "generacion": 0, "actividad": time.monotonic(),
    "sesion": None,  # sesión de Claude Code de la frase que se sintetiza o suena
}
motores_cargados: dict = {}  # nombre -> (firma de config, instancia)
carga = threading.Lock()  # la precarga y el trabajador no deben cargar a la vez
servidor = None
socket_retirado = False


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


def detener_actual() -> None:
    proc = estado["proc"]
    if proc and proc.poll() is None:
        estado["cortada"] = True
        proc.terminate()
    if estado["motor"]:
        estado["motor"].cancelar()


def vaciar(sesion: str | None = None) -> None:
    """Sin sesión lo descarta todo; con sesión, solo lo que dijo esa sesión."""
    with cond:
        if sesion is None:
            cola.clear()
        else:
            quedan = [frase for frase in cola if frase[2] != sesion]
            cola.clear()
            cola.extend(quedan)
            if estado["sesion"] != sesion:
                return  # lo que suena es de otra sesión
        estado["generacion"] += 1
    detener_actual()


def hablar(texto: str, recibido: float, generacion: int) -> None:
    for nombre in cadena(cfg["motor"]):
        try:
            m = motor(nombre)
            t0 = time.monotonic()
            orden, tmp = m.preparar(texto)
            sintesis = (time.monotonic() - t0) * 1000
        except Exception as e:
            log(f"fallo {nombre}: {e}")
            continue
        try:
            if generacion != estado["generacion"]:
                return  # se vació la cola mientras sintetizaba
            espera = (time.monotonic() - recibido) * 1000
            estado["motor"] = m
            estado["cortada"] = False
            estado["proc"] = subprocess.Popen(orden, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            rc = estado["proc"].wait()
            final = "cortada" if estado["cortada"] else f"rc={rc}"
            log(f"{nombre} sintesis={sintesis:.0f}ms hasta_sonar={espera:.0f}ms {final} «{texto[:60]}»")
        except OSError as e:
            log(f"no se pudo reproducir con {orden[0]}: {e}")
        finally:
            estado["proc"] = None
            estado["motor"] = None
            if tmp:
                tmp.unlink(missing_ok=True)
        return
    log(f"ningún motor pudo decir «{texto[:60]}»")


def trabajador() -> None:
    while True:
        with cond:
            while not cola:
                cond.wait()
            texto, recibido, estado["sesion"] = cola.popleft()
            generacion = estado["generacion"]
        hablar(texto, recibido, generacion)
        with cond:
            estado["sesion"] = None
        estado["actividad"] = time.monotonic()


def vigilante() -> None:
    while True:
        time.sleep(30)
        ocioso = time.monotonic() - estado["actividad"] > INACTIVIDAD_MAX
        if ocioso and not cola and estado["proc"] is None:
            log("apagado por inactividad")
            servidor.shutdown()
            return


def procesar(orden: dict):
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
            cond.notify()
    elif cmd == "saltar":
        detener_actual()
    elif cmd == "vaciar":
        vaciar(orden.get("sesion"))
    elif cmd == "recargar":
        cfg = leer_config()
        if cfg.get("silencio"):
            vaciar()
    elif cmd == "estado":
        return {
            "pid": os.getpid(),
            "motor": cfg["motor"],
            "silencio": bool(cfg.get("silencio")),
            "en_cola": len(cola),
            "hablando": estado["proc"] is not None,
            "cargados": sorted(motores_cargados),
        }
    elif cmd == "salir":
        vaciar()
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
            respuesta = procesar(orden)
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

    threading.Thread(target=trabajador, daemon=True).start()
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
