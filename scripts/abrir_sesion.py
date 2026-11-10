"""Abre una sesión viva de Claude Code para verla y responder a sus permisos.

  narrador sesion abrir NOMBRE|ID

- Sesión en segundo plano (trabajador): terminal nueva con `claude attach`, enganchada a su chat.
- Sesión interactiva (terminal o VS Code): trae su ventana al frente con wmctrl.

Busca en ~/.claude/sessions/*.json por nombre exacto, prefijo del id o parte del nombre.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from asistente import SIN_SESION, claude, entorno_limpio

SESIONES = Path.home() / ".claude" / "sessions"


def _viva(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def buscar(clave: str) -> dict | None:
    vivas = []
    for f in SESIONES.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _viva(d.get("pid")):
            vivas.append(d)
    for criterio in (lambda d: d.get("name") == clave,
                     lambda d: str(d.get("sessionId", "")).startswith(clave),
                     lambda d: clave.lower() in str(d.get("name", "")).lower()):
        hallados = [d for d in vivas if criterio(d)]
        if len(hallados) == 1:
            return hallados[0]
        if len(hallados) > 1:
            raise SystemExit(f"«{clave}» coincide con varias sesiones: "
                             + ", ".join(str(d.get("name") or d.get("sessionId", "")[:8]) for d in hallados))
    return None


def ancestros(pid: int) -> list[int]:
    salida = []
    while pid > 1:
        salida.append(pid)
        try:
            campos = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            pid = int(campos[1])
        except (OSError, ValueError, IndexError):
            break
    return salida


def ventanas() -> list[tuple[str, int, str]]:
    """(id, pid, título) de cada ventana, según wmctrl -lp."""
    r = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=5)
    filas = []
    for linea in r.stdout.splitlines():
        partes = linea.split(None, 4)
        if len(partes) >= 4:
            try:
                filas.append((partes[0], int(partes[2]), partes[4] if len(partes) > 4 else ""))
            except ValueError:
                continue
    return filas


def elegir_ventana(ses: dict, filas: list[tuple[str, int, str]]) -> str | None:
    linaje = set(ancestros(int(ses["pid"])))
    nombre = str(ses.get("name") or "")
    carpeta = Path(ses.get("cwd", "")).name
    propias = [f for f in filas if f[1] in linaje]
    candidatas = propias or filas
    for pista in (nombre, carpeta):
        if pista:
            con = [f for f in candidatas if pista.lower() in f[2].lower()]
            if con:
                return con[0][0]
    # una sola ventana del mismo proceso (VS Code, terminal propia): esa
    return propias[0][0] if len(propias) == 1 else None


def abrir(clave: str) -> int:
    ses = buscar(clave)
    if not ses:
        print(f"no hay ninguna sesión viva «{clave}» (mira narrador sesiones --vivas)", file=sys.stderr)
        return 1
    nombre = str(ses.get("name") or ses["sessionId"][:8])
    if ses.get("kind") in ("bg", "background"):
        terminal = shutil.which("gnome-terminal")
        if not terminal:
            print("no encuentro gnome-terminal", file=sys.stderr)
            return 1
        subprocess.Popen([terminal, f"--title={nombre}", f"--working-directory={ses.get('cwd', str(Path.home()))}",
                          "--", "bash", "-c", SIN_SESION + "", "io", "bash", "-c",
                          '"$@" || { echo; echo "No se pudo enganchar a la sesión. Pulsa Enter para cerrar."; read; }',
                          "io", claude(), "attach", str(ses["sessionId"])[:8]],
                         env=entorno_limpio(), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"abierta {nombre} en una terminal nueva")
        return 0
    if not shutil.which("wmctrl"):
        print("falta wmctrl para traer la ventana al frente (sudo apt install wmctrl)", file=sys.stderr)
        return 1
    ventana = elegir_ventana(ses, ventanas())
    if not ventana:
        print(f"no encuentro la ventana de {nombre}", file=sys.stderr)
        return 1
    subprocess.run(["wmctrl", "-ia", ventana], timeout=5)
    print(f"ventana de {nombre} al frente")
    return 0


def main(args: list[str]) -> int:
    if len(args) == 2 and args[0] == "abrir":
        return abrir(args[1])
    print(__doc__.strip(), file=sys.stderr)
    return 2
