#!/usr/bin/env python3
"""Hook Stop de Ío: comprueba el cierre de cada turno.

Solo actúa en la sesión de Ío (la de io.json). Bloquea, una vez por turno, dos fallos claros:
- el turno acaba con una lista de pendientes para el usuario en texto, sin AskUserQuestion;
- hay una sesión o un trabajador que Ío abrió, sigue vivo y nadie lo espera.
Una pregunta en texto solo se anota (puede ser un «¿me lo repites?»). Nunca falla: ante cualquier
error sale con 0 y sin decisión. El registro guarda el caso, nunca el texto del turno.
"""

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

from comun import RUNTIME
from pretool import es_sesion_de_io

REGISTRO = RUNTIME / "cierre.jsonl"
PREGUNTA = "AskUserQuestion"
ADORNO = r"[\s#>*_\-\d.]*"
CABECERA = re.compile(ADORNO + r"(Pendientes?(?: tuyos?| del usuario)?|Falta|Queda pendiente|Te toca|Por tu parte|De tu parte)"
                      r"[*_]*\s*(?::|$)", re.I)
TAREA_SUYA = re.compile(ADORNO + r"(Usuario|Tú)[*_]*\s*:", re.I)

AVISO_PENDIENTES = ("Has cerrado el turno con pendientes para el usuario en texto. Reclasifícalos ahora: haz tú o lanza lo que "
                    "depende de nosotros; lo que es una puerta, pregúntalo con AskUserQuestion (opciones, la recomendada "
                    "primero, selección múltiple si son independientes); lo que depende de terceros o de firmas va como "
                    "bloqueo externo, con su alternativa y lo que ya está preparado, nunca como tarea suya. "
                    "Por voz, solo «tienes la pregunta en pantalla».")
AVISO_VIGILANCIA = "Has abierto algo y nadie lo espera. Arranca ahora un Monitor (timeout_ms 1800000) con cada orden: "


def pendientes_en_texto(textos: list[str]) -> bool:
    for texto in textos:
        for linea in texto.splitlines():
            if CABECERA.match(linea) or TAREA_SUYA.match(linea):
                return True
    return False


def acaba_en_pregunta(textos: list[str]) -> bool:
    lineas = [linea for linea in (textos[-1] if textos else "").splitlines() if linea.strip()]
    return bool(lineas) and lineas[-1].rstrip(" *_»\"”)").endswith("?")


def revisar(textos: list[str], usos: list[str], sueltas: list[dict]) -> tuple[str | None, list[str]]:
    """(motivo para bloquear o None, casos vistos). Sin E/S."""
    casos, avisos = [], []
    pregunto = PREGUNTA in usos
    if not pregunto and pendientes_en_texto(textos):
        casos.append("pendientes_en_texto")
        avisos.append(AVISO_PENDIENTES)
    if sueltas:
        casos.append("sin_vigilar")
        avisos.append(AVISO_VIGILANCIA + "; ".join(f"`{s['orden']}` («{s['nombre']}»)" for s in sueltas) + ".")
    if not pregunto and acaba_en_pregunta(textos):
        casos.append("pregunta_en_texto")  # solo se anota
    return (" ".join(avisos) or None), casos


def anotar(casos: list[str], accion: str) -> None:
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    fila = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "casos": casos, "accion": accion}
    fd = os.open(REGISTRO, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(fila, ensure_ascii=False) + "\n").encode())
    finally:
        os.close(fd)


def decidir(datos: dict) -> dict | None:
    if datos.get("hook_event_name") != "Stop" or not es_sesion_de_io(datos.get("session_id")):
        return None
    from visor import ultimo_turno
    textos, usos = [], []
    try:
        textos, usos = ultimo_turno(Path(str(datos.get("transcript_path") or "")))
    except OSError:
        pass
    final = str(datos.get("last_assistant_message") or "")
    if final.strip() and final not in textos:  # por si el transcript aún no lo tiene
        textos.append(final)
    try:
        from abrir_sesion import sin_vigilar
        sueltas = sin_vigilar()
    except Exception:
        sueltas = []
    motivo, casos = revisar(textos, usos, sueltas)
    if not casos:
        return None
    repetido = bool(datos.get("stop_hook_active"))  # ya se avisó en este turno: no se insiste
    bloquea = bool(motivo) and not repetido
    try:
        anotar(casos, "bloqueo" if bloquea else ("repetido" if motivo else "registro"))
    except OSError:
        pass
    return {"decision": "block", "reason": motivo} if bloquea else None


def resumen() -> int:
    por_caso, por_accion = Counter(), Counter()
    if REGISTRO.exists():
        for linea in REGISTRO.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                fila = json.loads(linea)
            except ValueError:
                continue
            por_accion[fila.get("accion") or "?"] += 1
            por_caso.update(fila.get("casos") or [])
    print(f"cierres anotados: {sum(por_accion.values())} · {dict(por_accion)}")
    for caso, n in por_caso.most_common():
        print(f"  {caso}: {n}")
    return 0


def main() -> None:
    salida = decidir(json.load(sys.stdin))
    if salida:
        print(json.dumps(salida, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
