"""Pruebas de tablero.py (sin red). Ejecuta: .runtime/venv-tests/bin/python -m pytest -q tests/test_tablero.py"""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
from tablero import agrupar, decidir, id_tarjeta, leer_tarjetas, main, ocultar, planificar, ultimo_parte  # noqa: E402

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


# --- plan de cambios ---

FIXTURE = RAIZ / "tests" / "fixtures" / "parte_tablero.json"


def parte_real():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def parte_mini(*resultados, fecha=HOY, parcial=False):
    return {"compacto": {"fecha": fecha}, "parcial": parcial, "tenants": {"cliente-b-services": "cliente-b"}, "resultados": list(resultados)}


def doc(id_="cliente-a--chatwoot", **campos):
    return {"id": id_, "version": 7, "cliente": "cliente-a", "titulo": "Chatwoot", "fiabilidad": "comprobado", "primera_vez": AYER, **tarjeta(**campos)}


def escrituras(plan):
    return [e for lote in plan["lotes"] for e in lote]


def columnas(plan):
    return Counter(e["data"]["columna"] for e in escrituras(plan))


def test_semilla_real_da_7_y_5():
    plan = planificar(parte_real(), [], modo="semilla")
    assert columnas(plan) == {"nuevos": 7, "dejados": 5}
    assert len(escrituras(plan)) == 12


def test_semilla_real_agrupa_los_dos_env_de_un_cliente():
    plan = planificar(parte_real(), [], modo="semilla")
    env = next(e for e in escrituras(plan) if e["doc_id"] == "cliente-b-services--env_permisos")
    assert len(env["data"]["detalle"]) == 2


def test_semaforo_real_en_rojo():
    assert planificar(parte_real(), [], modo="semilla")["semaforo"] == "rojo"


def test_semaforo_ignora_dejados():
    plan = planificar(parte_mini(res("rojo")), [doc(columna="dejados", nivel="rojo")])
    assert plan["semaforo"] == "verde"


def test_semaforo_ambar():
    assert planificar(parte_mini(res("ambar")), [])["semaforo"] == "ambar"


def test_voz_activas_ordenadas_y_cifra_dejadas():
    tarjetas = [
        doc("a--uno", columna="nuevos", nivel="ambar"),
        {**doc("a--dos", columna="en_curso", nivel="rojo"), "primera_vez": "2026-11-01"},
        {**doc("a--tres", columna="nuevos", nivel="rojo"), "primera_vez": "2026-10-20"},
        doc("a--cuatro", columna="dejados"),
        doc("a--cinco", columna="resueltos"),
    ]
    voz = planificar(parte_mini(), tarjetas)["voz"]
    assert [a["id"] for a in voz["activas"]] == ["a--tres", "a--dos", "a--uno"]
    assert voz["dejadas"] == 1
    assert voz["activas"][0]["dias"] == 14
    assert set(voz["activas"][0]) == {"id", "cliente", "titulo", "nivel", "valores", "fiabilidad", "marca", "dias"}


def test_voz_refleja_los_cambios_del_plan():
    voz = planificar(parte_mini(res("verde")), [doc(columna="nuevos")])["voz"]
    assert voz["activas"] == []


def test_voz_incluye_reabierta_con_marca():
    voz = planificar(parte_mini(res("ambar")), [doc(columna="resueltos")])["voz"]
    assert voz["activas"][0]["marca"] == "reabierta"


def test_sin_comprobar_lista_na_y_error():
    plan = planificar(parte_real(), [], modo="semilla")
    texto = " ".join(plan["sin_comprobar"])
    assert "cliente-c" in texto and "Chatwoot" in texto
    assert "correo técnico" in texto and "sonda de conversación" in texto
    assert len(plan["sin_comprobar"]) == 3


def test_sin_comprobar_incluye_error():
    assert len(planificar(parte_mini(res("error")), [])["sin_comprobar"]) == 1


def test_cliente_usa_nombre_de_voz():
    plan = planificar(parte_mini(res(ambito="cliente-b-services"), res(ambito="10.0.0.1", check="vps")), [])
    clientes = {e["doc_id"]: e["data"]["cliente"] for e in escrituras(plan)}
    assert clientes == {"cliente-b-services--chatwoot": "cliente-b", "10.0.0.1--vps": "global"}


def test_update_lleva_version_y_set_no():
    plan = planificar(parte_mini(res("rojo"), res(check="tls")), [doc()])
    por_id = {e["doc_id"]: e for e in escrituras(plan)}
    assert por_id["cliente-a--chatwoot"]["op"] == "update"
    assert por_id["cliente-a--chatwoot"]["if_version"] == 7
    assert por_id["cliente-a--tls"]["op"] == "set"
    assert "if_version" not in por_id["cliente-a--tls"]
    assert por_id["cliente-a--tls"]["collection"] == "tarjetas"


def test_update_no_manda_campos_internos():
    data = escrituras(planificar(parte_mini(res("rojo")), [doc()]))[0]["data"]
    assert "id" not in data and "version" not in data


def test_sin_cambios_lotes_vacios():
    t = doc(columna="nuevos", ultima=HOY)
    assert planificar(parte_mini(res("ambar")), [t])["lotes"] == []


def test_parte_antiguo_no_mueve():
    plan = planificar(parte_mini(res("verde"), fecha=AYER), [doc(ultima=HOY)])
    assert plan["lotes"] == []
    assert any("antiguo" in a for a in plan["avisos"])


def test_grupo_ausente_no_cambia():
    assert planificar(parte_mini(res(check="tls", estado="verde")), [doc(columna="nuevos")])["lotes"] == []


def test_ignorar_no_recrea_tarjeta_invalida():
    assert planificar(parte_mini(res("rojo")), [], ignorar={"cliente-a--chatwoot"})["lotes"] == []


def test_parcial_no_crea_desde_planificar():
    assert planificar(parte_mini(res("rojo"), parcial=True), [])["lotes"] == []


def test_mas_de_50_escrituras_en_lotes():
    resultados = [res(check=f"c{i}") for i in range(120)]
    plan = planificar(parte_mini(*resultados), [])
    assert [len(lote) for lote in plan["lotes"]] == [50, 50, 20]
    assert len({e["doc_id"] for e in escrituras(plan)}) == 120


def test_plan_devuelve_fecha():
    assert planificar(parte_mini(), [])["fecha"] == HOY


# --- leer tarjetas ---

def guardar(carpeta, nombre, contenido):
    (carpeta / f"{nombre}.json").write_text(contenido if isinstance(contenido, str) else json.dumps(contenido), encoding="utf-8")


def sin_internos(d):
    return {k: v for k, v in d.items() if k not in ("id", "version")}


def test_leer_tarjetas_toma_id_del_nombre_y_version_del_listado(tmp_path):
    guardar(tmp_path, "cliente-a--chatwoot", sin_internos(doc()))
    tarjetas, invalidas, avisos = leer_tarjetas(tmp_path, {"cliente-a--chatwoot": 9})
    assert [(t["id"], t["version"]) for t in tarjetas] == [("cliente-a--chatwoot", 9)]
    assert invalidas == set() and avisos == []


def test_tarjeta_invalida_se_ignora_con_aviso(tmp_path):
    versiones = {"buena": 1, "columna-rara": 1, "rota": 1}
    guardar(tmp_path, "buena", sin_internos(doc()))
    guardar(tmp_path, "columna-rara", sin_internos(doc(columna="x")))
    guardar(tmp_path, "rota", "{no es json")
    guardar(tmp_path, "sin-version", sin_internos(doc()))
    tarjetas, invalidas, avisos = leer_tarjetas(tmp_path, versiones)
    assert [t["id"] for t in tarjetas] == ["buena"]
    assert invalidas == {"columna-rara", "rota", "sin-version"}
    assert len(avisos) == 3


def test_version_listada_sin_archivo_es_invalida(tmp_path):
    tarjetas, invalidas, avisos = leer_tarjetas(tmp_path, {"perdida": 3})
    assert tarjetas == [] and invalidas == {"perdida"} and len(avisos) == 1


def test_leer_carpeta_inexistente_lanza(tmp_path):
    with pytest.raises(FileNotFoundError):
        leer_tarjetas(tmp_path / "no", {})


# --- fiabilidad del plan: nunca un verde falso ---

def test_plan_fiable_sin_incidencias():
    assert planificar(parte_mini(res("ambar")), [])["fiable"] is True


def test_tarjeta_invalida_hace_el_plan_no_fiable():
    plan = planificar(parte_mini(), [], ignorar={"cliente-a--chatwoot"})
    assert plan["fiable"] is False


def test_parte_antiguo_hace_el_plan_no_fiable():
    assert planificar(parte_mini(fecha=AYER), [doc(ultima=HOY)])["fiable"] is False


def test_main_sin_versiones_no_da_verde_fiable(tmp_path, capsys):
    guardar(tmp_path, "cliente-a--meta_numero", sin_internos(doc(columna="nuevos", nivel="rojo")))
    assert main(["plan", "--tarjetas", str(tmp_path), "--versiones", "{}", "--parte", str(FIXTURE)]) == 0
    assert json.loads(capsys.readouterr().out)["fiable"] is False


# --- orden narrador tablero ---

def test_main_imprime_json_valido(tmp_path, capsys):
    assert main(["semilla", "--tarjetas", str(tmp_path), "--versiones", "{}", "--parte", str(FIXTURE)]) == 0
    assert len([e for lote in json.loads(capsys.readouterr().out)["lotes"] for e in lote]) == 12


def test_main_plan_no_usa_semilla(tmp_path, capsys):
    assert main(["plan", "--tarjetas", str(tmp_path), "--versiones", "{}", "--parte", str(FIXTURE)]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert {e["data"]["columna"] for lote in datos["lotes"] for e in lote} == {"nuevos"}


def test_main_avisa_de_tarjeta_invalida_y_no_la_recrea(tmp_path, capsys):
    guardar(tmp_path, "cliente-a--meta_numero", "{rota")
    assert main(["plan", "--tarjetas", str(tmp_path), "--versiones", "{}", "--parte", str(FIXTURE)]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert "cliente-a--meta_numero" not in {e["doc_id"] for lote in datos["lotes"] for e in lote}
    assert datos["avisos"]


def test_main_sin_carpeta_sale_3(tmp_path):
    assert main(["plan", "--tarjetas", str(tmp_path / "no"), "--versiones", "{}", "--parte", str(FIXTURE)]) == 3


def test_main_versiones_ilegibles_sale_3(tmp_path):
    assert main(["plan", "--tarjetas", str(tmp_path), "--versiones", "{", "--parte", str(FIXTURE)]) == 3


def test_main_usa_las_versiones_del_listado(tmp_path, capsys):
    guardar(tmp_path, "cliente-a--meta_numero", sin_internos(doc(columna="nuevos", nivel="ambar")))
    versiones = json.dumps({"cliente-a--meta_numero": 4})
    assert main(["plan", "--tarjetas", str(tmp_path), "--versiones", versiones, "--parte", str(FIXTURE)]) == 0
    datos = json.loads(capsys.readouterr().out)
    escritura = next(e for lote in datos["lotes"] for e in lote if e["doc_id"] == "cliente-a--meta_numero")
    assert escritura["if_version"] == 4


def test_main_parte_ilegible_sale_3(tmp_path):
    malo = tmp_path / "parte.json"
    malo.write_text("{", encoding="utf-8")
    assert main(["plan", "--tarjetas", str(tmp_path), "--parte", str(malo), "--versiones", "{}"]) == 3


def test_main_parte_sin_campos_sale_3(tmp_path):
    malo = tmp_path / "parte.json"
    malo.write_text("{}", encoding="utf-8")
    assert main(["plan", "--tarjetas", str(tmp_path), "--parte", str(malo), "--versiones", "{}"]) == 3


def test_main_parte_inexistente_sale_3(tmp_path):
    assert main(["plan", "--tarjetas", str(tmp_path), "--parte", str(tmp_path / "no.json"), "--versiones", "{}"]) == 3


def test_parte_por_defecto_es_el_ultimo_completo(tmp_path):
    for nombre in ("2026-11-02.json", "2026-11-03.json", "2026-11-03-parcial-x.json", "pendientes_cache.json"):
        (tmp_path / nombre).write_text("{}", encoding="utf-8")
    assert ultimo_parte(tmp_path).name == "2026-11-03.json"


def test_sin_partes_por_defecto_lanza(tmp_path):
    with pytest.raises(FileNotFoundError):
        ultimo_parte(tmp_path)


# --- guías de Ío ---

SKILLS = RAIZ / "skills"


@pytest.mark.parametrize("texto", ["[voz-equipo]", "if_version", "--versiones", "deshaz", "producción", "tarjetas"])
def test_skill_tablero_cubre_limites(texto):
    assert texto in (SKILLS / "io-tablero" / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("texto", ["narrador tablero plan", "--versiones", "resumen_voz", "fiable", "version_mismatch", "estimado"])
def test_parte_matinal_usa_tablero(texto):
    assert texto in (SKILLS / "io-parte-matinal" / "SKILL.md").read_text(encoding="utf-8")
