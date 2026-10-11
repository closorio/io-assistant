#!/usr/bin/env python3
"""Oído de Ío: escucha el micrófono, detecta cuándo hablas y lo transcribe en local.

Es un daemon aparte del de la voz porque carga Whisper (unos 600 MB) y tiene el micrófono
abierto. Solo deja pasar lo dirigido a Ío: frases que le nombran, o cualquier frase mientras
dura la conversación (unos segundos tras lo último que dijo). Lo que pasa lo añade a
oido.jsonl, y `narrador escuchar` se lo entrega al mentor a través de Monitor.

Necesita el venv (faster-whisper, onnxruntime, numpy). Se apaga solo cuando ya no hay
ningún `narrador escuchar` dando latido. Para pruebas, NARRADOR_OIDO_ENTRADA=archivo.wav
(16 kHz, mono, 16 bits) sustituye al micrófono.
"""

import fcntl
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import unicodedata
import wave
from collections import deque

import numpy as np

from comun import (
    CONFIG, LOG, OIDO_LOCK, OIDO_PID, OIDO_SALIDA, OIDO_VIVO, RUNTIME, enviar, leer_config,
)

TASA = 16000
BLOQUE = 512  # muestras por bloque de Silero (32 ms)
CONTEXTO = 64  # muestras del bloque anterior que Silero necesita delante
UMBRAL_ON, UMBRAL_OFF = 0.5, 0.35
ARRANQUE = 3  # bloques seguidos con voz para empezar una frase (~100 ms)
SILENCIO_FIN = 25  # bloques sin voz para darla por terminada (~800 ms)
PREVIO = 10  # bloques anteriores al arranque que se conservan (~320 ms)
MIN_VOZ = 12  # bloques con voz para que merezca la pena transcribir (~400 ms)
MAX_FRASE = 30 * TASA // BLOQUE
CORTE = 8  # bloques con voz mientras Ío habla para cortarle (~250 ms)
SIN_MENTOR = 120  # s sin latido de `narrador escuchar` antes de apagarse

PROMPT = "Conversación en español con Ío, un mentor de programación."
# Lo que Whisper suele inventarse con ruido o silencio en español.
ALUCINACIONES = re.compile(
    r"amara\.org|subt[ií]tul|gracias por ver|suscr[ií]bete|^\W*(m[uú]sica|aplausos|\.+)\W*$", re.I)

parar = threading.Event()


def log(mensaje: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} oído: {mensaje}\n")


def publicar(registro: dict) -> None:
    registro["t"] = time.time()
    with open(OIDO_SALIDA, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


class Vad:
    """Silero VAD v6 (el que trae faster-whisper) bloque a bloque, con su estado."""

    def __init__(self):
        import faster_whisper
        import onnxruntime as ort

        ruta = os.path.join(os.path.dirname(faster_whisper.__file__), "assets", "silero_vad_v6.onnx")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = opts.inter_op_num_threads = 1
        opts.log_severity_level = 4
        self.sesion = ort.InferenceSession(ruta, providers=["CPUExecutionProvider"], sess_options=opts)
        self.reiniciar()

    def reiniciar(self) -> None:
        self.h = np.zeros((1, 1, 128), np.float32)
        self.c = np.zeros((1, 1, 128), np.float32)
        self.contexto = np.zeros(CONTEXTO, np.float32)

    def __call__(self, bloque: np.ndarray) -> float:
        entrada = np.concatenate([self.contexto, bloque])[None, :]
        p, self.h, self.c = self.sesion.run(None, {"input": entrada, "h": self.h, "c": self.c})
        self.contexto = bloque[-CONTEXTO:]
        return float(np.asarray(p).ravel()[0])


class Oido:
    def __init__(self):
        from faster_whisper import WhisperModel

        self.cfg = leer_config()
        self.cfg_mtime = self._mtime_config()
        esc = self.cfg["escucha"]
        t0 = time.monotonic()
        self.modelo = WhisperModel(esc["modelo"], device="cpu", compute_type="int8",
                                   cpu_threads=max(1, min(14, (os.cpu_count() or 2) // 2)),
                                   download_root=str(RUNTIME / "whisper"))
        self.vad = Vad()
        log(f"modelo {esc['modelo']} cargado en {time.monotonic() - t0:.1f} s")
        nombre = normalizar(esc["nombre"])
        self.despierta = re.compile(rf"\b(?:h?{re.escape(nombre)})\b")
        self.hablando = False  # Ío está hablando ahora mismo
        self.ventana_hasta = 0.0  # monotonic hasta el que se le puede hablar sin nombrarle
        self.frases: queue.Queue = queue.Queue()
        self.proc = None

    # --- configuración y estado de la voz ---

    @staticmethod
    def _mtime_config() -> float:
        try:
            return CONFIG.stat().st_mtime
        except OSError:
            return 0.0

    @property
    def esc(self) -> dict:
        return self.cfg["escucha"]

    def vigia(self) -> None:
        """Sigue si Ío habla (para la ventana y para cortarle), la config y el latido del mentor."""
        while not parar.is_set():
            try:
                estado = enviar({"cmd": "estado"}, esperar_respuesta=True, timeout=0.3) or {}
                self.hablando = bool(estado.get("hablando"))
            except (OSError, ValueError):
                self.hablando = False
            if self.hablando:
                self.ventana_hasta = max(self.ventana_hasta, time.monotonic() + float(self.esc["ventana"]))
            mtime = self._mtime_config()
            if mtime != self.cfg_mtime:
                self.cfg_mtime, self.cfg = mtime, leer_config()
            if not os.environ.get("NARRADOR_OIDO_ENTRADA"):
                try:
                    sin_latido = time.time() - OIDO_VIVO.stat().st_mtime
                except OSError:
                    sin_latido = SIN_MENTOR + 1
                if sin_latido > SIN_MENTOR:
                    log("ningún mentor escucha; apago el oído")
                    parar.set()
            time.sleep(0.15)

    # --- captura ---

    def bloques(self):
        """Bloques de 512 muestras en float32. Con la escucha en pausa, el micrófono se cierra."""
        entrada = os.environ.get("NARRADOR_OIDO_ENTRADA")
        if entrada:
            yield from self._bloques_archivo(entrada)
            return
        while not parar.is_set():
            if self.esc.get("pausa"):
                time.sleep(0.3)
                continue
            orden = ["pw-record", "--rate", str(TASA), "--channels", "1", "--format", "s16"]
            if self.esc.get("microfono"):
                orden += ["--target", self.esc["microfono"]]
            self.proc = subprocess.Popen(orden + ["-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.vad.reiniciar()
            log("micrófono abierto")
            try:
                while not parar.is_set() and not self.esc.get("pausa"):
                    datos = self.proc.stdout.read(BLOQUE * 2)
                    if len(datos) < BLOQUE * 2:
                        raise OSError(f"pw-record terminó (rc={self.proc.poll()})")
                    yield np.frombuffer(datos, np.int16).astype(np.float32) / 32768
            finally:
                self.proc.terminate()
                self.proc.wait()
                log("micrófono cerrado")

    def _bloques_archivo(self, ruta: str):
        with wave.open(ruta, "rb") as w:
            datos = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        datos = np.concatenate([datos, np.zeros(2 * TASA, np.float32)])  # cola de silencio
        for i in range(0, len(datos) - BLOQUE + 1, BLOQUE):
            yield datos[i:i + BLOQUE]
            time.sleep(BLOQUE / TASA)  # a ritmo real, para que las ventanas cuenten igual

    def escuchar(self) -> None:
        previo: deque = deque(maxlen=PREVIO)
        frase: list = []
        en_frase = cortada = False
        seguidos = con_voz = silencio = 0
        for bloque in self.bloques():
            p = self.vad(bloque)
            if not en_frase:
                previo.append(bloque)
                seguidos = seguidos + 1 if p > UMBRAL_ON else 0
                if seguidos >= ARRANQUE:
                    en_frase, cortada = True, False
                    frase, con_voz, silencio = list(previo), seguidos, 0
                continue
            frase.append(bloque)
            if p > UMBRAL_OFF:
                con_voz += 1
                silencio = 0
            else:
                silencio += 1
            if self.hablando and not cortada and con_voz >= CORTE and self.esc.get("interrumpir"):
                cortada = True
                self.callar_a_io()
                log("me hablas mientras Ío habla: le corto")
            if silencio >= SILENCIO_FIN or len(frase) >= MAX_FRASE:
                if con_voz >= MIN_VOZ:
                    self.frases.put((np.concatenate(frase), time.monotonic()))
                en_frase, seguidos = False, 0
                previo.clear()
        self.frases.put(None)

    @staticmethod
    def callar_a_io() -> None:
        try:
            enviar({"cmd": "vaciar"})
        except OSError:
            pass

    # --- transcripción ---

    def transcriptor(self) -> None:
        while True:
            elemento = self.frases.get()
            if elemento is None:
                return
            audio, fin = elemento
            try:
                self.transcribir(audio, fin)
            except Exception as e:
                log(f"fallo al transcribir: {e}")

    def transcribir(self, audio: np.ndarray, fin: float) -> None:
        t0 = time.monotonic()
        segmentos, _ = self.modelo.transcribe(
            audio, language="es", beam_size=1, initial_prompt=PROMPT, hotwords=self.esc["nombre"],
            condition_on_previous_text=False, vad_filter=False, without_timestamps=True)
        texto = " ".join(s.text.strip() for s in segmentos if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0)
        texto = " ".join(texto.split())
        ms = (time.monotonic() - t0) * 1000
        if not re.search(r"\w", texto) or ALUCINACIONES.search(texto):
            log(f"ruido descartado ({len(audio) / TASA:.1f} s de audio, {ms:.0f} ms)")
            return
        if fin > self.ventana_hasta and not self.despierta.search(normalizar(texto)):
            log(f"frase sin «{self.esc['nombre']}» fuera de conversación, descartada ({len(texto.split())} palabras)")
            return
        self.ventana_hasta = time.monotonic() + float(self.esc["ventana"])
        self.callar_a_io()  # le estás hablando: lo que tuviera pendiente ya no viene a cuento
        publicar({"texto": texto})
        log(f"«{texto[:60]}» ({len(audio) / TASA:.1f} s de audio, transcrito en {ms:.0f} ms)")


def main() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cerrojo = open(OIDO_LOCK, "w")
    limite = time.monotonic() + 3  # margen por si alguien comprueba el cerrojo justo ahora
    while True:
        try:
            fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > limite:
                sys.exit(0)  # ya hay otro oído
            time.sleep(0.1)
    OIDO_PID.write_text(str(os.getpid()), encoding="utf-8")
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    if OIDO_SALIDA.exists() and OIDO_SALIDA.stat().st_size > 1_000_000:
        OIDO_SALIDA.write_text("", encoding="utf-8")
    try:
        oido = Oido()
    except Exception as e:
        log(f"no pude arrancar: {e}")
        publicar({"evento": "error", "detalle": f"no pude cargar el modelo de voz: {e}"})
        sys.exit(1)
    publicar({"evento": "listo", "nombre": oido.esc["nombre"]})
    log(f"escuchando (pid {os.getpid()})")
    threading.Thread(target=oido.vigia, daemon=True).start()
    hilo = threading.Thread(target=oido.transcriptor)
    hilo.start()
    try:
        oido.escuchar()
    except OSError as e:
        log(f"micrófono perdido: {e}")
        publicar({"evento": "error", "detalle": f"no puedo leer el micrófono: {e}"})
        oido.frases.put(None)
    hilo.join()
    OIDO_PID.unlink(missing_ok=True)
    log("oído parado")


if __name__ == "__main__":
    main()
