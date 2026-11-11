"""Pruebas de los tonos de la cabina. Ejecuta: .runtime/venv-tests/bin/python -m pytest -q tests/test_tonos.py"""

import subprocess
import sys
import wave
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import tonos  # noqa: E402


@pytest.mark.parametrize("nombre", tonos.NOMBRES)
def test_los_tonos_existen_y_son_cortos_y_pequenos(nombre):
    archivo = tonos.CARPETA / f"{nombre}.wav"
    with wave.open(str(archivo)) as w:
        assert w.getnframes() / w.getframerate() < 1.0
    assert archivo.stat().st_size < 64_000


def cfg(**extra):
    base = {"silencio": False, "reproductor": "pw-play", "destino": None,
            "escucha": {"pausa": False}, "tonos": {"activos": True, "volumen": 0.4}}
    for k, v in extra.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) else v
    return base


class Reproductor:
    def __init__(self):
        self.ordenes = []

    def __call__(self, orden, **_):
        self.ordenes.append(orden)
        return subprocess.CompletedProcess(orden, 0)


def test_suena_con_volumen_y_salida_de_la_voz(monkeypatch):
    monkeypatch.setattr(tonos, "leer_config", lambda: cfg(destino="cascos", tonos={"volumen": 0.3}))
    rep = Reproductor()
    assert tonos.tono("terminado", ocupada=lambda: False, ejecutar=rep) == (True, "sonó")
    assert rep.ordenes[0][:3] == ["pw-play", "--volume=0.30", "--target=cascos"]
    assert rep.ordenes[0][-1].endswith("terminado.wav")


@pytest.mark.parametrize("extra, motivo", [
    ({"silencio": True}, "silencio"),
    ({"escucha": {"pausa": True}}, "pausa"),
    ({"tonos": {"activos": False}}, "desactivados"),
])
def test_calla_en_silencio_pausa_o_desactivado(monkeypatch, extra, motivo):
    monkeypatch.setattr(tonos, "leer_config", lambda: cfg(**extra))
    rep = Reproductor()
    sono, porque = tonos.tono("error", ocupada=lambda: False, ejecutar=rep)
    assert not sono and motivo in porque and rep.ordenes == []


def test_espera_a_que_io_acabe_de_hablar(monkeypatch):
    monkeypatch.setattr(tonos, "leer_config", cfg)
    monkeypatch.setattr(tonos, "SONDEO", 0.01)
    respuestas = iter([True, True, False])
    rep = Reproductor()
    assert tonos.tono("puerta", ocupada=lambda: next(respuestas), ejecutar=rep)[0]
    assert len(rep.ordenes) == 1


def test_no_suena_encima_de_una_locucion_larga(monkeypatch):
    monkeypatch.setattr(tonos, "leer_config", cfg)
    monkeypatch.setattr(tonos, "SONDEO", 0.01)
    rep = Reproductor()
    assert tonos.tono("puerta", espera_max=0.05, ocupada=lambda: True, ejecutar=rep) == (False, "Ío sigue hablando")
    assert rep.ordenes == []


def test_tono_desconocido_no_falla():
    assert tonos.tono("nada")[0] is False
    assert tonos.main(["nada"]) == 0
