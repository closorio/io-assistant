"""Huella de voz: distingue tu voz de un vídeo o de otra persona. Todo local.

La huella es un vector de números (no el audio) que sale de un modelo ONNX pequeño y se guarda en
`~/.local/share/narrador/huella.npy` con permisos solo para ti. El modelo se descarga una vez; después no hace falta red.

  narrador huella grabar [SEGUNDOS]   (graba tu voz y crea la huella; pausa el oído mientras)
  narrador huella estado | probar | borrar
"""

import fcntl
import os
import subprocess
import sys
import time

import numpy as np

from comun import RUNTIME, guardar_config, leer_config

TASA = 16000
MODELO = RUNTIME / "modelos" / "wespeaker_resnet34.onnx"
HUELLA = RUNTIME / "huella.npy"
URL_MODELO = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
              "wespeaker_en_voxceleb_resnet34.onnx")
VENTANA = 3 * TASA  # trozos de 3 s para calcular y validar la huella
MIN_RMS = 0.01  # por debajo es silencio


class Huella:
    def __init__(self):
        import sherpa_onnx
        if not MODELO.exists():
            raise FileNotFoundError(f"falta el modelo de voz {MODELO}; descárgalo de {URL_MODELO}")
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELO), num_threads=1, provider="cpu")
        self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.referencia = np.load(HUELLA) if HUELLA.exists() else None

    def vector(self, audio: np.ndarray) -> np.ndarray:
        flujo = self.extractor.create_stream()
        flujo.accept_waveform(sample_rate=TASA, waveform=audio.astype(np.float32))
        flujo.input_finished()
        v = np.array(self.extractor.compute(flujo), dtype=np.float32)
        return v / (np.linalg.norm(v) + 1e-9)

    def similitud(self, audio: np.ndarray) -> float:
        """Coseno entre el audio y tu huella (1 = igual). Sin huella devuelve 1."""
        if self.referencia is None:
            return 1.0
        return float(np.dot(self.vector(audio), self.referencia))


def _grabar(segundos: int) -> np.ndarray:
    orden = ["pw-record", "--rate", str(TASA), "--channels", "1", "--format", "s16", "-"]
    cfg = leer_config()["escucha"]
    if cfg.get("microfono"):
        orden[1:1] = ["--target", cfg["microfono"]]
    proc = subprocess.Popen(orden, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    datos = bytearray()
    fin = time.monotonic() + segundos
    try:
        while time.monotonic() < fin:
            datos += proc.stdout.read(TASA * 2 // 5)
    finally:
        proc.terminate()
        proc.wait()
    return np.frombuffer(bytes(datos), np.int16).astype(np.float32) / 32768


def _trozos(audio: np.ndarray) -> list:
    return [audio[i:i + VENTANA] for i in range(0, len(audio) - VENTANA + 1, VENTANA)
            if np.sqrt(np.mean(audio[i:i + VENTANA] ** 2)) > MIN_RMS]


def grabar(segundos: int = 75) -> None:
    h = Huella()
    # Dos grabaciones a la vez se pisarían la pausa del oído: la segunda leería «pausa: true» como estado previo
    # y, al terminar, dejaría el micrófono cerrado para siempre (pasó el 2026-10-20). Un cerrojo lo impide.
    cerrojo = open(RUNTIME / "huella.lock", "w")
    try:
        fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("Ya hay una grabación de huella en marcha; espera a que termine o ciérrala.")
    cfg = leer_config()
    pausa_previa = cfg["escucha"].get("pausa", False)
    cfg["escucha"]["pausa"] = True  # el oído no debe transcribir esto
    guardar_config(cfg)
    try:
        print(f"Habla con naturalidad durante {segundos} s (lee algo en voz alta, sin vídeos sonando). Empieza ya.")
        audio = _grabar(segundos)
    finally:
        cfg = leer_config()
        cfg["escucha"]["pausa"] = pausa_previa
        guardar_config(cfg)
        fcntl.flock(cerrojo, fcntl.LOCK_UN)
        cerrojo.close()
    trozos = _trozos(audio)
    if len(trozos) < 8:
        sys.exit(f"Solo hay {len(trozos)} trozos con voz; habla más alto o más tiempo y repite.")
    vectores = np.stack([h.vector(t) for t in trozos])
    media = vectores.mean(axis=0)
    media /= np.linalg.norm(media)
    sims = vectores @ media
    HUELLA.parent.mkdir(parents=True, exist_ok=True)
    np.save(HUELLA, media)
    os.chmod(HUELLA, 0o600)
    print(f"Huella guardada ({len(trozos)} trozos). Parecido de tus trozos con ella: "
          f"mín {sims.min():.2f}, media {sims.mean():.2f}.")
    cfg = leer_config()
    cfg["escucha"]["huella"] = True
    cfg["escucha"].setdefault("huella_umbral", round(max(0.3, float(np.percentile(sims, 5)) - 0.1), 2))
    guardar_config(cfg)
    print(f"Umbral inicial: {cfg['escucha']['huella_umbral']} (ajustable en escucha.huella_umbral).")


def probar(segundos: int = 8) -> None:
    h = Huella()
    if h.referencia is None:
        sys.exit("No hay huella; usa `narrador huella grabar`.")
    print(f"Di algo o pon un vídeo durante {segundos} s…")
    trozos = _trozos(_grabar(segundos))
    if not trozos:
        sys.exit("No he oído voz.")
    print("Parecido por trozo de 3 s: " + ", ".join(f"{h.similitud(t):.2f}" for t in trozos))


def estado() -> None:
    cfg = leer_config()["escucha"]
    print(f"huella: {'creada' if HUELLA.exists() else 'sin crear'} · filtro {'activo' if cfg.get('huella') else 'apagado'}"
          f" · umbral {cfg.get('huella_umbral', 'sin fijar')} · escucha interna {'activada' if cfg.get('interna') else 'desactivada'}")


def borrar() -> None:
    HUELLA.unlink(missing_ok=True)
    cfg = leer_config()
    cfg["escucha"]["huella"] = False
    guardar_config(cfg)
    print("huella borrada")


def main(args: list[str]) -> None:
    accion = args[0] if args else "estado"
    if accion == "grabar":
        grabar(int(args[1]) if len(args) > 1 else 75)
    elif accion == "probar":
        probar()
    elif accion == "estado":
        estado()
    elif accion == "borrar":
        borrar()
    else:
        sys.exit("uso: narrador huella [grabar [SEGUNDOS]|probar|estado|borrar]")
