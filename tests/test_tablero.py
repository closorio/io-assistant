"""Pruebas de tablero.py (sin red). Ejecuta: .runtime/venv-tests/bin/python -m pytest -q tests/test_tablero.py"""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
from tablero import agrupar, decidir, id_tarjeta, ocultar  # noqa: E402

HOY = "2026-11-03"
AYER = "2026-11-02"


def res(estado="ambar", check="chatwoot", ambito="cliente-a", valor="v", detalle=""):
    return {"check": check, "ambito": ambito, "estado": estado, "valor": valor, "detalle": detalle}


def grupo(*resultados):
    return list(agrupar(list(resultados)).values())[0]


def tarjeta(columna="nuevos", nivel="ambar", detalle=("v",), ultima=AYER, historial=(), marca=None):
    return {"ambito": "cliente-a", "check": "chatwoot", "columna": columna, "nivel": nivel, "detalle": list(detalle),
            "ultima_vez": ultima, "historial": list(historial), "marca": marca}


def aplicar(t, cambios):
    return {**t, **cambios}


# --- identidad y ocultación ---

def test_id_sanea_caracteres():
    assert id_tarjeta("a b", "tls") == "a-b--tls"


def test_id_conserva_puntos_de_una_ip():
    assert id_tarjeta("10.0.0.1", "vps") == "10.0.0.1--vps"


def test_oculta_token_sk():
    assert "sk-abc" not in ocultar("clave sk-abcdefghijklmnop123456")


def test_oculta_token_meta():
    assert "EAAB" not in ocultar("token EAABwzLixnjYBO0ZCabc")


def test_oculta_cadena_larga():
    assert ocultar("x " + "a1" * 20) == "x [oculto]"


def test_no_oculta_texto_normal():
    assert ocultar("25 sin asignar más de 4 h") == "25 sin asignar más de 4 h"


def test_trunca_a_200():
    assert len(ocultar("x " * 500)) <= 200


# --- agrupar ---

def test_agrupa_con_peor_nivel():
    g = grupo(res("ambar", valor="uno"), res("rojo", valor="dos"))
    assert g["nivel"] == "rojo"
    assert g["valores"] == ["uno", "dos"]
    assert g["situacion"] == "anomalia"


def test_solo_valores_de_resultados_con_anomalia():
    assert grupo(res("ambar", valor="mal"), res("verde", valor="bien"))["valores"] == ["mal"]


def test_valor_vacio_usa_detalle():
    assert grupo(res(valor="", detalle="d"))["valores"] == ["d"]


def test_sin_valor_ni_detalle_usa_estado():
    assert grupo(res("rojo", valor="", detalle=""))["valores"] == ["rojo"]


def test_valor_se_oculta_al_agrupar():
    assert "sk-abc" not in grupo(res(valor="sk-abcdefghijklmnop123456"))["valores"][0]


def test_na_y_verde_es_sin_comprobar():
    assert grupo(res("na"), res("verde"))["situacion"] == "sin_comprobar"


def test_error_es_sin_comprobar():
    assert grupo(res("error"))["situacion"] == "sin_comprobar"


def test_todo_verde():
    g = grupo(res("verde"), res("verde"))
    assert g["situacion"] == "verde"
    assert g["nivel"] is None


def test_anomalia_gana_a_na():
    assert grupo(res("na"), res("ambar"))["situacion"] == "anomalia"


def test_ambitos_distintos_no_se_agrupan():
    assert len(agrupar([res(ambito="a"), res(ambito="b")])) == 2


# --- transiciones de un parte completo ---

def test_crea_en_nuevos():
    c = decidir(grupo(res("rojo")), None, parcial=False, hoy=HOY, cliente="cliente")
    assert c["columna"] == "nuevos"
    assert c["marca"] is None
    assert c["nivel"] == "rojo"
    assert c["cliente"] == "cliente"
    assert c["primera_vez"] == c["ultima_vez"] == HOY
    assert c["historial"] == [{"fecha": HOY, "de": None, "a": "nuevos", "origen": "parte"}]


def test_verde_sin_tarjeta_no_crea():
    assert decidir(grupo(res("verde")), None, parcial=False, hoy=HOY) is None


def test_sin_comprobar_sin_tarjeta_no_crea():
    assert decidir(grupo(res("na")), None, parcial=False, hoy=HOY) is None


@pytest.mark.parametrize("columna", ["nuevos", "en_curso"])
def test_abierta_actualiza_sin_mover(columna):
    c = decidir(grupo(res("rojo", valor="nuevo")), tarjeta(columna), parcial=False, hoy=HOY)
    assert "columna" not in c
    assert c == {"nivel": "rojo", "detalle": ["nuevo"], "ultima_vez": HOY}


def test_dejada_empeora_a_nuevos():
    c = decidir(grupo(res("rojo")), tarjeta("dejados", "ambar"), parcial=False, hoy=HOY)
    assert c["columna"] == "nuevos"
    assert c["marca"] == "empeorada"
    assert c["nivel"] == "rojo"
    assert c["historial"][-1] == {"fecha": HOY, "de": "dejados", "a": "nuevos", "origen": "parte"}


def test_dejada_ya_roja_no_empeora():
    c = decidir(grupo(res("rojo")), tarjeta("dejados", "rojo"), parcial=False, hoy=HOY)
    assert "columna" not in c


def test_dejada_sin_empeorar_no_se_mueve():
    c = decidir(grupo(res("ambar")), tarjeta("dejados", "ambar"), parcial=False, hoy=HOY)
    assert "columna" not in c
    assert c["ultima_vez"] == HOY


def test_resuelta_reabre():
    c = decidir(grupo(res("ambar")), tarjeta("resueltos"), parcial=False, hoy=HOY)
    assert c["columna"] == "nuevos"
    assert c["marca"] == "reabierta"
    assert c["historial"][-1]["de"] == "resueltos"


@pytest.mark.parametrize("columna", ["nuevos", "en_curso", "dejados"])
def test_verde_resuelve_abierta(columna):
    c = decidir(grupo(res("verde")), tarjeta(columna), parcial=False, hoy=HOY)
    assert c["columna"] == "resueltos"
    assert c["marca"] == "automatica"
    assert c["historial"][-1] == {"fecha": HOY, "de": columna, "a": "resueltos", "origen": "parte"}


def test_verde_en_resueltos_no_cambia():
    assert decidir(grupo(res("verde")), tarjeta("resueltos"), parcial=False, hoy=HOY) is None


@pytest.mark.parametrize("columna", ["nuevos", "en_curso", "dejados", "resueltos"])
def test_sin_comprobar_no_cambia(columna):
    assert decidir(grupo(res("na")), tarjeta(columna), parcial=False, hoy=HOY) is None


# --- parte parcial ---

def test_parcial_no_crea():
    assert decidir(grupo(res("rojo")), None, parcial=True, hoy=HOY) is None


def test_parcial_no_mueve_ni_toca_nivel():
    c = decidir(grupo(res("rojo", valor="nuevo")), tarjeta("dejados", "ambar"), parcial=True, hoy=HOY)
    assert c == {"detalle": ["nuevo"], "ultima_vez": HOY}


def test_parcial_verde_no_resuelve():
    assert decidir(grupo(res("verde")), tarjeta("nuevos"), parcial=True, hoy=HOY) is None


def test_parcial_no_reabre():
    assert "columna" not in decidir(grupo(res("rojo")), tarjeta("resueltos"), parcial=True, hoy=HOY)


def test_parcial_y_completo_detecta_empeorar():
    t = tarjeta("dejados", "ambar")
    t = aplicar(t, decidir(grupo(res("rojo")), t, parcial=True, hoy=HOY))
    c = decidir(grupo(res("rojo")), t, parcial=False, hoy=HOY)
    assert c["columna"] == "nuevos"
    assert c["marca"] == "empeorada"


# --- idempotencia e historial ---

@pytest.mark.parametrize("estado,columna", [("rojo", "nuevos"), ("rojo", "dejados"), ("ambar", "resueltos"), ("verde", "en_curso")])
def test_idempotente(estado, columna):
    t = tarjeta(columna)
    t = aplicar(t, decidir(grupo(res(estado)), t, parcial=False, hoy=HOY))
    assert decidir(grupo(res(estado)), t, parcial=False, hoy=HOY) is None


def test_creacion_idempotente():
    t = decidir(grupo(res("rojo")), None, parcial=False, hoy=HOY)
    assert decidir(grupo(res("rojo")), t, parcial=False, hoy=HOY) is None


def test_historial_max_20():
    previos = [{"fecha": AYER, "de": "a", "a": "b", "origen": "voz"}] * 20
    c = decidir(grupo(res("verde")), tarjeta("nuevos", historial=previos), parcial=False, hoy=HOY)
    assert len(c["historial"]) == 20
    assert c["historial"][-1]["a"] == "resueltos"


def test_tarjeta_sin_historial_no_falla():
    t = tarjeta("nuevos")
    del t["historial"]
    assert len(decidir(grupo(res("verde")), t, parcial=False, hoy=HOY)["historial"]) == 1


# --- semilla y fiabilidad ---

def test_semilla_env_en_dejados():
    c = decidir(grupo(res(check="env_permisos")), None, parcial=False, hoy=HOY, modo="semilla")
    assert c["columna"] == "dejados"
    assert c["historial"][-1]["a"] == "dejados"


def test_semilla_otro_en_nuevos():
    assert decidir(grupo(res()), None, parcial=False, hoy=HOY, modo="semilla")["columna"] == "nuevos"


def test_plan_env_en_nuevos():
    assert decidir(grupo(res(check="env_permisos")), None, parcial=False, hoy=HOY)["columna"] == "nuevos"


def test_semilla_respeta_tarjeta_existente():
    c = decidir(grupo(res(check="env_permisos")), tarjeta("en_curso"), parcial=False, hoy=HOY, modo="semilla")
    assert "columna" not in c


def test_saldo_es_estimado():
    assert decidir(grupo(res(check="openai_saldo")), None, parcial=False, hoy=HOY)["fiabilidad"] == "estimado"


def test_otro_es_comprobado():
    assert decidir(grupo(res()), None, parcial=False, hoy=HOY)["fiabilidad"] == "comprobado"


def test_titulo_legible():
    assert decidir(grupo(res(check="meta_numero")), None, parcial=False, hoy=HOY)["titulo"] == "número de WhatsApp"
