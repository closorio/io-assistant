"""Capacidades de Ío desde la CLI: sesiones vivas, proyectos, trabajadores, recordatorios y guías.

Solo biblioteca estándar. Lo usa bin/narrador; Ío lo llama por Bash.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from comun import PROYECTOS_CLAUDE, RAICES, RAIZ, RUNTIME, TRABAJADORES, binario_claude, enviar_arrancando
from visor import PROPIA, hace, metadatos_cwd, recortar

MARCAS = {".git", "CLAUDE.md", "package.json", "pyproject.toml", "composer.json", "requirements.txt",
          "go.mod", "Cargo.toml", "docker-compose.yml", "compose.yaml"}
IGNORAR = {"node_modules", "Archivado", "venv", ".venv", "__pycache__", "dist", "build", "vendor"}
GUIAS = RAIZ / "skills"  # las guías son las skills io-<tema>; `narrador guia` es el respaldo
CASA = str(Path.home())


def corta(ruta: str) -> str:
    return ruta.replace(CASA, "~")


def claude() -> str:
    binario = binario_claude()
    if not binario:
        raise SystemExit("no encuentro el binario de claude (ni en el PATH ni en la extensión de VS Code)")
    return binario


def transcript(cwd: str, sesion: str) -> Path:
    return PROYECTOS_CLAUDE / re.sub(r"[^A-Za-z0-9]", "-", cwd) / f"{sesion}.jsonl"


# --- sesiones vivas ----------------------------------------------------------------

def agentes(todas: bool = False) -> list[dict]:
    orden = [claude(), "agents", "--json"] + (["--all"] if todas else [])
    salida = subprocess.run(orden, capture_output=True, text=True, timeout=30).stdout
    try:
        return json.loads(salida or "[]")
    except ValueError:
        return []


def vivas() -> None:
    lista = agentes()
    if not lista:
        print("no hay sesiones de Claude Code abiertas")
        return
    for a in lista:
        sesion, cwd = a.get("sessionId", ""), a.get("cwd", "")
        titulo = ""
        archivo = transcript(cwd, sesion)
        if archivo.exists():
            titulo = metadatos_cwd(archivo, completo=False)[0]
        marca = " (esta)" if sesion == PROPIA else ""
        print(f"{a.get('name', '?')}{marca}  {a.get('status', '?')}  {a.get('kind', '?')}  {corta(cwd)}"
              f"\n    sesión {sesion[:8]}  «{titulo or 'sin título'}»")


# --- proyectos ---------------------------------------------------------------------

def _buscar(raiz: Path, profundidad: int = 4) -> list[Path]:
    encontrados = []
    pendientes = [(raiz, 0)]
    while pendientes:
        carpeta, nivel = pendientes.pop()
        try:
            hijos = list(carpeta.iterdir())
        except OSError:
            continue
        nombres = {h.name for h in hijos}
        if carpeta != raiz and nombres & MARCAS:
            encontrados.append(carpeta)
            continue
        if nivel < profundidad:
            pendientes += [(h, nivel + 1) for h in hijos
                           if h.is_dir() and not h.name.startswith(".") and h.name not in IGNORAR]
    return encontrados


def _ultima_sesion() -> dict[str, tuple[float, str]]:
    """cwd → (mtime, título) de su sesión más reciente."""
    ultima: dict[str, tuple[float, str]] = {}
    for carpeta in PROYECTOS_CLAUDE.iterdir() if PROYECTOS_CLAUDE.exists() else []:
        archivos = sorted(carpeta.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not archivos:
            continue
        titulo, _, cwd = metadatos_cwd(archivos[0], completo=False)
        if cwd:
            ultima[cwd] = (archivos[0].stat().st_mtime, titulo)
    return ultima


def lista_proyectos() -> list[tuple[Path, float, str]]:
    """(ruta, última actividad, título de su última sesión), lo más reciente primero."""
    sesiones = _ultima_sesion()
    rutas = {p for raiz in RAICES if raiz.exists() for p in _buscar(raiz)}
    rutas |= {Path(c) for c in sesiones if Path(c).exists() and any(Path(c).is_relative_to(r) for r in RAICES)}
    filas = []
    for p in rutas:
        mtime, titulo = sesiones.get(str(p), (0.0, ""))
        try:
            mtime = max(mtime, p.stat().st_mtime)
        except OSError:
            pass
        filas.append((p, mtime, titulo))
    return sorted(filas, key=lambda f: f[1], reverse=True)


def rama(p: Path) -> str:
    try:
        cabeza = (p / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return cabeza.rsplit("/", 1)[-1] if cabeza.startswith("ref:") else cabeza[:8]


def proyectos(todos: bool = False, git: bool = False) -> None:
    ahora = time.time()
    filas = lista_proyectos()
    for p, mtime, titulo in filas if todos else filas[:25]:
        extra = []
        if rama(p):
            extra.append(f"rama {rama(p)}")
        if git and (p / ".git").exists():
            try:
                cambios = subprocess.run(["git", "-C", str(p), "status", "--porcelain"], capture_output=True,
                                         text=True, timeout=3).stdout.count("\n")
                extra.append(f"{cambios} cambios sin confirmar" if cambios else "limpio")
            except subprocess.TimeoutExpired:
                pass
        if titulo:
            extra.append(f"última sesión «{recortar(titulo, 50)}»")
        print(f"{corta(str(p))}  hace {hace(ahora - mtime)}" + (f"\n    {' · '.join(extra)}" if extra else ""))
    if not todos and len(filas) > 25:
        print(f"… y {len(filas) - 25} más (narrador proyectos --todos)")


def resolver_proyecto(texto: str) -> Path:
    if texto.startswith(("/", "~")):
        p = Path(os.path.expanduser(texto))
        if p.is_dir():
            return p
        raise SystemExit(f"no existe la carpeta {texto}")
    candidatos = [f[0] for f in lista_proyectos()]
    exactos = [p for p in candidatos if p.name.lower() == texto.lower()]
    if len(exactos) == 1:
        return exactos[0]
    parecidos = [p for p in candidatos if texto.lower() in str(p).lower()]
    if len(parecidos) == 1:
        return parecidos[0]
    if not parecidos:
        raise SystemExit(f"no encuentro ningún proyecto que se parezca a «{texto}» (mira narrador proyectos)")
    raise SystemExit("«" + texto + "» encaja con varios proyectos:\n" + "\n".join(f"  {corta(str(p))}" for p in parecidos[:8]))


# --- trabajadores ------------------------------------------------------------------

def _registro() -> list[dict]:
    try:
        return json.loads(TRABAJADORES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _guardar(lista: list[dict]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    TRABAJADORES.write_text(json.dumps(lista[-50:], ensure_ascii=False, indent=1), encoding="utf-8")


PLANTILLA_CONTRATO = """{tarea}

--- Contrato del encargo (de Ío) ---
- No toques nada que no pida la tarea. No hagas commits ni `git push` ni envíes nada fuera.
- Comprueba lo que hagas (ejecuta las pruebas si las hay).
- Al terminar, escribe en el archivo {ruta} (créalo) lo siguiente: primero, un resumen de 5 líneas como mucho, en español llano
  y sin código, apto para leerse en voz alta (qué hiciste y si funcionó); después, una lista de lo que queda pendiente y de lo que falló.
- Tu última respuesta repite ese resumen."""


def _archivo_resultado(nombre: str) -> Path:
    return RUNTIME / "trabajadores" / f"{nombre}.md"


def lanzar(proyecto: str, tarea: str, modelo: str | None = None, contrato: bool = False) -> None:
    ruta = resolver_proyecto(proyecto)
    nombre = f"io-{re.sub(r'[^a-z0-9]+', '-', ruta.name.lower()).strip('-')[:24]}-{time.strftime('%H%M%S')}"
    original = tarea
    if contrato:
        _archivo_resultado(nombre).parent.mkdir(parents=True, exist_ok=True)
        tarea = PLANTILLA_CONTRATO.format(tarea=tarea, ruta=_archivo_resultado(nombre))
    comunes = ["--permission-mode", "auto"] + (["--model", modelo] if modelo else [])
    entorno = dict(os.environ, NARRADOR_IO="1")
    registro = {"nombre": nombre, "ruta": str(ruta), "tarea": original, "contrato": contrato, "modelo": modelo, "inicio": time.time()}
    r = subprocess.run([claude(), "--bg", "--name", nombre, *comunes, tarea], cwd=ruta, env=entorno,
                       capture_output=True, text=True, timeout=90)
    salida = (r.stdout + r.stderr).strip()
    if r.returncode == 0 and "not trusted" not in salida.lower():
        registro["tipo"] = "bg"
        print(f"trabajador {nombre} lanzado en segundo plano en {corta(str(ruta))}")
        print(f"  {recortar(salida, 200)}")
        print(f"  míralo con: narrador trabajador lista · ábrelo con: narrador trabajador abrir {nombre}")
    else:
        # carpeta sin confianza para --bg: sesión sin interfaz, que siempre se puede retomar después
        sesion = str(uuid.uuid4())
        carpeta = RUNTIME / "trabajadores"
        carpeta.mkdir(parents=True, exist_ok=True)
        log = carpeta / f"{sesion}.log"
        with open(log, "w", encoding="utf-8") as salida_log:
            proc = subprocess.Popen(
                [claude(), "-p", "--session-id", sesion, *comunes, "--output-format", "stream-json", "--verbose", tarea],
                cwd=ruta, env=entorno, stdin=subprocess.DEVNULL, stdout=salida_log, stderr=subprocess.STDOUT,
                start_new_session=True)
        registro.update(tipo="p", session_id=sesion, pid=proc.pid, log=str(log))
        print(f"trabajador {nombre} lanzado sin interfaz en {corta(str(ruta))} (la carpeta no es de confianza para --bg)")
        print(f"  sesión {sesion}")
        print(f"  síguelo con: narrador seguir {sesion} · estado: narrador trabajador lista")
    lista = _registro()
    lista.append(registro)
    _guardar(lista)


def _estado_p(t: dict) -> tuple[str, str]:
    """(estado, resultado) de un trabajador sin interfaz, leyendo su log de stream-json."""
    resultado = ""
    try:
        with open(t["log"], encoding="utf-8", errors="replace") as f:
            for linea in f:
                if '"type":"result"' in linea.replace(" ", ""):
                    try:
                        r = json.loads(linea)
                    except ValueError:
                        continue
                    estado = "falló" if r.get("is_error") else "terminado"
                    return estado, recortar(r.get("result") or "", 160)
    except OSError:
        return "sin log", ""
    try:
        os.kill(int(t.get("pid", 0)), 0)
        return "trabajando", resultado
    except (OSError, ValueError):
        return "parado sin resultado", resultado


def lista_trabajadores() -> None:
    lista = _registro()
    if not lista:
        print("no has lanzado ningún trabajador")
        return
    vivos = {a.get("name"): a for a in agentes(todas=True)} if any(t.get("tipo") == "bg" for t in lista) else {}
    ahora = time.time()
    for t in lista[-12:]:
        if t.get("tipo") == "bg":
            a = vivos.get(t["nombre"], {})
            estado, sesion, resultado = a.get("status", "desconocido"), a.get("sessionId", ""), ""
        else:
            (estado, resultado), sesion = _estado_p(t), t.get("session_id", "")
        if not resultado and t.get("contrato"):
            try:
                resultado = recortar(" ".join(_archivo_resultado(t["nombre"]).read_text(encoding="utf-8").split()), 160)
            except OSError:
                pass
        print(f"{t['nombre']}  {estado}  hace {hace(ahora - t['inicio'])}  {corta(t['ruta'])}"
              f"\n    tarea: «{recortar(t['tarea'], 80)}»" + (f"  sesión {sesion[:8]}" if sesion else "")
              + (f"\n    resultado: {resultado}" if resultado else ""))


def abrir(nombre: str) -> None:
    t = next((t for t in reversed(_registro()) if t["nombre"] == nombre or nombre in t["nombre"]), None)
    if not t:
        raise SystemExit(f"no hay ningún trabajador «{nombre}» (mira narrador trabajador lista)")
    terminal = shutil.which("gnome-terminal")
    if not terminal:
        raise SystemExit("no encuentro gnome-terminal")
    if t.get("tipo") == "bg":
        orden = [claude(), "attach", t["nombre"]]
    else:
        orden = [claude(), "--resume", t["session_id"]]
    subprocess.Popen([terminal, f"--title={t['nombre']}", f"--working-directory={t['ruta']}", "--", *orden],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"abierto {t['nombre']} en una terminal nueva")


def trabajador(args: list[str]) -> None:
    uso = "uso: narrador trabajador lanzar PROYECTO \"TAREA\" [--modelo opus] [--contrato] | lista | abrir NOMBRE"
    if not args or args[0] == "lista":
        lista_trabajadores()
    elif args[0] == "lanzar" and len(args) >= 3:
        resto = args[1:]
        modelo = None
        if "--modelo" in resto:
            i = resto.index("--modelo")
            modelo = resto[i + 1] if i + 1 < len(resto) else None
            resto = resto[:i] + resto[i + 2:]
        contrato = "--contrato" in resto
        resto = [a for a in resto if a != "--contrato"]
        lanzar(resto[0], " ".join(resto[1:]), modelo, contrato)
    elif args[0] == "abrir" and len(args) == 2:
        abrir(args[1])
    else:
        sys.exit(uso)


# --- escritorio y guías -------------------------------------------------------------

def aviso(texto: str) -> None:
    """Lo que dispara un recordatorio: notificación y voz."""
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Ío", "Ío", texto], check=False)
    try:
        enviar_arrancando({"cmd": "decir", "texto": texto})
    except OSError:
        pass


def recordar(minutos: str, texto: str) -> None:
    try:
        espera = float(minutos.replace(",", "."))
    except ValueError:
        raise SystemExit("uso: narrador recordar MINUTOS TEXTO")
    unidad = f"narrador-recordatorio-{int(time.time())}"
    orden = ["systemd-run", "--user", f"--on-active={max(1, round(espera * 60))}s", f"--unit={unidad}",
             f"--description=Recordatorio de Ío: {texto[:40]}",
             shutil.which("python3") or "/usr/bin/python3", str(RAIZ / "bin" / "narrador"), "aviso", texto]
    r = subprocess.run(orden, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"no pude programar el recordatorio: {r.stderr.strip()}")
    print(f"te lo recuerdo dentro de {minutos} min ({unidad}); para anularlo: systemctl --user stop {unidad}.timer")


def guia(tema: str | None) -> None:
    disponibles = sorted(p.parent.name.removeprefix("io-") for p in GUIAS.glob("io-*/SKILL.md"))
    if not tema:
        print("guías: " + ", ".join(disponibles) + "  (narrador guia TEMA)")
        return
    archivo = GUIAS / f"io-{tema}" / "SKILL.md"
    if not archivo.exists():
        raise SystemExit(f"no hay guía «{tema}»; hay: {', '.join(disponibles)}")
    texto = archivo.read_text(encoding="utf-8")
    if texto.startswith("---"):
        texto = texto.split("---", 2)[2].lstrip("\n")
    print(texto)
