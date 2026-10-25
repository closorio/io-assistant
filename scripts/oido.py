#!/usr/bin/env python3
"""Oído de Ío: escucha el micrófono, detecta cuándo hablas y lo transcribe en local.

Es un daemon aparte del de la voz porque carga Whisper (unos 600 MB) y tiene el micrófono
abierto. Solo deja pasar lo dirigido a Ío: frases que le nombran, o cualquier frase mientras
dura la conversación (unos segundos tras lo último que dijo). Lo que pasa lo añade a
oido.jsonl, y `narrador escuchar` se lo entrega al mentor a través de Monitor.

Con la escucha interna activada (`escucha.interna`) transcribe además lo que suena en el equipo
(el monitor de la salida: reuniones, vídeos). Esas frases van en el campo «equipo», no en «texto», y nunca
cuentan como órdenes: ni despiertan a Ío, ni abren la conversación, ni le cortan.

Necesita el venv (faster-whisper, onnxruntime, numpy). Se apaga solo cuando ya no hay
ningún `narrador escuchar` dando latido. Para pruebas, NARRADOR_OIDO_ENTRADA=archivo.wav
(16 kHz, mono, 16 bits) sustituye al micrófono y NARRADOR_OIDO_EQUIPO=archivo.wav al monitor.
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
from pathlib import Path
from collections import deque

import numpy as np

from comun import (
    CONFIG, IO_JSON, LOG, guardar_config, OIDO_LOCK, OIDO_PID, OIDO_SALIDA, OIDO_VIVO, RUNTIME, enviar, leer_config,
    ruta_transcript,
)

TASA = 16000
BLOQUE = 512  # muestras por bloque de Silero (32 ms)
CONTEXTO = 64  # muestras del bloque anterior que Silero necesita delante
UMBRAL_ON, UMBRAL_OFF = 0.4, 0.35
ARRANQUE = 3  # bloques seguidos con voz para empezar una frase (~100 ms)
SILENCIO_FIN = 25  # bloques sin voz para darla por terminada (~800 ms); `escucha.silencio_fin` (s) lo cambia
PREVIO = 25  # bloques anteriores al arranque que se conservan (~800 ms)
MIN_VOZ = 6  # bloques con voz para que merezca la pena transcribir (~200 ms); `escucha.min_voz_ms` lo cambia.
# Con 12 (~400 ms) un «Ío» suelto seguido de pausa se tiraba sin avisar, y la frase siguiente llegaba sin el nombre
# y se descartaba también: «se me cortan las primeras palabras» (2026-10-20).
MAX_FRASE = 30 * TASA // BLOQUE
BUSCAR_CORTE = 3 * TASA // BLOQUE  # al llegar a MAX_FRASE, corta en el momento más callado de los últimos 3 s
CORTE = 8  # bloques con voz mientras Ío habla para cortarle (~250 ms)
SIN_MENTOR = 120  # s sin latido de `narrador escuchar` antes de apagarse
TRABAJANDO = 6  # s: si el transcript de Ío se escribió hace menos, está trabajando y la ventana sigue abierta
AVISO_CADA = 20  # s mínimos entre dos tonos de «no te he oído decir Ío»
MARGEN_IO = 0.6  # s tras hablar Ío en los que lo del monitor aún puede ser su voz
COLA_EQUIPO = 8  # frases del equipo esperando a Whisper; si hay más, se tira la más vieja
CARPETA_IO = Path.home() / "Documentos"  # donde arranca bin/io

PROMPT = "Conversación en español con Ío, un mentor de programación."
PROMPT_EQUIPO = "Reunión en español."
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


def precargar_cuda() -> bool:
    """Carga las librerías de CUDA instaladas con pip en el venv (nvidia-cublas-cu12, nvidia-cudnn-cu12): ctranslate2
    no las busca por sí solo. True si están todas; False si falta alguna (entonces se transcribe en CPU)."""
    import ctypes
    import glob
    raiz = os.path.dirname(os.path.dirname(np.__file__))
    patrones = ("nvidia/cublas/lib/libcublasLt.so.12", "nvidia/cublas/lib/libcublas.so.12",
                "nvidia/cudnn/lib/libcudnn.so.9")
    try:
        for patron in patrones:
            rutas = glob.glob(os.path.join(raiz, patron))
            if not rutas:
                return False
            ctypes.CDLL(rutas[0], mode=ctypes.RTLD_GLOBAL)
    except OSError:
        return False
    return True


def es_eco_del_prompt(texto: str, prompt: str) -> bool:
    """Con ruido, Whisper a veces devuelve su propia frase guía (o un trozo de tres palabras o más) como si la
    hubieras dicho tú: «Ío, un mentor de programación». Eso no es una frase tuya."""
    palabras = re.findall(r"\w+", normalizar(texto))
    if len(palabras) < 3:
        return False
    return " ".join(palabras) in " ".join(re.findall(r"\w+", normalizar(prompt)))


def voz_media(probs) -> float:
    """Probabilidad media de voz (Silero) en los bloques de una frase que la tienen."""
    con_voz = [q for q in probs if q > UMBRAL_OFF]
    return float(np.mean(con_voz)) if con_voz else 0.0


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


def sonar(cfg: dict, nombre: str, notas: tuple, duracion: float = 0.09) -> None:
    """Toca un tono corto de varias notas (se genera una vez y se reutiliza)."""
    try:
        tono = RUNTIME / "tmp" / f"{nombre}.wav"
        if not tono.exists():
            tono.parent.mkdir(parents=True, exist_ok=True)
            partes = []
            for frecuencia in notas:
                t = np.arange(int(TASA * duracion)) / TASA
                envolvente = np.minimum(1, np.minimum(t, t[::-1]) / 0.015)  # sin chasquidos
                partes.append(0.15 * np.sin(2 * np.pi * frecuencia * t) * envolvente)
            with wave.open(str(tono), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(TASA)
                w.writeframes((np.concatenate(partes) * 32767).astype(np.int16).tobytes())
        orden = [cfg.get("reproductor", "pw-play")]
        if cfg.get("destino") and orden[0] == "pw-play":
            orden += ["--target", cfg["destino"]]
        subprocess.Popen(orden + [str(tono)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"no pude tocar el aviso {nombre}: {e}")


class Oido:
    def __init__(self):
        from faster_whisper import WhisperModel

        self.cfg = leer_config()
        self.cfg_mtime = self._mtime_config()
        esc = self.cfg["escucha"]
        t0 = time.monotonic()
        # `escucha.dispositivo`: "cuda" para transcribir en la gráfica (int8_float16, unas 3 veces más rápido que la
        # CPU y permite un modelo grande); si CUDA no está o falla, se vuelve a la CPU y se avisa en el log.
        dispositivo = esc.get("dispositivo", "cpu")
        precision = esc.get("precision") or ("int8_float16" if dispositivo == "cuda" else "int8")
        hilos = max(1, min(14, (os.cpu_count() or 2) // 2))
        if dispositivo == "cuda" and not precargar_cuda():
            log("CUDA pedido pero faltan sus librerías en el venv (nvidia-cublas-cu12, nvidia-cudnn-cu12): uso la CPU")
            dispositivo, precision = "cpu", "int8"
        try:
            self.modelo = WhisperModel(esc["modelo"], device=dispositivo, compute_type=precision, cpu_threads=hilos,
                                       download_root=str(RUNTIME / "whisper"))
        except (RuntimeError, ValueError) as e:
            if dispositivo == "cpu":
                raise
            log(f"no puedo usar CUDA ({str(e)[:120]}): uso la CPU")
            dispositivo, precision = "cpu", "int8"
            self.modelo = WhisperModel(esc["modelo"], device="cpu", compute_type="int8", cpu_threads=hilos,
                                       download_root=str(RUNTIME / "whisper"))
        log(f"transcripción en {dispositivo} ({precision})")
        self.vad = Vad()
        self.vad_equipo = Vad()  # el monitor de la salida lleva su propio estado
        log(f"modelo {esc['modelo']} cargado en {time.monotonic() - t0:.1f} s")
        nombre = normalizar(esc["nombre"])
        self.despierta = re.compile(rf"\b(?:h?{re.escape(nombre)})\b")
        self.hablando = False  # Ío está hablando ahora mismo
        self.hablo_io = 0.0  # monotonic de la última vez que se le vio hablando
        self.ventana_hasta = 0.0  # monotonic hasta el que se le puede hablar sin nombrarle
        self.frases: queue.Queue = queue.Queue()
        self.frases_equipo: queue.Queue = queue.Queue()  # lo del monitor, con menos prioridad que lo tuyo
        self.transcript_io: Path | None = None  # el de la sesión de Ío, si está abierta
        self.revision_io = 0.0
        self.ultimo_aviso = 0.0
        self.ventana_abierta = False  # para avisar una sola vez cuando se cierra
        self.cerrojo_parrafo = threading.Lock()
        self.pendiente: list = []  # frases ya transcritas que esperan a juntarse en un párrafo
        self.pendiente_desde = 0.0
        self.pendiente_hasta = 0.0
        self.pendiente_huella = None  # el mayor parecido con tu huella entre esas frases (None: ninguna confirmada)
        self.huella = None  # se carga al primer uso (modelo ONNX local)
        self.cerrojo_huella = threading.Lock()  # la usan el transcriptor y el corte por voz, en hilos distintos
        self.en_voz = False  # estás hablando ahora mismo
        self.transcribiendo = False

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

    def io_trabajando(self) -> bool:
        """Ío está pensando o usando herramientas: su transcript se ha escrito hace un momento."""
        ahora = time.monotonic()
        if ahora - self.revision_io > 5:  # io.json cambia solo al abrir o cerrar Ío
            self.revision_io = ahora
            try:
                sesion = json.loads(IO_JSON.read_text(encoding="utf-8")).get("session_id")
            except (OSError, ValueError):
                sesion = None
            self.transcript_io = ruta_transcript(CARPETA_IO, sesion) if sesion else None
        if not self.transcript_io:
            return False
        try:
            return time.time() - self.transcript_io.stat().st_mtime < TRABAJANDO
        except OSError:
            return False

    def conversacion_activa(self) -> bool:
        """Hay conversación en marcha: Ío habla o trabaja, o hay un párrafo tuyo por entregar (frases que la huella
        ya confirmó como tuyas). La voz cruda del micrófono no cuenta: un vídeo o alguien al lado no mantienen la
        ventana; solo lo que la huella confirma, que ya la renueva al aceptarse cada frase."""
        if self.hablando or self.io_trabajando():
            return True
        return self.ventana_abierta and bool(self.pendiente)

    def mantener_ventana(self) -> None:
        """La cuenta atrás de `escucha.ventana` solo corre con la conversación parada: mientras Ío hace algo o
        hay frases tuyas confirmadas en camino, el plazo se vuelve a poner entero. Cuando se agota, avisa una vez."""
        ahora = time.monotonic()
        if self.conversacion_activa():
            self.ventana_hasta = max(self.ventana_hasta, ahora + float(self.esc["ventana"]))
            self.ventana_abierta = True
        elif self.ventana_abierta and ahora > self.ventana_hasta:
            self.ventana_abierta = False
            self.avisar_ventana_cerrada()

    def avisar_descarte(self) -> None:
        """Un tono suave y descendente: «te he oído, pero no me has nombrado»."""
        if not self.esc.get("aviso_descarte", True) or time.monotonic() - self.ultimo_aviso < AVISO_CADA:
            return
        self.ultimo_aviso = time.monotonic()
        sonar(self.cfg, "descarte", (660, 440))

    def avisar_ventana_cerrada(self) -> None:
        """Tres notas descendentes y suaves: «la ventana de conversación se ha cerrado»."""
        if self.esc.get("avisos_sonoros", True):
            sonar(self.cfg, "ventana_cerrada", (523, 392, 262))

    def soltar_parrafo(self, forzar: bool = False) -> None:
        """Entrega a Ío las frases juntas, como un párrafo, cuando llevas `agrupar` s sin decir nada más."""
        if not self.pendiente:
            return
        ahora = time.monotonic()
        callado = not self.en_voz and self.frases.empty() and not self.transcribiendo
        tope = ahora - self.pendiente_desde > float(self.esc.get("agrupar_max", 25))
        if not (forzar or tope or (callado and ahora >= self.pendiente_hasta)):
            return
        with self.cerrojo_parrafo:
            texto = " ".join(self.pendiente)
            n = len(self.pendiente)
            self.pendiente = []
            huella, self.pendiente_huella = self.pendiente_huella, None
        if not texto:
            return
        if huella is not None:  # solo tu voz confirmada calla a Ío
            self.callar_a_io(f"párrafo tuyo entregado (huella {huella:.2f})")
        publicar({"texto": texto})
        if self.esc.get("aviso_recibido", True):
            sonar(self.cfg, "recibido", (440, 660), 0.07)  # «te he entendido, ya lo tengo Ío»
        log(f"párrafo de {n} frase(s) entregado: «{texto[:60]}»")

    def vigia(self) -> None:
        """Sigue si Ío habla (para la ventana y para cortarle), la config y el latido del mentor."""
        while not parar.is_set():
            try:
                estado = enviar({"cmd": "estado"}, esperar_respuesta=True, timeout=0.3) or {}
                self.hablando = bool(estado.get("hablando"))
            except (OSError, ValueError):
                self.hablando = False
            if self.hablando:
                self.hablo_io = time.monotonic()
            self.mantener_ventana()
            self.soltar_parrafo()
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

    def capturar(self, que: str, orden, cerrado, vad: Vad):
        """Bloques de 512 muestras en float32 de pw-record. Mientras `cerrado()`, la captura se cierra."""
        while not parar.is_set():
            if cerrado():
                time.sleep(0.3)
                continue
            proc = subprocess.Popen(orden() + ["-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            vad.reiniciar()
            log(f"{que} abierto")
            try:
                while not parar.is_set() and not cerrado():
                    datos = proc.stdout.read(BLOQUE * 2)
                    if len(datos) < BLOQUE * 2:
                        raise OSError(f"pw-record terminó (rc={proc.poll()})")
                    yield np.frombuffer(datos, np.int16).astype(np.float32) / 32768
            finally:
                proc.terminate()
                proc.wait()
                log(f"{que} cerrado")

    def _orden_mic(self) -> list:
        orden = ["pw-record", "--rate", str(TASA), "--channels", "1", "--format", "s16"]
        if self.esc.get("microfono"):
            orden += ["--target", self.esc["microfono"]]
        return orden

    def _orden_monitor(self) -> list:
        """pw-record del monitor de la salida (por defecto, la del sistema): lo que suena, sin el micrófono."""
        orden = ["pw-record", "--rate", str(TASA), "--channels", "1", "--format", "s16",
                 "-P", "{ stream.capture.sink = true node.name = io_escucha_interna }"]
        if self.esc.get("monitor"):
            orden += ["--target", self.esc["monitor"]]
        return orden

    def _mic_cerrado(self) -> bool:
        """En pausa el micrófono se cierra."""
        return bool(self.esc.get("pausa"))

    def _monitor_cerrado(self) -> bool:
        """El monitor solo se escucha con la escucha interna activada y sin pausa."""
        return not self.esc.get("interna") or bool(self.esc.get("pausa"))

    def _bloques_archivo(self, ruta: str):
        with wave.open(ruta, "rb") as w:
            datos = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        datos = np.concatenate([datos, np.zeros(2 * TASA, np.float32)])  # cola de silencio
        for i in range(0, len(datos) - BLOQUE + 1, BLOQUE):
            yield datos[i:i + BLOQUE]
            time.sleep(BLOQUE / TASA)  # a ritmo real, para que las ventanas cuenten igual

    def escuchar(self) -> None:
        """El micrófono: tus frases."""
        entrada = os.environ.get("NARRADOR_OIDO_ENTRADA")
        bloques = self._bloques_archivo(entrada) if entrada else self.capturar(
            "micrófono", self._orden_mic, self._mic_cerrado, self.vad)
        self.trocear(bloques, self.vad, mic=True)

    def escuchar_equipo(self) -> None:
        """Escucha interna: lo que suena en el equipo, solo mientras está activada. Si el monitor falla,
        lo reintenta sin tumbar el micrófono."""
        entrada = os.environ.get("NARRADOR_OIDO_EQUIPO")
        if entrada:
            self.trocear(self._bloques_archivo(entrada), self.vad_equipo, mic=False)
            return
        while not parar.is_set():
            try:
                self.trocear(self.capturar("monitor del equipo", self._orden_monitor, self._monitor_cerrado,
                                           self.vad_equipo), self.vad_equipo, mic=False)
            except OSError as e:
                log(f"no puedo oír lo que suena en el equipo: {e}")
                parar.wait(5)

    def trocear(self, bloques, vad: Vad, mic: bool) -> None:
        """Corta el audio en frases con el VAD y las encola para Whisper. Las del equipo (mic=False) no cortan
        a Ío ni cuentan como que estás hablando, y se tiran si Ío habló mientras sonaban: serían su voz."""
        previo: deque = deque(maxlen=PREVIO)  # (bloque, probabilidad de voz)
        frase: list = []
        probs: list = []  # la probabilidad de voz de cada bloque de la frase
        en_frase = cortada = con_io = False
        seguidos = con_voz = silencio = 0
        for bloque in bloques:
            p = vad(bloque)
            io_suena = self.hablando or time.monotonic() - self.hablo_io < MARGEN_IO
            if not en_frase:
                previo.append((bloque, p))
                seguidos = seguidos + 1 if p > UMBRAL_ON else 0
                if seguidos >= ARRANQUE:
                    en_frase, cortada, con_io = True, False, io_suena
                    if mic:
                        self.en_voz = True
                    frase, probs = [b for b, _ in previo], [q for _, q in previo]
                    con_voz, silencio = seguidos, 0
                continue
            frase.append(bloque)
            probs.append(p)
            con_io = con_io or io_suena
            if p > UMBRAL_OFF:
                con_voz += 1
                silencio = 0
            else:
                silencio += 1
            corte_bloques = max(4, int(float(self.esc.get("corte", 0.25)) * TASA / BLOQUE))
            if mic and self.hablando and not cortada and con_voz >= corte_bloques and self.esc.get("interrumpir"):
                cortada = True  # una sola comprobación por frase; si no eres tú, la frase sigue su camino
                threading.Thread(target=self.cortar_si_eres_tu, args=(np.concatenate(frase), voz_media(probs)),
                                 daemon=True).start()
            fin_bloques = max(8, int(float(self.esc.get("silencio_fin", 0.8)) * TASA / BLOQUE))
            if silencio >= fin_bloques:
                self._soltar_frase(frase, con_voz, con_io, mic, probs)
                en_frase, seguidos = False, 0
                if mic:
                    self.en_voz = False
                previo.clear()
            elif len(frase) >= MAX_FRASE:
                # Sin pausa larga en 30 s: corta donde menos voz hay, no a mitad de palabra (Whisper se pierde
                # con un trozo que empieza de golpe), y lo que sigue empieza ya la frase siguiente.
                k = len(frase) - BUSCAR_CORTE + int(np.argmin(probs[-BUSCAR_CORTE:]))
                self._soltar_frase(frase[:k + 1], sum(q > UMBRAL_OFF for q in probs[:k + 1]), con_io, mic,
                                   probs[:k + 1])
                frase, probs = frase[k:], probs[k:]
                con_voz = sum(q > UMBRAL_OFF for q in probs)
                silencio = min(silencio, len(frase))
                con_io = io_suena

    def _soltar_frase(self, frase: list, con_voz: int, con_io: bool, mic: bool, probs: list) -> None:
        minimo = int(float(self.esc.get("min_voz_ms", MIN_VOZ * BLOQUE * 1000 / TASA)) * TASA / 1000 / BLOQUE)
        if con_voz < max(1, minimo):
            if mic and con_voz >= 3:
                log(f"trozo con solo {con_voz * BLOQUE * 1000 // TASA} ms de voz, no se transcribe (mínimo {minimo * BLOQUE * 1000 // TASA} ms)")
            return
        if mic:
            ahora = time.monotonic()
            self.frases.put((np.concatenate(frase), ahora, voz_media(probs), ahora - len(frase) * BLOQUE / TASA))
        elif con_io:
            log("lo que sonaba en el equipo coincidía con la voz de Ío: descartado")
        else:
            self.encolar_equipo(np.concatenate(frase))

    def encolar_equipo(self, audio: np.ndarray) -> None:
        if self.frases_equipo.qsize() >= COLA_EQUIPO:
            try:
                self.frases_equipo.get_nowait()
                log("voy atrasado con lo que suena en el equipo: me salto una frase")
            except queue.Empty:
                pass
        self.frases_equipo.put(audio)

    @staticmethod
    def callar_a_io(motivo: str) -> None:
        try:
            enviar({"cmd": "vaciar", "origen": f"oído: {motivo}"})
        except OSError:
            pass

    def cortar_si_eres_tu(self, audio: np.ndarray, voz: float) -> None:
        """Corte por voz (`escucha.interrumpir`): hablas mientras Ío habla. Solo le corta si la huella confirma que
        eres tú; sin ella, el eco de su propia voz, un vídeo o el ruido le cortaban a media frase."""
        datos = f"voz {voz:.2f}, {len(audio) / TASA:.1f} s"
        sim = self.parecido(audio)
        umbral = self.umbral_huella()
        if sim is None:
            log(f"oigo voz mientras Ío habla ({datos}), pero sin huella no sé si eres tú: no le corto")
        elif sim < umbral:
            log(f"oigo voz mientras Ío habla ({datos}), huella {sim:.2f} < {umbral}: no eres tú, no le corto")
        else:
            self.callar_a_io(f"corte por voz ({datos}, huella {sim:.2f})")
            log(f"me hablas mientras Ío habla: le corto ({datos}, huella {sim:.2f})")

    # --- transcripción ---

    def transcriptor(self) -> None:
        """Pasa las frases por Whisper: primero las tuyas; las del equipo, cuando no hay ninguna tuya esperando.
        Al recibir None termina lo que quede del equipo y sale."""
        while True:
            try:
                elemento = self.frases.get(timeout=0.2)
            except queue.Empty:
                try:
                    self._transcribir(self.transcribir_equipo, self.frases_equipo.get_nowait())
                except queue.Empty:
                    pass
                continue
            if elemento is None:
                break
            self.transcribiendo = True
            try:
                self._transcribir(self.transcribir, *elemento)
            finally:
                self.transcribiendo = False
        while not self.frases_equipo.empty():
            self._transcribir(self.transcribir_equipo, self.frases_equipo.get_nowait())

    @staticmethod
    def _transcribir(funcion, *args) -> None:
        try:
            funcion(*args)
        except Exception as e:
            log(f"fallo al transcribir: {e}")

    def vocabulario(self) -> str:
        """Palabras que Whisper debe favorecer: tu nombre para Ío y los nombres propios de `escucha.vocabulario`
        (tenants, herramientas, clientes), que sin ayuda transcribe como «Marlobet» o «Brutalnet»."""
        palabras = [self.esc["nombre"]] + [str(p) for p in self.esc.get("vocabulario", []) if p]
        return ", ".join(dict.fromkeys(palabras))

    def _whisper(self, audio: np.ndarray, prompt: str, hotwords: str | None) -> tuple[str, float]:
        """(texto, ms que ha tardado). Texto vacío si era ruido o una alucinación típica de Whisper."""
        t0 = time.monotonic()
        segmentos, _ = self.modelo.transcribe(
            audio, language="es", beam_size=int(self.esc.get("beam", 5)), initial_prompt=prompt, hotwords=hotwords,
            condition_on_previous_text=False, vad_filter=False, without_timestamps=True)
        texto = " ".join(s.text.strip() for s in segmentos if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0)
        texto = " ".join(texto.split())
        ms = (time.monotonic() - t0) * 1000
        if not re.search(r"\w", texto) or ALUCINACIONES.search(texto) or es_eco_del_prompt(texto, prompt):
            texto = ""
        return texto, ms

    def comando_escucha(self, norm: str) -> bool:
        """«Escucha interna activada/desactivada» (sin decir Ío): activada, además de tu voz se transcribe lo que
        suena en el equipo (reuniones, vídeos), marcado aparte; desactivada, solo tu voz. True si era una orden."""
        activar = re.search(r"\bescucha interna (?:activa|activada|activar)\b|\bactiva (?:la |mi )?escucha interna\b", norm)
        apagar = re.search(r"\bescucha interna (?:desactivada|desactivar|inactiva|apagada)\b|\bdesactiva (?:la |mi )?escucha interna\b", norm)
        if bool(activar) == bool(apagar):
            return False
        nueva = bool(activar)
        if bool(self.esc.get("interna")) != nueva:
            cfg = leer_config()
            cfg["escucha"]["interna"] = nueva
            guardar_config(cfg)
            self.cfg, self.cfg_mtime = cfg, self._mtime_config()
        sonar(self.cfg, "escucha_on" if nueva else "escucha_off", (440, 660, 880) if nueva else (660, 440, 330), 0.08)
        log("escucha interna " + ("activada" if nueva else "desactivada") + " por voz")
        return True

    def parecido(self, audio: np.ndarray) -> float | None:
        """Parecido del audio con tu huella (1 = igual), o None si no hay huella con la que compararlo."""
        if not self.esc.get("huella"):
            return None
        try:
            with self.cerrojo_huella:
                if self.huella is None:
                    from huella import Huella
                    self.huella = Huella()
                if self.huella.referencia is None:
                    return None
                return self.huella.similitud(audio)
        except Exception as e:
            log(f"huella no disponible, dejo pasar sin callar a Ío: {e}")
            return None

    def umbral_huella(self) -> float:
        return float(self.esc.get("huella_umbral", 0.5))

    def transcribir_equipo(self, audio: np.ndarray) -> None:
        """Lo que suena en el equipo va marcado aparte y nunca es una orden: no mira el nombre de Ío ni los mandos
        de voz, no abre la conversación, no le corta ni se junta con tus párrafos. Al log solo va su tamaño."""
        texto, ms = self._whisper(audio, PROMPT_EQUIPO, None)
        if not texto:
            log(f"equipo: ruido descartado ({len(audio) / TASA:.1f} s de audio, {ms:.0f} ms)")
            return
        publicar({"equipo": texto})  # sin «texto»: un `narrador escuchar` viejo nunca lo mostraría como tuyo
        log(f"equipo: {len(texto.split())} palabras ({len(audio) / TASA:.1f} s de audio, transcrito en {ms:.0f} ms)")

    def transcribir(self, audio: np.ndarray, fin: float, voz: float = 0.0, inicio: float | None = None) -> None:
        """Con huella, del micrófono solo pasa lo que suena a tu voz. También con la escucha interna: lo que suena
        en el equipo llega por el monitor, marcado aparte, y no debe colarse por el micrófono como orden tuya.
        Solo una frase que la huella confirma como tuya calla a Ío."""
        texto, ms = self._whisper(audio, PROMPT, self.vocabulario())
        if not texto:
            log(f"ruido descartado ({len(audio) / TASA:.1f} s de audio, voz {voz:.2f}, {ms:.0f} ms)")
            return
        sim = self.parecido(audio)
        if sim is not None:
            log(f"huella: parecido {sim:.2f} (umbral {self.umbral_huella()})")
            if sim < self.umbral_huella():
                log(f"voz que no es la tuya, descartada (voz {voz:.2f})")
                return
        if self.esc.get("eco_exige_nombre", False) and not self.despierta.search(normalizar(texto)):
            empezo = fin - len(audio) / TASA if inicio is None else inicio
            if empezo <= self.hablo_io + float(self.esc.get("eco_margen", 1.0)):
                log(f"frase sin «{self.esc['nombre']}» mientras Ío hablaba: la tomo por eco, descartada")
                return
        if self.comando_escucha(normalizar(texto)):
            return
        empieza = fin if inicio is None else inicio  # vale con haber empezado a hablar dentro de la ventana
        if empieza > self.ventana_hasta and not self.despierta.search(normalizar(texto)):
            palabras = len(texto.split())
            log(f"frase sin «{self.esc['nombre']}» fuera de conversación, descartada ({palabras} palabras): «{texto[:60]}»")
            if palabras >= 3:  # parece una frase de verdad, no un ruido o una palabra suelta
                self.avisar_descarte()
            return
        self.ventana_hasta = time.monotonic() + float(self.esc["ventana"])
        self.ventana_abierta = True
        if sim is not None:  # le estás hablando: lo que tuviera pendiente ya no viene a cuento
            self.callar_a_io(f"frase tuya aceptada (voz {voz:.2f}, huella {sim:.2f})")
        elif self.hablando:
            log("frase aceptada sin huella que confirme tu voz: no callo a Ío")
        agrupar = float(self.esc.get("agrupar", 0))
        if agrupar > 0:  # junta las frases seguidas en un párrafo y lo entrega cuando te callas
            with self.cerrojo_parrafo:
                if not self.pendiente:
                    self.pendiente_desde = time.monotonic()
                self.pendiente.append(texto)
                self.pendiente_hasta = time.monotonic() + agrupar
                if sim is not None:
                    self.pendiente_huella = max(sim, self.pendiente_huella or 0.0)
        else:
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
    # pid y de qué copia del código viene: `narrador escuchar` reinicia el oído si es de otra versión
    OIDO_PID.write_text(f"{os.getpid()}\n{Path(__file__).resolve()}", encoding="utf-8")
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
    equipo = threading.Thread(target=oido.escuchar_equipo)  # no daemon: debe cerrar su pw-record al salir
    equipo.start()
    hilo = threading.Thread(target=oido.transcriptor)
    hilo.start()
    try:
        oido.escuchar()
    except OSError as e:
        log(f"micrófono perdido: {e}")
        if oido.esc.get("avisos_sonoros", True):
            sonar(oido.cfg, "no_oigo", (330, 330), 0.18)
        publicar({"evento": "error", "detalle": f"no puedo leer el micrófono: {e}"})
    parar.set()
    equipo.join()
    oido.frases.put(None)
    hilo.join()
    oido.soltar_parrafo(forzar=True)  # lo último que dijiste no se pierde al apagar
    OIDO_PID.unlink(missing_ok=True)
    log("oído parado")


if __name__ == "__main__":
    main()
