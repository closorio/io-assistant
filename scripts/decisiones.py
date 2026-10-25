#!/usr/bin/env python3
"""Captura de decisiones: antes de una decisión de calado, Claude tiene que decir por qué.

Hook PreToolUse para los settings de usuario de Claude Code (ver README, «Captura de
decisiones»). Vigila:
  - Write/Edit sobre un plan (`~/.claude/plans/*.md`) y ExitPlanMode;
  - Bash que lanza un trabajador (`narrador trabajador lanzar`, `claude --bg`, `claude -p`);
  - lo que añada `decisiones/config.json` (otras herramientas u otros comandos).

Si la llamada no trae la razón, la bloquea (`deny`) y le pide a Claude repetirla con una
línea «Por qué: …» (en el plan, en el new_string, en el texto de ExitPlanMode o como
comentario `# Por qué: …` en el comando), o con un archivo `<plan>.porque` junto al plan.
Si la trae, la deja pasar y la apunta en `decisiones.jsonl`, append-only, una línea JSON
por decisión. Nunca falla: ante un error propio sale sin decisión y la llamada pasa.

También es la CLI de `narrador decisiones listar | ruta`.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from comun import RUNTIME

DIR = RUNTIME / "decisiones"
REGISTRO = DIR / "decisiones.jsonl"
CONFIG = DIR / "config.json"  # opcional; no existe hasta que lo crees
PLANES = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "plans"
VERSION = 1  # versión del formato de cada línea del registro

CONFIG_DEFECTO = {
    "activo": True,
    "editar_plan": True,  # también cada Edit sobre un plan, no solo crearlo o reescribirlo
    "herramientas": [],  # regex de nombres de herramienta que también piden razón (p. ej. "Agent")
    "bash": [  # regex de comandos que también piden razón
        r"\bnarrador\s+trabajador\s+lanzar\b",
        r"\bclaude\b[^|;&\n]*\s(--bg|-p|--print)\b",
    ],
    "razon_min": 15,  # caracteres mínimos de una razón
    "plan_reciente_min": 60,  # ExitPlanMode sin texto: vale la razón del plan escrito hace menos de esto
}

# «Por qué: …» o «Porque: …» al principio de una línea, o tras #, // o <!--
MARCA = re.compile(r"(?im)(?:^[ \t>*_-]*|#[ \t]*|//[ \t]*|<!--[ \t]*)por[ \t]*qu[eé][ \t]*:[ \t]*(.+?)[ \t]*(?:-->|\*/)?[ \t]*$")
SUFIJO_RAZON = ".porque"


def leer_config() -> dict:
    cfg = dict(CONFIG_DEFECTO)
    try:
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


# --- qué es una decisión -------------------------------------------------------------

def es_plan(ruta) -> bool:
    if not ruta:
        return False
    p = Path(str(ruta)).expanduser()
    try:
        p = p.resolve()
        planes = PLANES.resolve()
    except OSError:
        return False
    return p.suffix == ".md" and planes in p.parents


def clasificar(herramienta: str, entrada: dict, cfg: dict) -> tuple[str, str] | None:
    """(tipo, objetivo) si la llamada es una decisión que pide razón; None si no."""
    if herramienta in ("Write", "Edit", "MultiEdit") and es_plan(entrada.get("file_path")):
        if herramienta == "Write":
            return "plan_escribir", str(entrada["file_path"])
        return ("plan_editar", str(entrada["file_path"])) if cfg["editar_plan"] else None
    if herramienta == "ExitPlanMode":
        return "plan_aprobar", "ExitPlanMode"
    if herramienta == "Bash":
        comando = str(entrada.get("command") or "")
        if any(re.search(p, comando) for p in cfg["bash"]):
            tipo = "trabajador" if re.search(r"trabajador|claude", comando) else "comando"
            return tipo, " ".join(comando.split())[:300]
    if any(re.fullmatch(p, herramienta) for p in cfg["herramientas"]):
        return "otra", herramienta
    return None


def resumen(tipo: str, objetivo: str, entrada: dict) -> str:
    """Qué iba a hacer, en una línea."""
    if tipo in ("plan_escribir", "plan_editar"):
        texto = entrada.get("content") or entrada.get("new_string") or ""
        titulo = next((l.lstrip("# ").strip() for l in str(texto).splitlines() if l.startswith("#")), "")
        verbo = "escribir" if tipo == "plan_escribir" else "editar"
        return f"{verbo} el plan {Path(objetivo).name}" + (f" «{titulo[:80]}»" if titulo else "")
    if tipo == "plan_aprobar":
        texto = str(entrada.get("plan") or "")
        titulo = next((l.lstrip("# ").strip() for l in texto.splitlines() if l.strip()), "")
        return "salir del modo plan y pedir aprobación" + (f" de «{titulo[:80]}»" if titulo else "")
    if tipo in ("trabajador", "comando"):
        return f"ejecutar: {objetivo[:200]}"
    return f"usar {objetivo}"


# --- dónde está la razón -------------------------------------------------------------

def textos(valor):
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from textos(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from textos(v)


def razon_en_texto(texto: str, minimo: int) -> str | None:
    for m in MARCA.finditer(texto or ""):
        razon = m.group(1).strip().strip("\"'")
        if len(razon) >= minimo:
            return razon
    return None


def plan_reciente(minutos: float) -> Path | None:
    try:
        planes = [p for p in PLANES.glob("*.md") if time.time() - p.stat().st_mtime < minutos * 60]
    except OSError:
        return None
    return max(planes, key=lambda p: p.stat().st_mtime, default=None)


def buscar_razon(tipo: str, objetivo: str, entrada: dict, cfg: dict) -> tuple[str, str, Path | None] | None:
    """(razón, fuente, archivo de razón a consumir) o None.

    Fuentes: «marcador» en cualquier texto de la llamada; «archivo» `<plan>.porque` junto al
    plan; «plan» la línea «Por qué:» del plan reciente cuando ExitPlanMode llega sin texto."""
    minimo = int(cfg["razon_min"])
    for texto in textos(entrada):
        if (r := razon_en_texto(texto, minimo)):
            return r, "marcador", None
    planes = [Path(objetivo).expanduser()] if tipo in ("plan_escribir", "plan_editar") else []
    if tipo == "plan_aprobar" and (p := plan_reciente(cfg["plan_reciente_min"])):
        planes.append(p)
    for plan in planes:
        lado = plan.with_name(plan.name + SUFIJO_RAZON)
        try:
            texto = lado.read_text(encoding="utf-8").strip()
        except OSError:
            texto = ""
        razon = razon_en_texto(texto, minimo) or " ".join(texto.split())
        if len(razon) >= minimo:
            return razon, "archivo", lado
        if tipo == "plan_aprobar":
            try:
                if (r := razon_en_texto(plan.read_text(encoding="utf-8"), minimo)):
                    return r, "plan", None
            except OSError:
                pass
    return None


# --- el hook ---------------------------------------------------------------------------

def mensaje_bloqueo(tipo: str, objetivo: str, minimo: int) -> str:
    if tipo in ("plan_escribir", "plan_editar"):
        donde = ("añade al contenido (o al new_string) una línea «Por qué: <tu razón>» "
                 "(vale como comentario: «<!-- Por qué: … -->»), o escribe antes la razón en "
                 f"{objetivo}{SUFIJO_RAZON}")
    elif tipo == "plan_aprobar":
        donde = "incluye en el texto del plan una línea «Por qué: <tu razón>», o ponla en el archivo del plan"
    elif tipo in ("trabajador", "comando"):
        donde = "añade al final del comando un comentario «# Por qué: <tu razón>»"
    else:
        donde = "incluye en algún campo de texto de la llamada una línea «Por qué: <tu razón>»"
    return (f"Captura de decisiones: antes de esto, di por qué. {donde[0].upper()}{donde[1:]} y repite la llamada. "
            f"La razón (al menos {minimo} caracteres) es el motivo real de la decisión: qué problema resuelve "
            "o por qué eliges esto y no otra cosa. Se guarda en el registro de decisiones del usuario.")


def apuntar(registro: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    linea = json.dumps(registro, ensure_ascii=False) + "\n"
    # una sola escritura en modo append: las líneas de sesiones a la vez no se mezclan
    fd = os.open(REGISTRO, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, linea.encode("utf-8"))
    finally:
        os.close(fd)


def decidir(datos: dict) -> dict | None:
    if datos.get("hook_event_name") != "PreToolUse":
        return None
    cfg = leer_config()
    if not cfg.get("activo", True):
        return None
    herramienta = str(datos.get("tool_name") or "")
    entrada = datos.get("tool_input") or {}
    clase = clasificar(herramienta, entrada, cfg)
    if not clase:
        return None
    tipo, objetivo = clase
    hallada = buscar_razon(tipo, objetivo, entrada, cfg)
    if not hallada:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": mensaje_bloqueo(tipo, objetivo, int(cfg["razon_min"])),
        }}
    razon, fuente, archivo = hallada
    cwd = str(datos.get("cwd") or "")
    apuntar({
        "v": VERSION,
        "fecha": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sesion": datos.get("session_id"),
        "proyecto": Path(cwd).name if cwd else None,
        "cwd": cwd or None,
        "herramienta": herramienta,
        "tipo": tipo,
        "objetivo": objetivo,
        "accion": resumen(tipo, objetivo, entrada),
        "razon": razon,
        "fuente": fuente,
    })
    if archivo:  # la razón del archivo vale para esta llamada, no para las siguientes
        try:
            archivo.unlink()
        except OSError:
            pass
    return None


def main_hook() -> None:
    salida = decidir(json.load(sys.stdin))
    if salida:
        print(json.dumps(salida, ensure_ascii=False))


# --- la CLI ----------------------------------------------------------------------------

def leer_registro() -> list[dict]:
    try:
        lineas = REGISTRO.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    salida = []
    for linea in lineas:
        try:
            salida.append(json.loads(linea))
        except ValueError:
            continue  # una línea a medias no tumba el listado
    return salida


def filtrar(registros: list[dict], sesion=None, proyecto=None, desde=None, tipo=None) -> list[dict]:
    def vale(r):
        return ((not sesion or str(r.get("sesion") or "").startswith(sesion))
                and (not proyecto or proyecto.lower() in str(r.get("proyecto") or "").lower())
                and (not desde or str(r.get("fecha") or "") >= desde)
                and (not tipo or r.get("tipo") == tipo))
    return [r for r in registros if vale(r)]


USO = ("uso: narrador decisiones listar [-n N] [--sesion ID] [--proyecto P] [--desde AAAA-MM-DD] "
       "[--tipo plan_escribir|plan_editar|plan_aprobar|trabajador|comando|otra] [--json] | ruta")


def main(args: list[str]) -> int:
    if not args or args[0] in ("-h", "--help"):
        print(USO)
        return 0
    if args[0] == "ruta":
        print(REGISTRO)
        return 0
    if args[0] != "listar":
        print(USO, file=sys.stderr)
        return 2
    opciones = {"-n": "20", "--sesion": None, "--proyecto": None, "--desde": None, "--tipo": None}
    como_json = False
    resto = args[1:]
    while resto:
        a = resto.pop(0)
        if a == "--json":
            como_json = True
        elif a in opciones and resto:
            opciones[a] = resto.pop(0)
        else:
            print(USO, file=sys.stderr)
            return 2
    registros = filtrar(leer_registro(), opciones["--sesion"], opciones["--proyecto"], opciones["--desde"], opciones["--tipo"])
    n = int(opciones["-n"])
    registros = registros[-n:] if n > 0 else registros
    if como_json:
        for r in registros:
            print(json.dumps(r, ensure_ascii=False))
        return 0
    if not registros:
        print(f"no hay decisiones apuntadas (registro: {REGISTRO})")
        return 0
    for r in registros:
        print(f"{str(r.get('fecha', ''))[:16].replace('T', ' ')} · {r.get('proyecto') or '?'} · "
              f"{str(r.get('sesion') or '')[:8]} · {r.get('accion')}")
        print(f"    por qué: {r.get('razon')}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main(sys.argv[1:]))
    try:
        main_hook()
    except Exception:
        pass
    sys.exit(0)
