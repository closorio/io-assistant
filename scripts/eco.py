"""Cancelación de eco del oído: quita del micrófono lo que suena en el equipo (vídeos, reuniones).

Arranca un `pipewire -c` aparte con module-echo-cancel (WebRTC) en modo monitor: toma el micrófono
y, como referencia, el monitor de la salida por defecto, y ofrece una fuente virtual con el
micrófono limpio. Vive solo mientras el oído tiene el micrófono abierto y muere con él. No toca la
configuración de PipeWire ni la entrada por defecto (su fuente tiene prioridad 0).
"""

import ctypes
import json
import signal
import subprocess
import time

from comun import RUNTIME

FUENTE = "io_oido_eco"  # node.name de la fuente limpia: pw-record la usa como --target
ESPERA = 5  # s máximos para que aparezca la fuente


def conf(microfono: str | None = None, referencia: str | None = None, nombre: str = FUENTE) -> str:
    """Config de `pipewire -c`. Sin micrófono ni referencia, usa la entrada y la salida por defecto."""
    mic = f'target.object = "{microfono}"' if microfono else ""
    ref = f'target.object = "{referencia}"' if referencia else ""
    return f"""
context.properties = {{ log.level = 0 }}
context.spa-libs = {{
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}}
context.modules = [
    {{ name = libpipewire-module-rt flags = [ ifexists nofail ] }}
    {{ name = libpipewire-module-protocol-native }}
    {{ name = libpipewire-module-client-node }}
    {{ name = libpipewire-module-adapter }}
    {{ name = libpipewire-module-echo-cancel
        args = {{
            library.name = aec/libspa-aec-webrtc
            monitor.mode = true
            audio.channels = 1
            audio.position = [ MONO ]
            aec.args = {{ webrtc.gain_control = false }}
            capture.props = {{ node.name = "{nombre}_mic" {mic} }}
            sink.props = {{ node.name = "{nombre}_ref" {ref} }}
            source.props = {{
                node.name = "{nombre}"
                node.description = "Ío: micrófono sin eco"
                priority.session = 0
                priority.driver = 0
            }}
        }}
    }}
]
"""


def existe(nombre: str) -> bool:
    try:
        nodos = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=3).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    return any(((n.get("info") or {}).get("props") or {}).get("node.name") == nombre for n in nodos)


def _morir_con_el_padre() -> None:
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG: no deja el micrófono abierto


class Eco:
    def __init__(self, log):
        self.log = log
        self.proc: subprocess.Popen | None = None

    def arrancar(self, microfono: str | None = None, referencia: str | None = None, nombre: str = FUENTE) -> bool:
        """Arranca el filtro y espera a que su fuente exista. False si no se puede (y no deja nada vivo)."""
        self.parar()
        ruta = RUNTIME / "tmp" / f"{nombre}.conf"
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(conf(microfono, referencia, nombre), encoding="utf-8")
            self.proc = subprocess.Popen(["pipewire", "-c", str(ruta)], stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         preexec_fn=_morir_con_el_padre)
        except OSError as e:
            self.log(f"no pude arrancar la cancelación de eco: {e}")
            return False
        limite = time.monotonic() + ESPERA
        while time.monotonic() < limite and self.vivo():
            if existe(nombre):
                self.log("cancelación de eco activa")
                return True
            time.sleep(0.2)
        self.log(f"la cancelación de eco no arrancó (rc={self.proc.poll()})")
        self.parar()
        return False

    def vivo(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def parar(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc = None
