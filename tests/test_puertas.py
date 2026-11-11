"""Pruebas del registro de puertas. Ejecuta: .runtime/venv-tests/bin/python -m pytest -q tests/test_puertas.py"""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import asistente  # noqa: E402
import puertas  # noqa: E402


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "puertas.json"


def test_sin_archivo_no_hay_puertas(ruta):
    assert puertas.leer(ruta) == puertas.vacio()
    assert puertas.main(["lista", "--json"], ruta) == 0


def test_anadir_da_id_corto_y_queda_abierta(ruta, capsys):
    assert puertas.main(["añadir", "Push", "de", "la", "rama", "--comando", "git push origin x",
                         "--coste", "0 €", "--vuelta", "git push --delete origin x", "--proyecto", "io-assistant"], ruta) == 0
    ident = capsys.readouterr().out.strip()
    assert len(ident) == 3 and all(c in asistente.ALFABETO_ID for c in ident)
    p = puertas.leer(ruta)["puertas"][0]
    assert p == {**p, "id": ident, "titulo": "Push de la rama", "comando": "git push origin x", "coste": "0 €",
                 "vuelta": "git push --delete origin x", "proyecto": "io-assistant", "estado": "abierta"}


def test_anadir_sin_comando_es_error_de_uso(ruta, capsys):
    assert puertas.main(["añadir", "algo"], ruta) == 2
    assert "comando" in capsys.readouterr().err


def test_ids_distintos(ruta):
    ids = {puertas.anadir(f"p{i}", "true", ruta=ruta)["id"] for i in range(30)}
    assert len(ids) == 30


def test_responder_solo_anota_y_no_ejecuta(ruta, tmp_path, capsys):
    testigo = tmp_path / "ejecutado"
    p = puertas.anadir("crear testigo", f"touch {testigo}", ruta=ruta)
    assert puertas.main(["responder", p["id"], "sí", "--origen", "cabina"], ruta) == 0
    salida = capsys.readouterr().out
    assert "Nada se ha ejecutado" in salida and f"narrador puerta cerrar {p['id']}" in salida
    assert not testigo.exists()
    guardada = puertas.leer(ruta)["puertas"][0]
    assert guardada["estado"] == "si" and guardada["origen"] == "cabina" and guardada["respondida"]


def test_responder_dos_veces_es_conflicto(ruta, capsys):
    p = puertas.anadir("x", "true", ruta=ruta)
    puertas.responder(p["id"], "no", "voz", ruta)
    assert puertas.main(["responder", p["id"], "si"], ruta) == 4
    assert "ya no está abierta" in capsys.readouterr().err
    assert puertas.leer(ruta)["puertas"][0]["estado"] == "no"


def test_respuesta_y_origen_validos(ruta):
    p = puertas.anadir("x", "true", ruta=ruta)
    assert puertas.main(["responder", p["id"], "quizá"], ruta) == 2
    assert puertas.main(["responder", p["id"], "si", "--origen", "correo"], ruta) == 2
    assert puertas.main(["responder", "zzz", "si"], ruta) == 3


def test_lista_oculta_las_cerradas_salvo_todas(ruta, capsys):
    a = puertas.anadir("a", "true", ruta=ruta)
    puertas.anadir("b", "true", ruta=ruta)
    puertas.cerrar(a["id"], "hecho", ruta)
    capsys.readouterr()
    puertas.main(["lista", "--json"], ruta)
    assert [p["titulo"] for p in json.loads(capsys.readouterr().out)["puertas"]] == ["b"]
    puertas.main(["lista", "--json", "--todas"], ruta)
    todas = json.loads(capsys.readouterr().out)["puertas"]
    assert [p["estado"] for p in todas] == ["cerrada", "abierta"] and todas[0]["nota"] == "hecho"


def test_se_olvidan_solo_las_cerradas_mas_viejas(ruta, monkeypatch):
    monkeypatch.setattr(puertas, "GUARDAR_CERRADAS", 2)
    abierta = puertas.anadir("sigue", "true", ruta=ruta)
    for i in range(4):
        puertas.cerrar(puertas.anadir(f"c{i}", "true", ruta=ruta)["id"], ruta=ruta)
    titulos = [p["titulo"] for p in puertas.leer(ruta)["puertas"]]
    assert titulos == ["sigue", "c2", "c3"] and abierta["id"]


def test_archivo_roto_no_es_registro_vacio(ruta, capsys):
    ruta.write_text("{roto", encoding="utf-8")
    assert puertas.main(["lista"], ruta) == 3
    assert "no es JSON" in capsys.readouterr().err
    assert puertas.main(["añadir", "x", "--comando", "true"], ruta) == 3
    assert ruta.read_text(encoding="utf-8") == "{roto"


def test_esperar_vuelve_al_responder(ruta):
    p = puertas.anadir("x", "true", ruta=ruta)
    threading.Timer(0.2, lambda: puertas.responder(p["id"], "si", "cabina", ruta)).start()
    inicio = time.monotonic()
    vista = puertas.esperar(p["id"], ruta=ruta, sondeo=0.05)
    assert vista["estado"] == "si" and time.monotonic() - inicio < 3
    assert puertas.evento(vista).startswith(f"[puerta {p['id']}] sí a «x»")


def test_esperar_con_maximo_devuelve_abierta(ruta, capsys):
    p = puertas.anadir("x", "true", ruta=ruta)
    assert puertas.main(["esperar", p["id"], "--max", "0"], ruta) == 0
    assert "sigue abierta" in capsys.readouterr().out
