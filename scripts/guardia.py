#!/usr/bin/env python3
"""Guardia del equipo, de momento SOLO EN MODO REGISTRO: anota qué comandos delicados se usan, para
decidir con datos qué bloquear. Nunca decide, nunca escribe en stdout y siempre sale con 0.

Se carga en caliente en sesiones activas, así que un fallo aquí no puede tocarlas. Registra categoría,
sesión y carpeta; nunca el comando ni la ruta, que pueden llevar secretos o datos de clientes.
"""

import fnmatch
import json
import os
import re
import shlex
import sys
import time
from collections import Counter
from pathlib import Path

from comun import RUNTIME
from riesgo import FORZADO, OPCIONES_GIT_CON_VALOR

REGISTRO = RUNTIME / "guardia.jsonl"
PROTEGIDAS = (".env*", "tenants/**")
SEPARADORES = set(";&|()")
ENVOLTORIOS = {"env", "command", "exec", "nohup", "nice", "time", "timeout", "stdbuf", "sudo", "xargs",
               "if", "then", "elif", "else", "while", "until", "do", "!", "{"}
SHELLS = {"sh", "bash", "zsh", "dash"}
ASIGNACION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _ordenes(comando: str) -> list[list[str]]:
    lex = shlex.shlex(comando.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:  # comillas sin cerrar: mejor algo aproximado que nada
        tokens = comando.split()
    ordenes, actual = [], []
    for t in tokens:
        if t and set(t) <= SEPARADORES:
            ordenes.append(actual)
            actual = []
        else:
            actual.append(t)
    return [o for o in ordenes + [actual] if o]


def _sin_envoltorios(orden: list[str]) -> list[str]:
    i = 0
    while i < len(orden):
        t = orden[i]
        if ASIGNACION.match(t) or t.startswith("-") or (i > 0 and t.replace(".", "").isdigit()):
            i += 1
        elif t.rsplit("/", 1)[-1] in ENVOLTORIOS:
            i += 1
        else:
            break
    return orden[i:]


def _de_git(orden: list[str]) -> list[str]:
    categorias = []
    i = 1
    while i < len(orden) and orden[i].startswith("-"):
        i += 2 if orden[i].split("=")[0] in OPCIONES_GIT_CON_VALOR and "=" not in orden[i] else 1
    sub, resto = (orden[i], orden[i + 1:]) if i < len(orden) else ("", [])
    if sub == "stash":
        categorias.append("stash")
    elif sub == "reset" and "--hard" in resto:
        categorias.append("reset_hard")
    elif sub == "push":
        forzado = any(a.split("=")[0] in FORZADO or a.startswith(("+", ":")) for a in resto)
        categorias.append("push_forzado" if forzado else "push")
    elif sub == "clean" and any(a == "--force" or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a) for a in resto):
        categorias.append("clean_f")
    elif sub == "branch" and ("-D" in resto or ("--delete" in resto and "--force" in resto)):
        categorias.append("branch_D")
    elif sub == "worktree" and resto[:1] == ["remove"]:
        categorias.append("worktree_remove")
    return categorias


def _de_bash(comando: str, profundidad: int = 0) -> list[str]:
    categorias = []
    for orden in _ordenes(comando):
        orden = _sin_envoltorios(orden)
        programa = orden[0].rsplit("/", 1)[-1] if orden else ""
        if programa == "git":
            categorias += _de_git(orden)
        elif programa in SHELLS and profundidad < 3:
            for j, t in enumerate(orden[:-1]):
                if t.startswith("-") and not t.startswith("--") and "c" in t:
                    categorias += _de_bash(orden[j + 1], profundidad + 1)
                    break
    return categorias


def _protegida(ruta: str, protegidas) -> bool:
    partes = Path(ruta).parts
    for patron in protegidas:
        if patron.endswith("/**"):
            if patron[:-3] in partes[:-1] or (patron[:-3] in partes and partes[-1] != patron[:-3]):
                return True
        elif partes and fnmatch.fnmatch(partes[-1], patron):
            return True
    return False


def categorias(herramienta: str, entrada, protegidas) -> list[str]:
    entrada = entrada if isinstance(entrada, dict) else {}
    if herramienta == "Bash":
        comando = entrada.get("command")
        return list(dict.fromkeys(_de_bash(comando))) if isinstance(comando, str) else []
    if herramienta in ("Edit", "Write", "NotebookEdit"):
        ruta = entrada.get("file_path") or entrada.get("notebook_path")
        return ["ruta_protegida"] if isinstance(ruta, str) and _protegida(ruta, protegidas) else []
    return []


def _anotar(fila: dict) -> None:
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(REGISTRO, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(fila, ensure_ascii=False) + "\n").encode())
    finally:
        os.close(fd)


def principal(args: list[str]) -> int:
    try:
        protegidas = PROTEGIDAS
        if "--protegidas" in args:
            protegidas = tuple(args[args.index("--protegidas") + 1].split(","))
        evento = json.load(sys.stdin)
        _anotar({"cuando": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sesion": str(evento.get("session_id") or "")[:8],
                 "agente": evento.get("agent_type"), "carpeta": Path(str(evento.get("cwd") or "")).name,
                 "herramienta": evento.get("tool_name"),
                 "categorias": categorias(evento.get("tool_name"), evento.get("tool_input"), protegidas)})
    except Exception:
        pass
    return 0


def comando_hook(script=None) -> str:
    script = script or Path(__file__).resolve()
    # `|| true` es imprescindible: si el script desaparece, python sale con 2, que en PreToolUse bloquearía
    return f"python3 {shlex.quote(str(script))} --modo registro >/dev/null 2>&1 || true"


def configuracion(script=None) -> dict:
    return {"hooks": {"PreToolUse": [{"matcher": "Bash|Edit|Write|NotebookEdit", "hooks": [
        {"type": "command", "command": comando_hook(script), "async": True}]}]}}


def resumen() -> None:
    llamadas, por_categoria, por_carpeta = 0, Counter(), Counter()
    if REGISTRO.exists():
        for linea in REGISTRO.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                fila = json.loads(linea)
            except ValueError:
                continue
            llamadas += 1
            por_carpeta[fila.get("carpeta") or "?"] += 1
            por_categoria.update(fila.get("categorias") or [])
    print(f"{llamadas} llamadas vistas; por carpeta: {dict(por_carpeta)}")
    for c, n in por_categoria.most_common():
        print(f"  {c}: {n}")
    if not por_categoria:
        print("  ninguna categoría vigilada")


if __name__ == "__main__":
    os._exit(principal(sys.argv[1:]))
