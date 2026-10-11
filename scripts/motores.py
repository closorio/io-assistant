"""Motores de voz. Cada uno convierte un texto en la orden que lo reproduce.

preparar(texto) -> (orden, archivo_temporal | None)
cancelar()      -> corta lo que esté sonando por fuera del proceso reproductor
"""

import os
import subprocess
import tempfile
import wave
from pathlib import Path

from comun import RUNTIME, VOCES


KOKORO = RUNTIME / "kokoro"


def _wav_temporal() -> Path:
    tmp = RUNTIME / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    fd, ruta = tempfile.mkstemp(suffix=".wav", dir=tmp)
    os.close(fd)
    return Path(ruta)


def _reproducir(cfg: dict, ruta: Path) -> list[str]:
    """La orden que reproduce un WAV, por la salida elegida si es pw-play."""
    orden = [cfg["reproductor"]]
    if cfg.get("destino") and orden[0] == "pw-play":
        orden += ["--target", cfg["destino"]]
    return orden + [str(ruta)]


class Motor:
    nombre = ""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def preparar(self, texto: str) -> tuple[list[str], Path | None]:
        raise NotImplementedError

    def cancelar(self) -> None:
        pass


class Piper(Motor):
    nombre = "piper"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        from piper import PiperVoice, SynthesisConfig

        voz = cfg["piper"]["voz"]
        modelo = VOCES / f"{voz}.onnx"
        if not modelo.exists():
            raise FileNotFoundError(f"voz de Piper no instalada: {voz} (ejecuta scripts/instalar.sh)")
        self.voz = PiperVoice.load(modelo)
        velocidad = float(cfg["piper"].get("velocidad") or 1.0)
        hablante = cfg["piper"].get("hablante")
        self.syn = SynthesisConfig(
            length_scale=1.0 / max(0.5, min(velocidad, 2.0)),
            speaker_id=int(hablante) if hablante is not None else None,
        )

    def preparar(self, texto):
        ruta = _wav_temporal()
        with wave.open(str(ruta), "wb") as wav:
            self.voz.synthesize_wav(texto, wav, syn_config=self.syn)
        return _reproducir(self.cfg, ruta), ruta


class Kokoro(Motor):
    """Voces neuronales de Kokoro, en local (en español: ef_dora, em_alex, em_santa)."""

    nombre = "kokoro"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        from kokoro_onnx import Kokoro as Modelo

        modelo, voces = KOKORO / "kokoro-v1.0.onnx", KOKORO / "voices-v1.0.bin"
        if not (modelo.exists() and voces.exists()):
            raise FileNotFoundError("faltan los archivos de Kokoro (ejecuta scripts/instalar.sh)")
        self.modelo = Modelo(str(modelo), str(voces))

    def preparar(self, texto):
        import numpy as np

        k = self.cfg["kokoro"]
        velocidad = max(0.5, min(float(k.get("velocidad") or 1.0), 2.0))
        muestras, tasa = self.modelo.create(texto, voice=k["voz"], speed=velocidad, lang="es")
        ruta = _wav_temporal()
        with wave.open(str(ruta), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(tasa)
            wav.writeframes((np.clip(muestras, -1, 1) * 32767).astype(np.int16).tobytes())
        tono = float(k.get("tono") or 1.0)
        if abs(tono - 1.0) > 1e-3:
            # tono: multiplicador de la altura (1.03 = un 3 % más agudo), sin cambiar la velocidad
            salida = ruta.with_suffix(".tono.wav")
            try:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ruta), "-af", f"rubberband=pitch={tono},volume=2.0,alimiter=limit=0.95", str(salida)], check=True)
                os.replace(salida, ruta)
            finally:
                salida.unlink(missing_ok=True)
        return _reproducir(self.cfg, ruta), ruta



class Edge(Motor):
    """Voces neuronales de Edge TTS (necesita internet). Si falla, el respaldo es Piper."""

    nombre = "edge"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        import edge_tts  # noqa: F401

    def preparar(self, texto):
        import asyncio

        import edge_tts

        e = self.cfg["edge"]
        ruta = _wav_temporal()
        mp3 = ruta.with_suffix(".mp3")
        try:
            com = edge_tts.Communicate(texto, e["voz"], rate=f"{int(e.get('velocidad', 0)):+d}%")
            asyncio.run(asyncio.wait_for(com.save(str(mp3)), timeout=15))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), str(ruta)], check=True)
        except BaseException:
            ruta.unlink(missing_ok=True)
            raise
        finally:
            mp3.unlink(missing_ok=True)
        return _reproducir(self.cfg, ruta), ruta


class Spd(Motor):
    nombre = "spd"

    def preparar(self, texto):
        spd = self.cfg["spd"]
        return ["spd-say", "-w", "-l", str(spd["idioma"]), "-r", str(spd["velocidad"]), texto], None

    def cancelar(self):
        subprocess.run(["spd-say", "-C"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


MOTORES = {m.nombre: m for m in (Kokoro, Edge, Piper, Spd)}
# Si el motor elegido falla, los respaldos son locales: Kokoro nunca cae en Edge, que va por internet.
RESPALDO = {
    "kokoro": ["kokoro", "piper", "spd"],
    "edge": ["edge", "piper", "spd"],
    "piper": ["piper", "spd"],
    "spd": ["spd"],
}


def cadena(principal: str) -> list[str]:
    """El motor elegido y, detrás, sus respaldos."""
    return RESPALDO.get(principal, RESPALDO["piper"])
