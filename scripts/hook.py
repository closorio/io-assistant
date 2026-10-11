#!/usr/bin/env python3
"""Hook del narrador.

MessageDisplay: envía al daemon las líneas que empiezan por 🎙️.
UserPromptSubmit: vacía la cola para que el narrador se calle cuando escribes,
pero solo lo que dijo esta sesión: escribir en la ejecutora no corta al mentor.

Nunca escribe en stdout (en UserPromptSubmit entraría en el contexto) y nunca
falla: cualquier error termina con código 0 sin decir nada.
"""

import json
import sys

from comun import MARCA, enviar, enviar_arrancando


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


def main() -> None:
    datos = json.load(sys.stdin)
    evento = datos.get("hook_event_name")
    sesion = datos.get("session_id")
    if evento == "MessageDisplay":
        for frase in lineas_narradas(datos.get("delta") or ""):
            enviar_arrancando({"cmd": "decir", "texto": frase, "sesion": sesion})
    elif evento == "UserPromptSubmit":
        try:
            enviar({"cmd": "vaciar", "sesion": sesion})
        except OSError:
            pass  # sin daemon no hay nada que callar


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
