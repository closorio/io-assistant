"""Almacén local del tablero de hallazgos: un solo JSON, con cerrojo y escritura atómica.

Sin lógica de negocio: qué es una tarjeta válida y cómo se mueve lo decide tablero.py.
Quien escribe toma antes `con_cerrojo` y hace leer → modificar → guardar dentro; quien solo
lee no bloquea, porque el archivo se sustituye de una vez (os.replace).
"""

import fcntl
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

VERSION = 1
ESPERA = 5.0  # segundos que aguarda un escritor a que otro termine


class ArchivoRoto(ValueError):
    """El archivo existe pero no es un tablero legible. Nunca se trata como tablero vacío."""


class CerrojoOcupado(Exception):
    """Otro escritor no ha soltado el cerrojo a tiempo."""


def vacio() -> dict:
    return {"v": VERSION, "rev": 0, "parte_fecha": None, "ultimo_movimiento": None, "tarjetas": {}}


def leer(ruta: Path) -> dict:
    """El tablero guardado. Sin archivo lanza FileNotFoundError; ilegible, ArchivoRoto."""
    texto = Path(ruta).read_text(encoding="utf-8")
    try:
        estado = json.loads(texto)
    except ValueError as e:
        raise ArchivoRoto(f"{ruta}: no es JSON ({e})") from e
    if not (
        isinstance(estado, dict) and estado.get("v") == VERSION
        and isinstance(estado.get("rev"), int) and isinstance(estado.get("tarjetas"), dict)
        and isinstance(estado.get("ultimo_movimiento"), (dict, type(None)))
    ):
        raise ArchivoRoto(f"{ruta}: no tiene la forma de un tablero v{VERSION}")
    return estado


@contextmanager
def con_cerrojo(ruta: Path, espera: float = ESPERA):
    """Cerrojo exclusivo entre procesos (flock sobre tablero.lock, junto al archivo)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    limite = time.monotonic() + espera
    with open(ruta.with_suffix(".lock"), "w") as cerrojo:
        while True:
            try:
                fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= limite:
                    raise CerrojoOcupado(f"otro proceso está escribiendo {ruta.name}") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(cerrojo, fcntl.LOCK_UN)


def guardar(ruta: Path, estado: dict) -> dict:
    """Escribe el tablero de una vez, sube `rev` y deja la versión anterior en .bak. Llámalo con el cerrojo tomado."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    estado = {**estado, "v": VERSION, "rev": int(estado.get("rev", 0)) + 1}
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(estado, ensure_ascii=False, indent=1) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if ruta.exists():
            shutil.copy2(ruta, ruta.with_suffix(ruta.suffix + ".bak"))
        os.replace(tmp, ruta)
    finally:
        tmp.unlink(missing_ok=True)
    return estado
