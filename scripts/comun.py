"""Piezas compartidas por el hook, el daemon y la CLI. Solo biblioteca estándar."""

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent  # código: el repo o la copia del plugin
# Estado fuera del código: todas las copias comparten venv, voces, config y lock.
RUNTIME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "narrador"
CONFIG = RUNTIME / "config.json"
VENV_PY = RUNTIME / "venv" / "bin" / "python"
DAEMON = RAIZ / "scripts" / "daemon.py"
OIDO = RAIZ / "scripts" / "oido.py"
LOG = RUNTIME / "narrador.log"
LOCK = RUNTIME / "narrador.lock"
VOCES = RUNTIME / "voces"

# Oído: el daemon que escucha el micrófono y lo que comparte con `narrador escuchar`.
OIDO_LOCK = RUNTIME / "oido.lock"
OIDO_PID = RUNTIME / "oido.pid"
OIDO_SALIDA = RUNTIME / "oido.jsonl"  # frases dirigidas a Ío y avisos (listo, error)
OIDO_VIVO = RUNTIME / "oido.vivo"  # latido de `narrador escuchar`; sin él, el oído se apaga
OIDO_CONSUMIDOR = RUNTIME / "oido-consumidor.lock"  # quién recibe las frases (Ío o el mentor)

# Ío: la sesión de asistente y sus trabajadores.
IO_LOCK = RUNTIME / "io.lock"
IO_JSON = RUNTIME / "io.json"  # session_id de la sesión de Ío en marcha
TRABAJADORES = RUNTIME / "trabajadores.json"
PROYECTOS_CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
RAICES = [Path.home() / "Documentos" / "thereisnospoon", Path.home() / "Documentos" / "greedisgood"]

MARCA = "\U0001F399"  # 🎙 (a veces seguido de U+FE0F)

CONFIG_DEFECTO = {
    "motor": "piper",
    "silencio": False,
    "cola_max": 4,
    "reproductor": "pw-play",
    "destino": None,  # salida de pw-play (node.name); None = la salida por defecto del sistema
    "piper": {"voz": "es_ES-davefx-medium", "velocidad": 1.1},
    "edge": {"voz": "es-MX-DaliaNeural", "velocidad": 0},
    "kokoro": {"voz": "ef_dora", "velocidad": 1.0, "tono": 1.0},  # voces en español: ef_dora, em_alex, em_santa
    "spd": {"idioma": "es", "velocidad": 10},
    "escucha": {
        "pausa": False,
        "nombre": "Ío",  # palabra que le despierta
        "ventana": 90,  # s sin actividad (ni Ío habla o trabaja, ni frases tuyas confirmadas por la huella) tras los que hay que volver a nombrarle
        "agrupar": 1.5,  # s de calma tras tu última frase para entregar a Ío todo junto como un párrafo (0 = frase a frase)
        "agrupar_max": 25,  # s máximos que se retiene un párrafo en formación
        "corte": 0.25,  # s de tu voz sobre la de Ío para cortarle (más = menos cortes falsos por eco)
        "silencio_fin": 0.8,  # s de silencio para dar una frase por terminada (más = te deja pensar entre frases)
        "aviso_descarte": True,  # un tono suave cuando descarta una frase por no oír su nombre
        "modelo": "small",  # modelo de faster-whisper
        "interrumpir": True,  # hablar mientras Ío habla le corta, solo si la huella confirma que eres tú
        "microfono": None,  # entrada de pw-record (node.name); None = la de por defecto
        "interna": False,  # escucha interna: además de tu voz, transcribe lo que suena en el equipo ([voz-equipo])
        "monitor": None,  # salida cuyo monitor oye la escucha interna (node.name); None = la de por defecto
    },
}


def ruta_socket(nombre: str = "narrador") -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return Path(base) / f"{nombre}-{os.getuid()}.sock"


def ruta_transcript(cwd: str | Path, sesion: str) -> Path:
    """Dónde guarda Claude Code el transcript de una sesión abierta en `cwd`."""
    return PROYECTOS_CLAUDE / re.sub(r"[^A-Za-z0-9]", "-", str(cwd)) / f"{sesion}.jsonl"


def binario_claude() -> str | None:
    """`claude` del PATH o, si no está, el de la extensión de VS Code más nueva."""
    import shutil

    en_path = shutil.which("claude")
    if en_path:
        return en_path

    def version(ruta: Path) -> tuple:
        m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", str(ruta))
        return tuple(int(x) for x in m.groups()) if m else (0,)

    candidatos = Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude")
    candidatos = sorted(candidatos, key=version)
    return str(candidatos[-1]) if candidatos else None


def leer_config() -> dict:
    cfg = json.loads(json.dumps(CONFIG_DEFECTO))
    try:
        datos = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    for clave, valor in datos.items():
        if isinstance(valor, dict) and isinstance(cfg.get(clave), dict):
            cfg[clave].update(valor)
        else:
            cfg[clave] = valor
    return cfg


def guardar_config(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG)


def enviar(orden: dict, esperar_respuesta: bool = False, timeout: float = 1.0):
    """Envía una orden JSON al daemon. Lanza OSError si no está en marcha."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(ruta_socket()))
        s.sendall((json.dumps(orden, ensure_ascii=False) + "\n").encode("utf-8"))
        if not esperar_respuesta:
            return None
        datos = b""
        while not datos.endswith(b"\n"):
            trozo = s.recv(4096)
            if not trozo:
                break
            datos += trozo
        return json.loads(datos.decode("utf-8")) if datos else None


def arrancar_daemon(script: Path = DAEMON) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    python = str(VENV_PY) if VENV_PY.exists() else sys.executable
    subprocess.Popen(
        [python, str(script)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def enviar_arrancando(orden: dict, espera: float = 2.0, esperar_respuesta: bool = False):
    """Como enviar(), pero arranca el daemon si no responde y reintenta hasta `espera` s."""
    try:
        return enviar(orden, esperar_respuesta)
    except OSError:
        pass
    arrancar_daemon()
    limite = time.monotonic() + espera
    while True:
        time.sleep(0.05)
        try:
            return enviar(orden, esperar_respuesta)
        except OSError:
            if time.monotonic() > limite:
                raise
