"""Pruebas del almacén local del tablero. Ejecuta: .runtime/venv-tests/bin/python -m pytest -q tests/test_tablero_archivo.py"""

import json
import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import tablero_archivo as almacen  # noqa: E402


def test_vacio_tiene_la_forma_del_archivo():
    assert almacen.vacio() == {"v": 1, "rev": 0, "parte_fecha": None, "ultimo_movimiento": None, "tarjetas": {}}


def test_guardar_y_leer_ida_y_vuelta(tmp_path):
    ruta = tmp_path / "tablero.json"
    estado = almacen.vacio()
    estado["tarjetas"]["a--b"] = {"columna": "nuevos", "detalle": ["añadido"]}
    almacen.guardar(ruta, estado)
    assert almacen.leer(ruta)["tarjetas"] == {"a--b": {"columna": "nuevos", "detalle": ["añadido"]}}


def test_guardar_sube_la_revision(tmp_path):
    ruta = tmp_path / "tablero.json"
    almacen.guardar(ruta, almacen.vacio())
    assert almacen.leer(ruta)["rev"] == 1
    almacen.guardar(ruta, almacen.leer(ruta))
    assert almacen.leer(ruta)["rev"] == 2


def test_guardar_deja_la_version_anterior_en_bak(tmp_path):
    ruta = tmp_path / "tablero.json"
    almacen.guardar(ruta, almacen.vacio())
    assert not (tmp_path / "tablero.json.bak").exists()
    almacen.guardar(ruta, almacen.leer(ruta))
    assert json.loads((tmp_path / "tablero.json.bak").read_text(encoding="utf-8"))["rev"] == 1


def test_guardar_no_deja_temporales(tmp_path):
    ruta = tmp_path / "tablero.json"
    almacen.guardar(ruta, almacen.vacio())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tablero.json"]


def test_guardar_crea_la_carpeta(tmp_path):
    ruta = tmp_path / "nueva" / "tablero.json"
    almacen.guardar(ruta, almacen.vacio())
    assert ruta.exists()


def test_leer_inexistente_lanza(tmp_path):
    with pytest.raises(FileNotFoundError):
        almacen.leer(tmp_path / "tablero.json")


@pytest.mark.parametrize("contenido", [
    "{no es json",
    "[]",
    "{}",
    '{"v": 2, "rev": 1, "tarjetas": {}}',
    '{"v": 1, "rev": "uno", "tarjetas": {}}',
    '{"v": 1, "rev": 1, "tarjetas": []}',
    '{"v": 1, "rev": 1, "tarjetas": {}, "ultimo_movimiento": "x"}',
    "",
])
def test_archivo_roto_lanza_y_no_se_toca(tmp_path, contenido):
    ruta = tmp_path / "tablero.json"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(almacen.ArchivoRoto):
        almacen.leer(ruta)
    assert ruta.read_text(encoding="utf-8") == contenido


def test_cerrojo_ocupado_lanza(tmp_path):
    ruta = tmp_path / "tablero.json"
    with almacen.con_cerrojo(ruta):
        with pytest.raises(almacen.CerrojoOcupado):
            with almacen.con_cerrojo(ruta, espera=0.1):
                pass


def test_cerrojo_se_libera_al_salir(tmp_path):
    ruta = tmp_path / "tablero.json"
    with almacen.con_cerrojo(ruta):
        pass
    with almacen.con_cerrojo(ruta, espera=0.1):
        pass


def test_escritores_a_la_vez_no_pierden_cambios(tmp_path):
    ruta = tmp_path / "tablero.json"
    almacen.guardar(ruta, almacen.vacio())

    def escribir(n):
        with almacen.con_cerrojo(ruta):
            estado = almacen.leer(ruta)
            estado["tarjetas"][f"t{n}"] = {}
            almacen.guardar(ruta, estado)

    hilos = [threading.Thread(target=escribir, args=(n,)) for n in range(12)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    final = almacen.leer(ruta)
    assert len(final["tarjetas"]) == 12
    assert final["rev"] == 13
