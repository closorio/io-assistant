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


def _wav_temporal() -> Path:
    tmp = RUNTIME / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    fd, ruta = tempfile.mkstemp(suffix=".wav", dir=tmp)
    os.close(fd)
    return Path(ruta)


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
        orden = [self.cfg["reproductor"]]
        if self.cfg.get("destino") and orden[0] == "pw-play":
            orden += ["--target", self.cfg["destino"]]
        return orden + [str(ruta)], ruta



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
        orden = [self.cfg["reproductor"]]
        if self.cfg.get("destino") and orden[0] == "pw-play":
            orden += ["--target", self.cfg["destino"]]
        return orden + [str(ruta)], ruta


class Spd(Motor):
    nombre = "spd"

    def preparar(self, texto):
        spd = self.cfg["spd"]
        return ["spd-say", "-w", "-l", str(spd["idioma"]), "-r", str(spd["velocidad"]), texto], None

    def cancelar(self):
        subprocess.run(["spd-say", "-C"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


MOTORES = {m.nombre: m for m in (Edge, Piper, Spd)}
RESPALDO = ["edge", "piper", "spd"]


def cadena(principal: str) -> list[str]:
    """El motor elegido y, detrás, los demás como respaldo (edge → piper → spd)."""
    if principal not in MOTORES:
        principal = "piper"
    return RESPALDO[RESPALDO.index(principal):]
