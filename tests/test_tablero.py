"""Pruebas de tablero.py (sin red). Ejecuta: .runtime/venv-tests/bin/python -m pytest -q tests/test_tablero.py"""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import tablero  # noqa: E402
import tablero_archivo as almacen  # noqa: E402
from tablero import agrupar, decidir, id_tarjeta, leer_tarjetas, main, mover, ocultar, planificar, ultimo_parte  # noqa: E402

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


@pytest.mark.parametrize("columna", ["nuevos", "en_curso", "dejados"])
def test_verde_no_resuelve_check_de_cierre_manual(columna):
    t = {**tarjeta(columna), "check": "respuestas_fallo"}
    assert decidir(grupo(res("verde", check="respuestas_fallo")), t, parcial=False, hoy=HOY) is None


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
    return {"id": id_, "cliente": "cliente-a", "titulo": "Chatwoot", "fiabilidad": "comprobado", "primera_vez": AYER, **tarjeta(**campos)}


def escrituras(plan):
    return plan["cambios"]


def columnas(plan):
    return Counter(e["data"]["columna"] for e in escrituras(plan))


def test_semilla_real_da_7_y_5():
    plan = planificar(parte_real(), [], modo="semilla")
    assert columnas(plan) == {"nuevos": 7, "dejados": 5}
    assert len(escrituras(plan)) == 12


def test_semilla_real_agrupa_los_dos_env_de_un_cliente():
    plan = planificar(parte_real(), [], modo="semilla")
    env = next(e for e in escrituras(plan) if e["id"] == "cliente-b-services--env_permisos")
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
    clientes = {e["id"]: e["data"]["cliente"] for e in escrituras(plan)}
    assert clientes == {"cliente-b-services--chatwoot": "cliente-b", "10.0.0.1--vps": "global"}


def test_cambio_distingue_crear_de_actualizar():
    plan = planificar(parte_mini(res("rojo"), res(check="tls")), [doc()])
    por_id = {e["id"]: e for e in escrituras(plan)}
    assert por_id["cliente-a--chatwoot"]["crear"] is False
    assert por_id["cliente-a--tls"]["crear"] is True
    assert set(por_id["cliente-a--tls"]) == {"id", "crear", "data"}


def test_plan_ya_no_habla_de_la_pagina():
    plan = planificar(parte_mini(res("rojo")), [doc()])
    assert "lotes" not in plan
    assert "if_version" not in json.dumps(plan) and "collection" not in json.dumps(plan)


def test_cambio_no_manda_campos_internos():
    data = escrituras(planificar(parte_mini(res("rojo")), [doc()]))[0]["data"]
    assert "id" not in data and "version" not in data


def test_sin_cambios_lotes_vacios():
    t = doc(columna="nuevos", ultima=HOY)
    assert planificar(parte_mini(res("ambar")), [t])["cambios"] == []


def test_parte_antiguo_no_mueve():
    plan = planificar(parte_mini(res("verde"), fecha=AYER), [doc(ultima=HOY)])
    assert plan["cambios"] == []
    assert any("antiguo" in a for a in plan["avisos"])


def test_grupo_ausente_no_cambia():
    assert planificar(parte_mini(res(check="tls", estado="verde")), [doc(columna="nuevos")])["cambios"] == []


def test_ignorar_no_recrea_tarjeta_invalida():
    assert planificar(parte_mini(res("rojo")), [], ignorar={"cliente-a--chatwoot"})["cambios"] == []


def test_parcial_no_crea_desde_planificar():
    assert planificar(parte_mini(res("rojo"), parcial=True), [])["cambios"] == []


def test_muchos_cambios_van_en_una_sola_lista():
    resultados = [res(check=f"c{i}") for i in range(120)]
    plan = planificar(parte_mini(*resultados), [])
    assert len({e["id"] for e in escrituras(plan)}) == 120


def test_plan_devuelve_fecha():
    assert planificar(parte_mini(), [])["fecha"] == HOY


# --- leer tarjetas ---

def guardar(carpeta, nombre, contenido):
    (carpeta / f"{nombre}.json").write_text(contenido if isinstance(contenido, str) else json.dumps(contenido), encoding="utf-8")


def sin_internos(d):
    return {k: v for k, v in d.items() if k != "id"}


def test_leer_tarjetas_toma_el_id_del_nombre(tmp_path):
    guardar(tmp_path, "cliente-a--chatwoot", sin_internos(doc()))
    tarjetas, invalidas, avisos = leer_tarjetas(tmp_path)
    assert [t["id"] for t in tarjetas] == ["cliente-a--chatwoot"]
    assert "version" not in tarjetas[0]
    assert invalidas == set() and avisos == []


def test_tarjeta_invalida_se_ignora_con_aviso(tmp_path):
    guardar(tmp_path, "buena", sin_internos(doc()))
    guardar(tmp_path, "columna-rara", sin_internos(doc(columna="x")))
    guardar(tmp_path, "rota", "{no es json")
    tarjetas, invalidas, avisos = leer_tarjetas(tmp_path)
    assert [t["id"] for t in tarjetas] == ["buena"]
    assert invalidas == {"columna-rara", "rota"}
    assert len(avisos) == 2


def test_leer_carpeta_inexistente_lanza(tmp_path):
    with pytest.raises(FileNotFoundError):
        leer_tarjetas(tmp_path / "no")


# --- fiabilidad del plan: nunca un verde falso ---

def test_plan_fiable_sin_incidencias():
    assert planificar(parte_mini(res("ambar")), [])["fiable"] is True


def test_tarjeta_invalida_hace_el_plan_no_fiable():
    plan = planificar(parte_mini(), [], ignorar={"cliente-a--chatwoot"})
    assert plan["fiable"] is False


def test_parte_antiguo_hace_el_plan_no_fiable():
    assert planificar(parte_mini(fecha=AYER), [doc(ultima=HOY)])["fiable"] is False


# --- orden narrador tablero: simulación (plan y semilla) ---

@pytest.fixture
def archivo(tmp_path, monkeypatch):
    ruta = tmp_path / "datos" / "tablero.json"
    monkeypatch.setattr(tablero, "ARCHIVO", ruta)
    return ruta


def crear_tablero(ruta, *docs, **extra):
    estado = {**almacen.vacio(), "tarjetas": {d["id"]: sin_internos(d) for d in docs}, **extra}
    return almacen.guardar(ruta, estado)


def salida(capsys):
    return json.loads(capsys.readouterr().out)


def test_main_tarjeta_invalida_no_da_verde_fiable(archivo, capsys):
    crear_tablero(archivo, doc("cliente-a--meta_numero", columna="x"))
    assert main(["plan", "--parte", str(FIXTURE)]) == 0
    assert salida(capsys)["fiable"] is False


def test_main_semilla_imprime_json_valido(archivo, capsys):
    assert main(["semilla", "--parte", str(FIXTURE)]) == 0
    assert len(salida(capsys)["cambios"]) == 12
    assert not archivo.exists()


def test_main_plan_no_usa_semilla(archivo, capsys):
    crear_tablero(archivo)
    assert main(["plan", "--parte", str(FIXTURE)]) == 0
    assert {e["data"]["columna"] for e in salida(capsys)["cambios"]} == {"nuevos"}


def test_main_plan_no_escribe(archivo, capsys):
    crear_tablero(archivo)
    antes = archivo.read_text(encoding="utf-8")
    assert main(["plan", "--parte", str(FIXTURE)]) == 0
    assert archivo.read_text(encoding="utf-8") == antes


def test_main_avisa_de_tarjeta_invalida_y_no_la_recrea(archivo, capsys):
    crear_tablero(archivo, doc("cliente-a--meta_numero", columna="x"))
    assert main(["plan", "--parte", str(FIXTURE)]) == 0
    datos = salida(capsys)
    assert "cliente-a--meta_numero" not in {e["id"] for e in datos["cambios"]}
    assert datos["avisos"]


def test_main_plan_sin_archivo_sale_3(archivo):
    assert main(["plan", "--parte", str(FIXTURE)]) == 3


def test_main_archivo_roto_sale_3_y_no_se_toca(archivo):
    archivo.parent.mkdir(parents=True)
    archivo.write_text("{roto", encoding="utf-8")
    for orden in (["plan", "--parte", str(FIXTURE)], ["aplicar", "--parte", str(FIXTURE)], ["ver", "--json"],
                  ["mover", "a--b", "en_curso", "--origen", "mod"], ["deshacer", "--origen", "mod"]):
        assert main(orden) == 3
    assert archivo.read_text(encoding="utf-8") == "{roto"


def test_main_parte_ilegible_sale_3(archivo, tmp_path):
    crear_tablero(archivo)
    malo = tmp_path / "parte.json"
    malo.write_text("{", encoding="utf-8")
    assert main(["plan", "--parte", str(malo)]) == 3


def test_main_parte_sin_campos_sale_3(archivo, tmp_path):
    crear_tablero(archivo)
    malo = tmp_path / "parte.json"
    malo.write_text("{}", encoding="utf-8")
    assert main(["plan", "--parte", str(malo)]) == 3


def test_main_parte_inexistente_sale_3(archivo, tmp_path):
    crear_tablero(archivo)
    assert main(["plan", "--parte", str(tmp_path / "no.json")]) == 3


# --- mover: función pura ---

def test_mover_apunta_origen_y_quita_la_marca():
    c = mover(tarjeta("nuevos", marca="reabierta"), "en_curso", "mod", HOY)
    assert c == {"columna": "en_curso", "marca": None, "historial": [{"fecha": HOY, "de": "nuevos", "a": "en_curso", "origen": "mod"}]}


def test_mover_recorta_el_historial_a_20():
    previos = [{"fecha": AYER, "de": "a", "a": "b", "origen": "pagina"}] * 20
    c = mover(tarjeta("nuevos", historial=previos), "resueltos", "voz", HOY)
    assert len(c["historial"]) == 20 and c["historial"][-1]["origen"] == "voz"


@pytest.mark.parametrize("origen", ["parte", "pagina", "otro"])
def test_mover_solo_admite_mod_o_voz(origen):
    with pytest.raises(ValueError):
        mover(tarjeta("nuevos"), "en_curso", origen, HOY)


def test_mover_a_columna_desconocida_lanza():
    with pytest.raises(ValueError):
        mover(tarjeta("nuevos"), "papelera", "mod", HOY)


# --- orden narrador tablero ver ---

def test_ver_sin_archivo_da_tablero_vacio(archivo, capsys):
    assert main(["ver", "--json"]) == 0
    datos = salida(capsys)
    assert datos["existe"] is False and datos["tarjetas"] == [] and datos["puede_deshacer"] is False
    assert not archivo.exists()


def test_ver_lista_las_tarjetas_con_id(archivo, capsys):
    crear_tablero(archivo, doc("a--uno", columna="en_curso", nivel="rojo"), doc("a--dos", columna="dejados"), parte_fecha=AYER)
    assert main(["ver", "--json"]) == 0
    datos = salida(capsys)
    assert datos["existe"] is True and datos["rev"] == 1 and datos["parte_fecha"] == AYER
    assert {t["id"]: t["columna"] for t in datos["tarjetas"]} == {"a--uno": "en_curso", "a--dos": "dejados"}
    assert datos["semaforo"] == "rojo"


def test_ver_semaforo_ignora_dejados_y_resueltos(archivo, capsys):
    crear_tablero(archivo, doc("a--uno", columna="dejados", nivel="rojo"), doc("a--dos", columna="resueltos", nivel="rojo"))
    main(["ver", "--json"])
    assert salida(capsys)["semaforo"] == "verde"


def test_ver_avisa_de_tarjeta_invalida_sin_listarla(archivo, capsys):
    crear_tablero(archivo, doc("a--uno"), doc("a--mala", nivel="ROJO"))
    assert main(["ver", "--json"]) == 0
    datos = salida(capsys)
    assert [t["id"] for t in datos["tarjetas"]] == ["a--uno"]
    assert any("a--mala" in a for a in datos["avisos"])


def test_ver_sin_json_es_texto_legible(archivo, capsys):
    crear_tablero(archivo, doc("a--uno", columna="en_curso"))
    assert main(["ver"]) == 0
    texto = capsys.readouterr().out
    assert "en curso" in texto.lower() and "a--uno" in texto


def test_ver_no_escribe(archivo):
    crear_tablero(archivo, doc("a--uno"))
    antes = archivo.read_text(encoding="utf-8")
    main(["ver", "--json"])
    assert archivo.read_text(encoding="utf-8") == antes


# --- orden narrador tablero mover ---

def guardada(ruta, id_):
    return almacen.leer(ruta)["tarjetas"][id_]


def test_main_mover_escribe_columna_e_historial(archivo, capsys):
    crear_tablero(archivo, doc("a--uno", marca="reabierta"), doc("a--dos"))
    assert main(["mover", "a--uno", "en_curso", "--origen", "mod", "--hoy", HOY]) == 0
    t = guardada(archivo, "a--uno")
    assert t["columna"] == "en_curso" and t["marca"] is None
    assert t["historial"][-1] == {"fecha": HOY, "de": "nuevos", "a": "en_curso", "origen": "mod"}
    assert guardada(archivo, "a--dos") == sin_internos(doc("a--dos"))
    datos = salida(capsys)
    assert datos["rev"] == 2 and datos["puede_deshacer"] is True
    assert {t["id"]: t["columna"] for t in datos["tarjetas"]}["a--uno"] == "en_curso"


def test_main_mover_no_toca_nivel_ni_detalle(archivo):
    crear_tablero(archivo, doc("a--uno", nivel="rojo", detalle=("x", "y")))
    main(["mover", "a--uno", "resueltos", "--origen", "voz", "--hoy", HOY])
    t = guardada(archivo, "a--uno")
    assert (t["nivel"], t["detalle"], t["ultima_vez"], t["fiabilidad"]) == ("rojo", ["x", "y"], AYER, "comprobado")


def test_main_mover_id_desconocido_sale_1(archivo):
    crear_tablero(archivo, doc("a--uno"))
    assert main(["mover", "a--no", "en_curso", "--origen", "mod"]) == 1
    assert almacen.leer(archivo)["rev"] == 1


def test_main_mover_a_la_misma_columna_sale_1(archivo):
    crear_tablero(archivo, doc("a--uno"))
    assert main(["mover", "a--uno", "nuevos", "--origen", "mod"]) == 1
    assert almacen.leer(archivo)["rev"] == 1


def test_main_mover_desde_columna_que_ya_no_es_sale_4(archivo):
    crear_tablero(archivo, doc("a--uno", columna="resueltos"))
    assert main(["mover", "a--uno", "en_curso", "--origen", "mod", "--desde", "nuevos"]) == 4
    assert guardada(archivo, "a--uno")["columna"] == "resueltos"


def test_main_mover_desde_correcto_pasa(archivo):
    crear_tablero(archivo, doc("a--uno"))
    assert main(["mover", "a--uno", "en_curso", "--origen", "mod", "--desde", "nuevos"]) == 0


def test_main_mover_sin_archivo_sale_3(archivo):
    assert main(["mover", "a--uno", "en_curso", "--origen", "mod"]) == 3
    assert not archivo.exists()


@pytest.mark.parametrize("orden", [
    ["mover", "a--uno", "papelera", "--origen", "mod"],
    ["mover", "a--uno", "en_curso", "--origen", "parte"],
    ["mover", "a--uno", "en_curso"],
])
def test_main_mover_con_argumentos_invalidos_no_escribe(archivo, orden):
    crear_tablero(archivo, doc("a--uno"))
    with pytest.raises(SystemExit):
        main(orden)
    assert almacen.leer(archivo)["rev"] == 1


def test_main_mover_tarjeta_invalida_sale_1(archivo):
    crear_tablero(archivo, doc("a--mala", nivel="ROJO"))
    assert main(["mover", "a--mala", "en_curso", "--origen", "mod"]) == 1


def test_main_cerrojo_ocupado_sale_5(archivo, monkeypatch):
    crear_tablero(archivo, doc("a--uno"))
    monkeypatch.setattr(almacen, "ESPERA", 0.1)
    with almacen.con_cerrojo(archivo):
        assert main(["mover", "a--uno", "en_curso", "--origen", "mod"]) == 5
    assert guardada(archivo, "a--uno")["columna"] == "nuevos"


# --- orden narrador tablero deshacer ---

def test_main_deshacer_devuelve_columna_y_marca(archivo, capsys):
    crear_tablero(archivo, doc("a--uno", marca="reabierta"))
    main(["mover", "a--uno", "resueltos", "--origen", "mod", "--hoy", HOY])
    capsys.readouterr()
    assert main(["deshacer", "--origen", "voz", "--hoy", HOY]) == 0
    t = guardada(archivo, "a--uno")
    assert t["columna"] == "nuevos" and t["marca"] == "reabierta"
    assert t["historial"][-1] == {"fecha": HOY, "de": "resueltos", "a": "nuevos", "origen": "voz"}
    datos = salida(capsys)
    assert datos["deshecho"] == {"id": "a--uno", "cliente": "cliente-a", "titulo": "Chatwoot", "de": "resueltos", "a": "nuevos"}
    assert datos["puede_deshacer"] is False


def test_main_deshacer_dos_veces_sale_1(archivo):
    crear_tablero(archivo, doc("a--uno"))
    main(["mover", "a--uno", "en_curso", "--origen", "mod"])
    assert main(["deshacer", "--origen", "mod"]) == 0
    assert main(["deshacer", "--origen", "mod"]) == 1


def test_main_deshacer_sin_movimientos_sale_1(archivo):
    crear_tablero(archivo, doc("a--uno"))
    assert main(["deshacer", "--origen", "mod"]) == 1
    assert almacen.leer(archivo)["rev"] == 1


def test_main_deshacer_no_pisa_lo_que_movio_el_parte(archivo, capsys):
    crear_tablero(archivo, doc("cliente-a--chatwoot"))
    main(["mover", "cliente-a--chatwoot", "en_curso", "--origen", "mod", "--hoy", HOY])
    parte = archivo.parent / "parte.json"
    parte.write_text(json.dumps(parte_mini(res("verde"))), encoding="utf-8")
    assert main(["aplicar", "--parte", str(parte)]) == 0
    assert guardada(archivo, "cliente-a--chatwoot")["columna"] == "resueltos"
    capsys.readouterr()
    assert main(["ver", "--json"]) == 0
    assert salida(capsys)["puede_deshacer"] is False
    assert main(["deshacer", "--origen", "mod"]) == 1
    assert guardada(archivo, "cliente-a--chatwoot")["columna"] == "resueltos"


# --- orden narrador tablero aplicar ---

def parte_en(ruta, *resultados, **opciones):
    destino = ruta.parent / "parte.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(parte_mini(*resultados, **opciones)), encoding="utf-8")
    return str(destino)


def test_aplicar_crea_actualiza_y_resuelve(archivo, capsys):
    crear_tablero(archivo, doc("cliente-a--chatwoot"), doc("cliente-a--tls", columna="en_curso"))
    parte = parte_en(archivo, res("verde"), res("rojo", check="tls", valor="caduca"), res("ambar", check="wf_activo"))
    assert main(["aplicar", "--parte", parte]) == 0
    tarjetas = almacen.leer(archivo)["tarjetas"]
    assert tarjetas["cliente-a--chatwoot"]["columna"] == "resueltos" and tarjetas["cliente-a--chatwoot"]["marca"] == "automatica"
    assert (tarjetas["cliente-a--tls"]["columna"], tarjetas["cliente-a--tls"]["nivel"], tarjetas["cliente-a--tls"]["detalle"]) == ("en_curso", "rojo", ["caduca"])
    assert tarjetas["cliente-a--tls"]["titulo"] == "Chatwoot"  # los campos que no cambian se conservan
    assert tarjetas["cliente-a--wf_activo"]["columna"] == "nuevos"
    assert "id" not in tarjetas["cliente-a--wf_activo"]
    datos = salida(capsys)
    assert datos["aplicados"] == 3 and datos["fiable"] is True and datos["semaforo"] == "rojo"
    assert "cambios" not in datos
    assert almacen.leer(archivo)["parte_fecha"] == HOY


def test_aplicar_es_idempotente(archivo, capsys):
    crear_tablero(archivo)
    parte = parte_en(archivo, res("rojo"))
    main(["aplicar", "--parte", parte])
    rev = almacen.leer(archivo)["rev"]
    capsys.readouterr()
    assert main(["aplicar", "--parte", parte]) == 0
    assert salida(capsys)["aplicados"] == 0
    assert almacen.leer(archivo)["rev"] == rev


def test_aplicar_respeta_la_tarjeta_movida_por_el_usuario(archivo):
    crear_tablero(archivo, doc("cliente-a--chatwoot"))
    main(["mover", "cliente-a--chatwoot", "dejados", "--origen", "voz", "--hoy", HOY])
    main(["aplicar", "--parte", parte_en(archivo, res("ambar"))])
    assert guardada(archivo, "cliente-a--chatwoot")["columna"] == "dejados"


def test_aplicar_no_cierra_check_de_cierre_manual(archivo):
    crear_tablero(archivo, {**doc("cliente-a--respuestas_fallo"), "check": "respuestas_fallo"})
    main(["aplicar", "--parte", parte_en(archivo, res("verde", check="respuestas_fallo"))])
    assert guardada(archivo, "cliente-a--respuestas_fallo")["columna"] == "nuevos"


def test_aplicar_sin_archivo_sale_3_y_no_lo_crea(archivo):
    assert main(["aplicar", "--parte", parte_en(archivo, res("rojo"))]) == 3
    assert not archivo.exists()


def test_aplicar_crear_estrena_el_tablero(archivo):
    assert main(["aplicar", "--crear", "--parte", parte_en(archivo, res("rojo"))]) == 0
    assert list(almacen.leer(archivo)["tarjetas"]) == ["cliente-a--chatwoot"]


def test_aplicar_fecha_distinta_no_escribe(archivo, capsys):
    crear_tablero(archivo, doc("cliente-a--chatwoot"))
    assert main(["aplicar", "--fecha", "2026-11-04", "--parte", parte_en(archivo, res("verde"))]) == 0
    datos = salida(capsys)
    assert datos["fiable"] is False and datos["aplicados"] == 0
    assert almacen.leer(archivo)["rev"] == 1 and almacen.leer(archivo)["parte_fecha"] is None


def test_aplicar_parcial_actualiza_detalle_sin_fijar_la_fecha_del_parte(archivo):
    crear_tablero(archivo, doc("cliente-a--chatwoot"))
    main(["aplicar", "--parte", parte_en(archivo, res("rojo", valor="nuevo"), parcial=True)])
    estado = almacen.leer(archivo)
    assert estado["tarjetas"]["cliente-a--chatwoot"]["detalle"] == ["nuevo"]
    assert estado["tarjetas"]["cliente-a--chatwoot"]["nivel"] == "ambar"
    assert estado["parte_fecha"] is None


def test_aplicar_conserva_la_tarjeta_invalida_y_no_es_fiable(archivo, capsys):
    mala = doc("cliente-a--chatwoot", nivel="ROJO")
    crear_tablero(archivo, mala)
    assert main(["aplicar", "--parte", parte_en(archivo, res("rojo"), res("ambar", check="tls"))]) == 0
    assert salida(capsys)["fiable"] is False
    tarjetas = almacen.leer(archivo)["tarjetas"]
    assert tarjetas["cliente-a--chatwoot"] == sin_internos(mala)
    assert "cliente-a--tls" in tarjetas


def test_aplicar_no_mezcla_clientes(archivo):
    crear_tablero(archivo)
    main(["aplicar", "--parte", parte_en(archivo, res("rojo", ambito="cliente-a"), res("ambar", ambito="cliente-b-services"))])
    tarjetas = almacen.leer(archivo)["tarjetas"]
    assert tarjetas["cliente-a--chatwoot"]["cliente"] == "global"
    assert tarjetas["cliente-b-services--chatwoot"]["cliente"] == "cliente-b"
    assert tarjetas["cliente-a--chatwoot"]["nivel"] == "rojo" and tarjetas["cliente-b-services--chatwoot"]["nivel"] == "ambar"


# --- orden narrador tablero importar (migración desde la página) ---

def test_importar_crea_el_archivo_con_el_id_del_nombre(archivo, tmp_path, capsys):
    movida = doc("cliente-a--meta_numero", columna="en_curso", historial=[{"fecha": AYER, "de": "nuevos", "a": "en_curso", "origen": "voz"}])
    guardar(tmp_path, "cliente-a--chatwoot", sin_internos(doc()))
    guardar(tmp_path, "cliente-a--meta_numero", sin_internos(movida))
    assert main(["importar", str(tmp_path)]) == 0
    estado = almacen.leer(archivo)
    assert estado["tarjetas"] == {"cliente-a--chatwoot": sin_internos(doc()), "cliente-a--meta_numero": sin_internos(movida)}
    assert estado["parte_fecha"] == AYER and estado["ultimo_movimiento"] is None
    datos = salida(capsys)
    assert datos["importadas"] == 2 and datos["columnas"] == {"nuevos": 1, "en_curso": 1}


def test_importar_oculta_tokens_del_detalle(archivo, tmp_path):
    guardar(tmp_path, "a--uno", sin_internos(doc("a--uno", detalle=("clave sk-abcdefghijklmnop123456",))))
    assert main(["importar", str(tmp_path)]) == 0
    assert "sk-abc" not in json.dumps(almacen.leer(archivo))


def test_importar_se_niega_si_ya_hay_tablero(archivo, tmp_path):
    crear_tablero(archivo, doc("a--uno"))
    guardar(tmp_path, "a--dos", sin_internos(doc("a--dos")))
    assert main(["importar", str(tmp_path)]) == 1
    assert list(almacen.leer(archivo)["tarjetas"]) == ["a--uno"]


def test_importar_con_un_documento_invalido_no_escribe_nada(archivo, tmp_path):
    guardar(tmp_path, "a--uno", sin_internos(doc("a--uno")))
    guardar(tmp_path, "a--mala", "{rota")
    assert main(["importar", str(tmp_path)]) == 3
    assert not archivo.exists()


def test_importar_carpeta_vacia_o_inexistente_sale_3(archivo, tmp_path):
    assert main(["importar", str(tmp_path)]) == 3
    assert main(["importar", str(tmp_path / "no")]) == 3
    assert not archivo.exists()


def test_importar_no_toca_la_carpeta_de_origen(archivo, tmp_path):
    guardar(tmp_path, "a--uno", sin_internos(doc("a--uno")))
    antes = (tmp_path / "a--uno.json").read_text(encoding="utf-8")
    main(["importar", str(tmp_path)])
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["a--uno.json"]
    assert (tmp_path / "a--uno.json").read_text(encoding="utf-8") == antes


def test_parte_por_defecto_es_el_ultimo_completo(tmp_path):
    for nombre in ("2026-11-02.json", "2026-11-03.json", "2026-11-03-parcial-x.json", "pendientes_cache.json"):
        (tmp_path / nombre).write_text("{}", encoding="utf-8")
    assert ultimo_parte(tmp_path).name == "2026-11-03.json"


def test_sin_partes_por_defecto_lanza(tmp_path):
    with pytest.raises(FileNotFoundError):
        ultimo_parte(tmp_path)


# --- guías de Ío ---

SKILLS = RAIZ / "skills"


def skill(nombre):
    return (SKILLS / nombre / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("texto", ["[voz-equipo]", "narrador tablero mover", "--origen voz", "narrador tablero deshacer", "narrador tablero ver",
                                   "deshaz", "producción", "tarjetas", "respuestas de emergencia"])
def test_skill_tablero_cubre_limites(texto):
    assert texto in skill("io-tablero")


@pytest.mark.parametrize("texto", ["narrador tablero aplicar", "--fecha", "resumen_voz", "fiable", "estimado"])
def test_parte_matinal_usa_tablero(texto):
    assert texto in skill("io-parte-matinal")


@pytest.mark.parametrize("nombre", ["io-tablero", "io-parte-matinal"])
@pytest.mark.parametrize("texto", ["ArtifactData", "if_version", "--versiones", "version_mismatch"])
def test_las_guias_ya_no_usan_la_pagina(nombre, texto):
    assert texto not in skill(nombre)


# --- revisión final: nunca un verde falso ---

def test_parte_parcial_no_es_fiable():
    plan = planificar(parte_mini(res("rojo"), parcial=True), [])
    assert plan["fiable"] is False
    assert any("parcial" in a for a in plan["avisos"])


def test_fecha_esperada_distinta_no_es_fiable():
    plan = planificar(parte_mini(res("verde"), fecha=AYER), [doc(columna="nuevos", ultima=AYER)], fecha_esperada=HOY)
    assert plan["fiable"] is False
    assert plan["cambios"] == []


def test_fecha_esperada_igual_es_fiable():
    assert planificar(parte_mini(), [], fecha_esperada=HOY)["fiable"] is True


def test_main_fecha_del_parte_distinta(archivo, capsys):
    crear_tablero(archivo)
    assert main(["plan", "--parte", str(FIXTURE), "--fecha", "2026-11-04"]) == 0
    assert json.loads(capsys.readouterr().out)["fiable"] is False


@pytest.mark.parametrize("cambio", [
    {"columna": []},
    {"nivel": None},
    {"nivel": "ROJO"},
    {"primera_vez": "ayer"},
    {"primera_vez": None},
    {"ultima_vez": None},
    {"historial": None},
    {"detalle": "texto"},
])
def test_documento_con_esquema_roto_es_invalido(tmp_path, cambio):
    guardar(tmp_path, "mala", {**sin_internos(doc()), **cambio})
    tarjetas, invalidas, avisos = leer_tarjetas(tmp_path)
    assert tarjetas == [] and invalidas == {"mala"} and len(avisos) == 1


def test_estado_desconocido_no_resuelve():
    assert grupo(res("raro"))["situacion"] == "sin_comprobar"
    assert decidir(grupo(res("raro")), tarjeta("nuevos"), parcial=False, hoy=HOY) is None
