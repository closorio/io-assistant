#!/usr/bin/env python3
"""Hook PreToolUse de Ío: pide confirmación antes de lo que sale en nombre del usuario.

Solo actúa en la sesión de Ío (la de io.json): enviar o responder correos, tocar el
calendario y `git push`. Pregunta en pantalla (`ask`) y lo dice en voz alta. Todo lo demás
pasa sin decir nada. Nunca falla: ante cualquier error sale sin decisión.
"""

import json
import sys

from comun import IO_JSON, enviar_arrancando
from riesgo import CONFIRMAR, clasificar


def es_sesion_de_io(sesion: str | None) -> bool:
    try:
        return bool(sesion) and json.loads(IO_JSON.read_text(encoding="utf-8")).get("session_id") == sesion
    except (OSError, ValueError):
        return False


def decidir(datos: dict) -> dict | None:
    if datos.get("hook_event_name") != "PreToolUse" or not es_sesion_de_io(datos.get("session_id")):
        return None
    v = clasificar(datos.get("tool_name") or "", datos.get("tool_input") or {}, str(datos.get("cwd") or ""))
    if v.nivel != CONFIRMAR:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": f"Ío va a {v.resumen}" + (". Acción de alto impacto." if v.alta else "."),
    }}


def main() -> None:
    datos = json.load(sys.stdin)
    salida = decidir(datos)
    if not salida:
        return
    try:
        resumen = salida["hookSpecificOutput"]["permissionDecisionReason"]
        enviar_arrancando({"cmd": "decir", "texto": f"Necesito tu permiso en pantalla. {resumen}", "sesion": datos.get("session_id")})
    except Exception:
        pass
    print(json.dumps(salida, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
