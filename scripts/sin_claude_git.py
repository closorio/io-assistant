#!/usr/bin/env python3
"""Hook PreToolUse global: ninguna referencia a Claude ni a Anthropic llega a git.

Regla del usuario (2026-11-11): nunca subir referencias a Anthropic o Claude en commits
ni en PR. Se aplica a todas las sesiones de este equipo, no solo a la de Ío.

- `git commit …`: deniega si el texto del comando (mensaje, heredoc) las menciona.
- `git push …`: deniega si algún commit que aún no está en un remoto las lleva en el
  mensaje, el autor o el committer.
- `gh pr create|edit …`: deniega si el título o el cuerpo las mencionan.

Las rutas `.claude/…` y el nombre de archivo `CLAUDE.md` no cuentan. Ante cualquier
error interno sale sin decisión (nunca rompe una sesión).
"""

import json
import re
import subprocess
import sys

PROHIBIDO = re.compile(r"claude|anthropic", re.IGNORECASE)
INOCUO = re.compile(r"\S*\.claude/\S*|CLAUDE\.md", re.IGNORECASE)
# Solo en posición de comando: al principio o tras ; && || | ( o salto de línea.
INICIO = r"(?:^|[;&|(\n])\s*(?:\w+=[^\s'\"]*\s+)*"
COMMIT = re.compile(INICIO + r"git(?:\s+-[cC]\s+\S+)*\s+commit\b")
PUSH = re.compile(INICIO + r"git(?:\s+-[cC]\s+\S+)*\s+push\b")
PR = re.compile(INICIO + r"gh\s+pr\s+(?:create|edit)\b")


def menciona(texto: str) -> bool:
    return bool(PROHIBIDO.search(INOCUO.sub(" ", texto)))


def commits_sin_subir(cwd: str) -> str:
    r = subprocess.run(
        ["git", "log", "--format=%an %ae %cn %ce%n%B", "--branches", "HEAD", "--not", "--remotes"],
        cwd=cwd or None, capture_output=True, text=True, timeout=10,
    )
    return r.stdout if r.returncode == 0 else ""


FIN = re.compile(r"\s(?:&&|\|\|)\s")


def tramo(comando: str, patron: re.Pattern) -> str | None:
    """El trozo del comando desde la orden hasta el siguiente && o ||."""
    m = patron.search(comando)
    if not m:
        return None
    resto = comando[m.start():]
    f = FIN.search(resto, 1)
    return resto[: f.start()] if f else resto


def motivo(comando: str, cwd: str) -> str | None:
    t = tramo(comando, COMMIT)
    if t and menciona(t):
        return "el mensaje del commit menciona a Claude o Anthropic (incluido Co-Authored-By)"
    t = tramo(comando, PR)
    if t and menciona(t):
        return "el título o el cuerpo del PR mencionan a Claude o Anthropic"
    if PUSH.search(comando) and menciona(commits_sin_subir(cwd)):
        return "hay commits sin subir que mencionan a Claude o Anthropic; reescríbelos antes del push"
    return None


def decidir(datos: dict) -> dict | None:
    if datos.get("hook_event_name") != "PreToolUse" or datos.get("tool_name") != "Bash":
        return None
    comando = str((datos.get("tool_input") or {}).get("command") or "")
    m = motivo(comando, str(datos.get("cwd") or ""))
    if not m:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Bloqueado: {m}. Regla del usuario: nunca referencias a Claude ni a Anthropic en git ni en PR.",
    }}


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
