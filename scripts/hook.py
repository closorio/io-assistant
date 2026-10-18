#!/usr/bin/env python3
"""Hook del narrador.

MessageDisplay: envía al daemon las líneas que empiezan por 🎙️.
UserPromptSubmit: vacía la cola para que el narrador se calle cuando escribes,
pero solo lo que dijo esta sesión: escribir en la ejecutora no corta al mentor.
Los avisos que mete Claude Code (eventos de Monitor como `[voz]` o el parte, tareas en
segundo plano que terminan) también disparan este hook, pero no los has escrito tú:
no callan la voz.

Nunca escribe en stdout (en UserPromptSubmit entraría en el contexto) y nunca
falla: cualquier error termina con código 0 sin decir nada.
"""

import json
import re
import sys
import time

from comun import LOG, MARCA, enviar, enviar_arrancando

AVISO = "<task-notification>"  # así empiezan los eventos de Monitor y las tareas en segundo plano


def lineas_narradas(texto: str) -> list[str]:
    narradas = []
    for linea in texto.splitlines():
        limpia = linea.strip().lstrip(">*_- \t")
        if not limpia.startswith(MARCA):
            continue
        frase = limpia[len(MARCA):].lstrip("️").strip(" *_:\t")
        if frase:
            narradas.append(frase)
    return narradas


def es_aviso(prompt) -> bool:
    """Un aviso de Claude Code (Monitor, tarea en segundo plano), no algo que has escrito tú."""
    return str(prompt or "").lstrip().startswith(AVISO)


def resumen_aviso(prompt: str) -> str:
    m = re.search(r"<summary>(.*?)</summary>", prompt, re.S)
    return " ".join((m.group(1) if m else prompt.lstrip()[len(AVISO):]).split())[:70]


def anotar(mensaje: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} hook: {mensaje}\n")


def main() -> None:
    datos = json.load(sys.stdin)
    evento = datos.get("hook_event_name")
    sesion = datos.get("session_id")
    if evento == "MessageDisplay":
        for frase in lineas_narradas(datos.get("delta") or ""):
            enviar_arrancando({"cmd": "decir", "texto": frase, "sesion": sesion})
    elif evento == "UserPromptSubmit":
        prompt = str(datos.get("prompt") or "")
        if es_aviso(prompt):
            anotar(f"aviso «{resumen_aviso(prompt)}» en la sesión {str(sesion)[:8]}: no callo la voz")
            return
        texto = " ".join(prompt.split())[:40]
        try:
            enviar({"cmd": "vaciar", "sesion": sesion, "origen": f"hook: has escrito «{texto}»"})
        except OSError:
            pass  # sin daemon no hay nada que callar


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
