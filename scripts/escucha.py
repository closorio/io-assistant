"""Lado ligero del oído: arrancarlo, entregar sus frases al mentor y controlar la pausa.

`narrador escuchar` es lo que corre dentro de Monitor: da latido para que el oído siga vivo,
y por cada frase dirigida a Ío imprime una línea `[voz] …`. Solo biblioteca estándar.
"""

import fcntl
import json
import os
import signal
import sys
import time

from comun import (
    OIDO, OIDO_CONSUMIDOR, OIDO_LOCK, OIDO_PID, OIDO_SALIDA, OIDO_VIVO, RUNTIME, VENV_PY,
    arrancar_daemon, enviar_arrancando, guardar_config, leer_config,
)

DUENOS = {"io": "Ío", "mentor": "el mentor"}

REANUDAR = 15 * 60  # s: con una posición guardada más reciente, se sigue donde se quedó
LATIDO = 5  # s entre latidos
REVISION = 5  # s entre comprobaciones de que el oído sigue vivo
MARGEN_ARRANQUE = 15  # s que se le dan al oído para coger el cerrojo antes de revisarlo
REINICIOS_MAX = 3


def oido_en_marcha() -> bool:
    try:
        with open(OIDO_LOCK, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True


def latido() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    OIDO_VIVO.touch()


def formato(registro: dict) -> str:
    evento = registro.get("evento")
    if evento == "listo":
        return f"[voz] (te escucho; empieza la frase por «{registro.get('nombre', 'Ío')}» para hablarme)"
    if evento == "error":
        return f"[voz] error: {registro.get('detalle', 'desconocido')}"
    if registro.get("confirmacion"):
        return (f"[voz] (respuesta a una confirmación: «{registro.get('texto', '')}». "
                "El sistema ya la ha aplicado: no hagas nada con ella)")
    return f"[voz] {registro.get('texto', '')}"


def tomar_consumidor(dueno: str):
    """Solo una sesión recibe tus frases. Devuelve el archivo con el cerrojo (mantenerlo abierto)."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cerrojo = open(OIDO_CONSUMIDOR, "a+")
    try:
        fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        cerrojo.seek(0)
        actual = cerrojo.read().strip() or "otra sesión"
        raise SystemExit(f"[voz] error: ya te escucha {DUENOS.get(actual, actual)}; ciérralo antes")
    cerrojo.seek(0)
    cerrojo.truncate()
    cerrojo.write(dueno)
    cerrojo.flush()
    return cerrojo


def escuchar(dueno: str = "mentor") -> None:
    if not VENV_PY.exists():
        raise SystemExit("[voz] error: falta el venv con faster-whisper; ejecuta scripts/instalar.sh")
    cerrojo = tomar_consumidor(dueno)  # noqa: F841 (se mantiene abierto mientras escucha)
    posicion = RUNTIME / f"oido-{dueno}.pos"
    latido()
    arrancado = 0.0
    if not oido_en_marcha():
        arrancar_daemon(OIDO)
        arrancado = time.monotonic()
    pos = OIDO_SALIDA.stat().st_size if OIDO_SALIDA.exists() else 0
    try:
        guardada = json.loads(posicion.read_text(encoding="utf-8"))
        if time.time() - guardada["t"] < REANUDAR and guardada["pos"] <= pos:
            pos = guardada["pos"]  # Monitor caducó y se rearmó: no se pierde lo que dijiste entretanto
    except (OSError, ValueError, KeyError):
        pass
    resto = b""
    reinicios = 0
    ultimo_latido = revision = time.monotonic()
    while True:
        ahora = time.monotonic()
        if ahora - ultimo_latido >= LATIDO:
            latido()
            ultimo_latido = ahora
        if OIDO_SALIDA.exists():
            if OIDO_SALIDA.stat().st_size < pos:
                pos, resto = 0, b""  # el oído vació su archivo al arrancar
            with open(OIDO_SALIDA, "rb") as f:
                f.seek(pos)
                datos = f.read()
            if datos:
                pos += len(datos)
                lineas = (resto + datos).split(b"\n")
                resto = lineas.pop()
                for linea in lineas:
                    try:
                        print(formato(json.loads(linea)), flush=True)
                    except ValueError:
                        continue
                posicion.write_text(json.dumps({"pos": pos - len(resto), "t": time.time()}), encoding="utf-8")
        if ahora - revision >= REVISION and ahora - arrancado >= MARGEN_ARRANQUE:
            revision = ahora
            if not oido_en_marcha():
                if reinicios >= REINICIOS_MAX:
                    raise SystemExit("[voz] error: el oído se ha caído varias veces; mira narrador.log")
                reinicios += 1
                arrancar_daemon(OIDO)
                arrancado = ahora
        time.sleep(0.3)


def decir(texto: str) -> None:
    try:
        enviar_arrancando({"cmd": "decir", "texto": texto})
    except OSError:
        pass


def pausar(pausa: bool | None) -> None:
    """True pausa, False reanuda, None alterna. Lo confirma en voz alta (útil desde un atajo)."""
    cfg = leer_config()
    nueva = (not cfg["escucha"].get("pausa")) if pausa is None else pausa
    cfg["escucha"]["pausa"] = nueva
    guardar_config(cfg)
    print("escucha en pausa" if nueva else "escucha activa")
    decir("Dejo de escucharte." if nueva else "Te escucho.")


def estado() -> None:
    cfg = leer_config()["escucha"]
    if oido_en_marcha():
        pid = OIDO_PID.read_text(encoding="utf-8").strip() if OIDO_PID.exists() else "?"
        print(f"oído en marcha (pid {pid}) · {'en pausa' if cfg.get('pausa') else 'escuchando'}"
              f" · nombre «{cfg['nombre']}» · ventana {cfg['ventana']} s · modelo {cfg['modelo']}")
    else:
        print(f"oído parado (lo arranca Ío o /narrador:mentor) · {'en pausa' if cfg.get('pausa') else 'activo'}")


def parar() -> None:
    try:
        os.kill(int(OIDO_PID.read_text(encoding="utf-8")), signal.SIGTERM)
        print("oído parado")
    except (OSError, ValueError):
        print("el oído no está en marcha")


def main(args: list[str]) -> None:
    accion = args[0] if args else "estado"
    acciones = {
        "estado": estado,
        "pausa": lambda: pausar(True),
        "activar": lambda: pausar(False),
        "alternar": lambda: pausar(None),
        "parar": parar,
    }
    if accion not in acciones:
        sys.exit("uso: narrador escucha [estado|pausa|activar|alternar|parar]")
    acciones[accion]()
