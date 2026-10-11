"""Visor: sigue el transcript de otra sesión de Claude Code y emite un resumen por turno.

Lo usa la sesión mentora a través de Monitor: cada resumen sale de golpe por stdout,
en varias líneas seguidas, para que llegue como un solo evento. Solo biblioteca estándar.
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from comun import RUNTIME

PROYECTOS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
ESTADO = RUNTIME / "visor"
PROPIA = os.environ.get("CLAUDE_CODE_SESSION_ID", "")  # la sesión mentora no se sigue a sí misma

SONDEO = 0.5  # s entre lecturas del transcript
QUIETUD = 2.0  # s sin registros nuevos tras end_turn para dar el turno por cerrado
AVANCE = 180  # s de turno largo con actividad nueva antes de mandar un resumen parcial
REANUDAR = 15 * 60  # s: con un estado guardado más reciente, se sigue donde se quedó
CAMBIO = 5  # s entre comprobaciones de si hay una sesión ejecutora más nueva (tras /clear)
COLA = 256 * 1024  # bytes del final del transcript que bastan para el título y el cwd

INTERRUPCION = "[Request interrupted by user]"
ESPERAN_USUARIO = {"AskUserQuestion", "ExitPlanMode"}


def recortar(texto: str, n: int) -> str:
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def hace(segundos: float) -> str:
    s = int(max(0, segundos))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 2 * 86400:
        return f"{s // 3600} h {s % 3600 // 60} min"
    return f"{s // 86400} días"


def instante(registro: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(registro["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None


def carpeta_proyecto(ruta: str | None = None) -> Path:
    return PROYECTOS / re.sub(r"[^A-Za-z0-9]", "-", ruta or os.getcwd())


def sesiones(carpeta: Path) -> list[Path]:
    """Transcripts del proyecto, el más reciente primero, sin la sesión propia."""
    archivos = [f for f in carpeta.glob("*.jsonl") if f.stem != PROPIA]
    return sorted(archivos, key=lambda f: f.stat().st_mtime, reverse=True)


def metadatos(archivo: Path, completo: bool = True) -> tuple[str, str]:
    """Último título y último mensaje del usuario que Claude Code guardó en el transcript."""
    titulo, ultimo, _ = metadatos_cwd(archivo, completo)
    return titulo, ultimo


def metadatos_cwd(archivo: Path, completo: bool = True) -> tuple[str, str, str]:
    """(título, último mensaje, cwd). Sin `completo`, lee primero el final del archivo (rápido)."""
    def recorrer(lineas) -> tuple[str, str, str]:
        titulo = ultimo = cwd = ""
        for linea in lineas:
            interesa = '"ai-title"' in linea or '"last-prompt"' in linea
            if not interesa and cwd:
                continue
            try:
                r = json.loads(linea)
            except ValueError:
                continue
            titulo = r.get("aiTitle") or titulo
            ultimo = r.get("lastPrompt") or ultimo
            cwd = r.get("cwd") or cwd
        return titulo, ultimo, cwd

    if not completo:
        with open(archivo, "rb") as f:
            f.seek(max(0, archivo.stat().st_size - COLA))
            lineas = f.read().decode("utf-8", "replace").splitlines()[1:]
        datos = recorrer(lineas)
        if datos[0] and datos[2]:
            return datos
    with open(archivo, encoding="utf-8", errors="replace") as f:
        return recorrer(f)


def primer_instante(archivo: Path) -> datetime | None:
    with open(archivo, encoding="utf-8", errors="replace") as f:
        for linea in f:
            try:
                momento = instante(json.loads(linea))
            except ValueError:
                continue
            if momento:
                return momento
    return None


def resolver(carpeta: Path, sesion: str) -> Path:
    if sesion.endswith(".jsonl") and Path(sesion).exists():
        return Path(sesion)
    candidatos = [f for f in carpeta.glob("*.jsonl") if f.stem.startswith(sesion)]
    if not candidatos:  # una sesión de otro proyecto: Ío las sigue todas
        candidatos = [f for f in PROYECTOS.glob(f"*/{sesion}*.jsonl")]
    if len(candidatos) != 1:
        raise SystemExit(f"[visor] la sesión «{sesion}» no es única o no existe")
    return candidatos[0]


def recientes(n: int = 10) -> list[Path]:
    """Los transcripts más recientes de todos los proyectos, sin la sesión propia."""
    archivos = [f for f in PROYECTOS.glob("*/*.jsonl")
                if f.stem != PROPIA and not f.parent.name.startswith("-tmp-")]  # sin sesiones de carpetas temporales
    return sorted(archivos, key=lambda f: f.stat().st_mtime, reverse=True)[:n]


def texto_usuario(contenido) -> str:
    if isinstance(contenido, str):
        texto = contenido
    elif isinstance(contenido, list):
        texto = " ".join(b.get("text", "") for b in contenido if b.get("type") == "text")
    else:
        return ""
    comando = re.search(r"<command-name>(.*?)</command-name>", texto, re.S)
    if comando:
        argumentos = re.search(r"<command-args>(.*?)</command-args>", texto, re.S)
        return " ".join([comando.group(1), argumentos.group(1) if argumentos else ""]).strip()
    texto = re.sub(r"<([a-z][\w-]*)[^>]*>.*?</\1>", " ", texto, flags=re.S)  # system-reminder, ide_selection…
    return " ".join(texto.split())


def texto_resultado(contenido) -> str:
    if isinstance(contenido, list):
        return " ".join(b.get("text", "") for b in contenido if isinstance(b, dict))
    return str(contenido or "")


def detalle(bloque: dict) -> str:
    entrada = bloque.get("input") or {}
    for clave in ("file_path", "notebook_path"):
        if entrada.get(clave):
            return Path(entrada[clave]).name
    for clave in ("description", "pattern", "query", "skill", "url", "command", "prompt"):
        if entrada.get(clave):
            return recortar(entrada[clave], 60)
    return ""


def resumen_herramientas(usos: list[tuple[str, str]]) -> str:
    grupos: dict[str, list] = {}
    for nombre, det in usos:
        grupo = grupos.setdefault(nombre, [0, []])
        grupo[0] += 1
        if det and det not in grupo[1]:
            grupo[1].append(det)
    partes = []
    for nombre, (veces, detalles) in grupos.items():
        parte = f"{nombre} ×{veces}" if veces > 1 else nombre
        if detalles:
            parte += f" ({', '.join(detalles[:4])}{', …' if len(detalles) > 4 else ''})"
        partes.append(parte)
    return "; ".join(partes)


class Turno:
    def __init__(self, n: int, prompt: str, inicio: datetime | None):
        self.n = n
        self.prompt = prompt
        self.inicio = self.fin = inicio
        self.usos: list[tuple[str, str]] = []
        self.errores: list[str] = []
        self.texto = ""
        self.cerrado = False
        self.interrumpido = False
        self.esperando = ""  # herramienta que espera al usuario (AskUserQuestion…)
        self.novedad = False  # hay algo que no se ha emitido todavía
        self.prompt_emitido = False
        self.ultima_emision = time.monotonic()

    def resumen(self, estado: str) -> list[str]:
        duracion = ""
        if self.inicio and self.fin:
            duracion = f" · {hace((self.fin - self.inicio).total_seconds())}"
        lineas = [f"[visor] turno {self.n} · {estado}{duracion}"]
        if self.prompt and not self.prompt_emitido:
            lineas.append(f"Usuario: «{recortar(self.prompt, 400)}»")
        if self.usos:
            lineas.append(f"Herramientas ({len(self.usos)}): {resumen_herramientas(self.usos)}")
        if self.errores:
            lineas.append("Errores: " + " | ".join(self.errores[:3]))
        if self.texto:
            lineas.append(f"Claude: «{recortar(self.texto, 700)}»")
        return lineas

    def vaciar_emitido(self) -> None:
        self.prompt_emitido = True
        self.usos, self.errores, self.texto = [], [], ""
        self.novedad = False
        self.ultima_emision = time.monotonic()


class Lector:
    """Lee el transcript por incrementos y arma los turnos."""

    def __init__(self, archivo: Path):
        self.archivo = archivo
        self.pos = 0
        self.resto = b""
        self.n = 0
        self.turno: Turno | None = None
        self.anterior: Turno | None = None
        self.nombres: dict[str, str] = {}  # tool_use_id -> herramienta
        self.ultimo_registro = time.monotonic()
        self.estado = ESTADO / f"{archivo.stem}.json"

    # --- lectura ---

    def nuevos(self) -> list[dict]:
        if self.archivo.stat().st_size < self.pos:
            self.pos, self.resto = 0, b""  # el archivo se reescribió
        with open(self.archivo, "rb") as f:
            f.seek(self.pos)
            datos = f.read()
        if not datos:
            return []
        self.pos += len(datos)
        lineas = (self.resto + datos).split(b"\n")
        self.resto = lineas.pop()
        registros = []
        for linea in lineas:
            try:
                registros.append(json.loads(linea))
            except ValueError:
                continue
        return registros

    def guardar(self) -> None:
        ESTADO.mkdir(parents=True, exist_ok=True)
        datos = {"pos": self.pos - len(self.resto), "n": self.n, "en_curso": bool(self.turno), "t": time.time()}
        self.estado.write_text(json.dumps(datos), encoding="utf-8")

    # --- turnos ---

    def cerrar_turno(self) -> None:
        if self.turno:
            self.anterior = self.turno
        self.turno = None

    def procesar(self, r: dict, vivo: bool) -> None:
        if r.get("isSidechain") or r.get("isMeta"):
            return
        tipo = r.get("type")
        contenido = (r.get("message") or {}).get("content")
        if tipo == "user":
            if isinstance(contenido, list):
                for b in contenido:
                    if b.get("type") == "tool_result" and self.turno:
                        nombre = self.nombres.get(b.get("tool_use_id"), "herramienta")
                        if nombre == self.turno.esperando:
                            self.turno.esperando = ""
                        if b.get("is_error"):
                            self.turno.errores.append(f"{nombre}: {recortar(texto_resultado(b.get('content')), 120)}")
                            self.turno.novedad = True
            texto = texto_usuario(contenido)
            if not texto:
                return
            if texto == INTERRUPCION:
                if self.turno:
                    self.turno.interrumpido = self.turno.cerrado = True
                return
            if self.turno and vivo and (self.turno.novedad or not self.turno.prompt_emitido):
                self.emitir("terminado" if self.turno.cerrado else "interrumpido")
            self.cerrar_turno()
            self.n += 1
            self.turno = Turno(self.n, texto, instante(r))
        elif tipo == "assistant" and isinstance(contenido, list):
            if not self.turno:  # turno sin mensaje del usuario (una notificación, una tarea de fondo…)
                self.n += 1
                self.turno = Turno(self.n, "", instante(r))
                self.turno.prompt_emitido = True
            t = self.turno
            t.fin = instante(r) or t.fin
            for b in contenido:
                if b.get("type") == "tool_use":
                    nombre = b.get("name", "?")
                    nombre = nombre.split("__")[-1] if nombre.startswith("mcp__") else nombre
                    self.nombres[b.get("id", "")] = nombre
                    t.usos.append((nombre, detalle(b)))
                    if nombre in ESPERAN_USUARIO:
                        t.esperando = nombre
                    t.novedad = True
                elif b.get("type") == "text" and b.get("text", "").strip():
                    t.texto = b["text"]
                    t.novedad = True
            if (r.get("message") or {}).get("stop_reason") == "end_turn":
                t.cerrado = True

    def emitir(self, estado: str) -> None:
        t = self.turno
        print("\n".join(t.resumen(estado)), flush=True)
        t.vaciar_emitido()
        if estado in ("terminado", "interrumpido"):
            self.cerrar_turno()
        self.guardar()

    # --- ciclo ---

    def arrancar(self) -> None:
        try:
            guardado = json.loads(self.estado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            guardado = None
        if guardado and time.time() - guardado["t"] < REANUDAR and guardado["pos"] <= self.archivo.stat().st_size:
            self.pos, self.n = guardado["pos"], guardado["n"]  # Monitor caducó y se rearmó: sin repetir nada
            if guardado.get("en_curso"):
                self.turno = Turno(self.n, "", None)
                self.turno.prompt_emitido = True
            return
        for r in self.nuevos():
            self.procesar(r, vivo=False)
        titulo, _ = metadatos(self.archivo)
        lineas = [f"[visor] siguiendo la sesión «{titulo or 'sin título'}» ({self.archivo.stem[:8]}) · {self.n} turnos hasta ahora"]
        primero = self.primer_encargo()
        if primero:
            lineas.append(f"Primer encargo: «{recortar(primero, 300)}»")
        en_curso = self.turno and not self.turno.cerrado
        if self.turno and self.turno.cerrado:
            self.cerrar_turno()
        if self.anterior:
            lineas.append("Último turno cerrado:")
            lineas += self.anterior.resumen("terminado")[1:] or ["(sin contenido)"]
        if en_curso:
            lineas.append(f"El turno {self.turno.n} está en curso: «{recortar(self.turno.prompt, 200)}»")
            self.turno.prompt_emitido = True
            self.turno.novedad = False
        print("\n".join(lineas), flush=True)
        self.guardar()

    def primer_encargo(self) -> str:
        with open(self.archivo, encoding="utf-8", errors="replace") as f:
            for linea in f:
                if '"type":"user"' not in linea.replace(" ", ""):
                    continue
                try:
                    r = json.loads(linea)
                except ValueError:
                    continue
                if r.get("isMeta") or r.get("isSidechain"):
                    continue
                texto = texto_usuario((r.get("message") or {}).get("content"))
                if texto and texto != INTERRUPCION:
                    return texto
        return ""

    def sondear(self) -> None:
        registros = self.nuevos()
        for r in registros:
            self.procesar(r, vivo=True)
        ahora = time.monotonic()
        if registros:
            self.ultimo_registro = ahora
        t = self.turno
        if not t:
            return
        quieto = ahora - self.ultimo_registro
        if t.cerrado and quieto >= QUIETUD:
            self.emitir("interrumpido" if t.interrumpido else "terminado")
        elif t.esperando and t.novedad and quieto >= QUIETUD:
            self.emitir("esperando tu respuesta")
        elif t.novedad and ahora - t.ultima_emision >= AVANCE:
            self.emitir("en curso")


def listar(proyecto: str | None = None) -> None:
    carpeta = carpeta_proyecto(proyecto)
    archivos = sesiones(carpeta)[:8] if carpeta.exists() else []
    if not archivos:
        print(f"no hay otras sesiones en {carpeta}")
        return
    ahora = time.time()
    for f in archivos:
        titulo, ultimo = metadatos(f, completo=False)
        print(f"{f.stem[:8]}  hace {hace(ahora - f.stat().st_mtime):>9}  «{titulo or 'sin título'}»"
              f"  último: «{recortar(ultimo, 70)}»")


def listar_todas(n: int = 10) -> None:
    """Las sesiones más recientes de todos los proyectos, con su carpeta."""
    archivos = recientes(n)
    if not archivos:
        print("no hay sesiones de Claude Code")
        return
    ahora = time.time()
    casa = str(Path.home())
    for f in archivos:
        titulo, ultimo, cwd = metadatos_cwd(f, completo=False)
        print(f"{f.stem[:8]}  hace {hace(ahora - f.stat().st_mtime):>9}  {cwd.replace(casa, '~') or '?'}"
              f"\n          «{titulo or 'sin título'}»  último: «{recortar(ultimo, 70)}»")


def seguir(sesion: str | None = None, proyecto: str | None = None) -> None:
    """Sin sesión, sigue la más reciente del proyecto y salta a otra más nueva (p. ej. tras /clear)."""
    carpeta = carpeta_proyecto(proyecto)
    if sesion:
        archivo = resolver(carpeta, sesion)
    else:
        candidatas = sesiones(carpeta) if carpeta.exists() else []
        if not candidatas:
            raise SystemExit("[visor] no hay ninguna otra sesión de Claude Code en este proyecto")
        archivo = candidatas[0]
    lector = Lector(archivo)
    lector.arrancar()
    nacida = primer_instante(archivo)
    revision = time.monotonic()
    while True:
        try:
            lector.sondear()
        except FileNotFoundError:
            raise SystemExit("[visor] el transcript de la sesión ejecutora ha desaparecido")
        if not sesion and time.monotonic() - revision >= CAMBIO:
            revision = time.monotonic()
            nueva = next(iter(sesiones(carpeta)), None)
            if nueva and nueva != archivo and lector.turno is None:
                momento = primer_instante(nueva)
                if momento and nacida and momento > nacida and metadatos(nueva)[1]:
                    print(f"[visor] la sesión ejecutora cambió (¿/clear?): ahora sigo {nueva.stem[:8]}", flush=True)
                    archivo, nacida = nueva, momento
                    lector = Lector(archivo)
                    lector.arrancar()
        time.sleep(SONDEO)
