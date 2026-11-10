"""Tablero de hallazgos del parte: compara el parte con las tarjetas, decide los cambios y los guarda.

Sin red ni .env. Las tarjetas viven en un archivo local (tablero_archivo.py) que leen y escriben
el parte, el mod io-cabina y Ío por voz, siempre a través de `narrador tablero`.
Reglas de transición: docs/superpowers/specs/2026-11-03-tablero-hallazgos-design.md
Almacén y órdenes:    docs/superpowers/specs/2026-11-09-tablero-local-design.md
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tablero_archivo as almacen  # noqa: E402
from comun import RUNTIME  # noqa: E402
from parte_matinal import NOMBRE_CHECK, PARTES  # noqa: E402

ARCHIVO = RUNTIME / "tablero.json"
MAX_HISTORIAL = 20
MAX_TEXTO = 200
ORDEN_COLUMNAS = ("nuevos", "en_curso", "dejados", "resueltos")
COLUMNAS = set(ORDEN_COLUMNAS)
NOMBRE_COLUMNA = {"nuevos": "Nuevos", "en_curso": "En curso", "dejados": "Dejados de lado", "resueltos": "Resueltos"}
ORIGENES_MANUALES = ("mod", "voz")  # «parte» lo pone el cruce; «pagina» solo queda en historiales antiguos
PARTE_COMPLETO = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
ESTIMADOS = {"openai_saldo"}
CIERRE_MANUAL = {"respuestas_fallo"}  # en verde no pasan solas a resueltos: las cierra el usuario
TOKENS = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}|\bEAA[A-Za-z0-9]{8,}|\b[A-Za-z0-9_-]{32,}")


def id_tarjeta(ambito: str, check: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.~:@+-]", "-", f"{ambito}--{check}")


def ocultar(texto: str) -> str:
    return TOKENS.sub("[oculto]", texto)[:MAX_TEXTO]


def agrupar(resultados: list[dict]) -> dict[tuple[str, str], dict]:
    grupos: dict[tuple[str, str], list[dict]] = {}
    for r in resultados:
        grupos.setdefault((r["ambito"], r["check"]), []).append(r)
    return {clave: _grupo(*clave, propios) for clave, propios in grupos.items()}


def _grupo(ambito: str, check: str, propios: list[dict]) -> dict:
    estados = {r["estado"] for r in propios}
    nivel = "rojo" if "rojo" in estados else "ambar" if "ambar" in estados else None
    situacion = "anomalia" if nivel else "verde" if estados == {"verde"} else "sin_comprobar"
    valores = [ocultar(r.get("valor") or r.get("detalle") or r["estado"]) for r in propios if r["estado"] in ("rojo", "ambar")]
    return {"ambito": ambito, "check": check, "situacion": situacion, "nivel": nivel, "valores": valores}


def _mover(tarjeta: dict, a: str, marca: str | None, hoy: str, origen: str = "parte") -> dict:
    linea = {"fecha": hoy, "de": tarjeta["columna"], "a": a, "origen": origen}
    return {"columna": a, "marca": marca, "historial": [*tarjeta.get("historial", []), linea][-MAX_HISTORIAL:]}


def mover(tarjeta: dict, columna: str, origen: str, hoy: str) -> dict:
    """Campos que cambian cuando el usuario mueve una tarjeta desde el mod o por voz. No toca nivel ni detalle."""
    if columna not in COLUMNAS:
        raise ValueError(f"columna desconocida: {columna}")
    if origen not in ORIGENES_MANUALES:
        raise ValueError(f"origen no válido para un movimiento manual: {origen}")
    return _mover(tarjeta, columna, None, hoy, origen)


def _nueva(grupo: dict, hoy: str, modo: str, cliente: str) -> dict:
    columna = "dejados" if modo == "semilla" and grupo["check"] == "env_permisos" else "nuevos"
    return {
        "ambito": grupo["ambito"], "check": grupo["check"], "cliente": cliente,
        "titulo": NOMBRE_CHECK.get(grupo["check"], grupo["check"]),
        "nivel": grupo["nivel"], "detalle": grupo["valores"], "columna": columna, "marca": None,
        "fiabilidad": "estimado" if grupo["check"] in ESTIMADOS else "comprobado",
        "primera_vez": hoy, "ultima_vez": hoy,
        "historial": [{"fecha": hoy, "de": None, "a": columna, "origen": "parte"}],
    }


def _distintos(tarjeta: dict, campos: dict) -> dict:
    return {k: v for k, v in campos.items() if tarjeta.get(k) != v}


def decidir(grupo: dict, tarjeta: dict | None, *, parcial: bool, hoy: str, modo: str = "plan", cliente: str = "global") -> dict | None:
    """Campos que cambian (el documento entero si la tarjeta es nueva), o None si no cambia nada."""
    anomalia = grupo["situacion"] == "anomalia"
    if tarjeta is None:
        return _nueva(grupo, hoy, modo, cliente) if anomalia and not parcial else None
    if parcial:
        return _distintos(tarjeta, {"detalle": grupo["valores"], "ultima_vez": hoy}) or None if anomalia else None
    if grupo["situacion"] == "sin_comprobar":
        return None
    columna = tarjeta["columna"]
    if not anomalia:
        if columna == "resueltos" or grupo["check"] in CIERRE_MANUAL:
            return None
        return _mover(tarjeta, "resueltos", "automatica", hoy)
    cambios = _distintos(tarjeta, {"nivel": grupo["nivel"], "detalle": grupo["valores"], "ultima_vez": hoy})
    if columna == "resueltos":
        cambios |= _mover(tarjeta, "nuevos", "reabierta", hoy)
    elif columna == "dejados" and tarjeta.get("nivel") == "ambar" and grupo["nivel"] == "rojo":
        cambios |= _mover(tarjeta, "nuevos", "empeorada", hoy)
    return cambios or None


def _fecha_valida(valor: object) -> bool:
    try:
        date.fromisoformat(valor)
        return True
    except (TypeError, ValueError):
        return False


def _tarjeta_valida(datos: object) -> bool:
    return (
        isinstance(datos, dict) and isinstance(datos.get("columna"), str) and datos["columna"] in COLUMNAS
        and datos.get("nivel") in ("rojo", "ambar")
        and _fecha_valida(datos.get("primera_vez")) and _fecha_valida(datos.get("ultima_vez"))
        and isinstance(datos.get("detalle"), list) and isinstance(datos.get("historial"), list)
    )


def leer_tarjetas(directorio: Path) -> tuple[list[dict], set[str], list[str]]:
    """Tarjetas válidas, ids inválidos y avisos de una carpeta con un JSON por tarjeta (el export de la página).

    El id es el nombre del archivo. Sin carpeta lanza FileNotFoundError. Solo lo usa `importar`.
    """
    tarjetas, invalidas = [], set()
    for archivo in sorted(a for a in Path(directorio).iterdir() if a.suffix == ".json"):
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            datos = None
        if _tarjeta_valida(datos):
            tarjetas.append({**datos, "id": archivo.stem})
        else:
            invalidas.add(archivo.stem)
    return tarjetas, invalidas, _avisos_invalidas(invalidas)


def _avisos_invalidas(invalidas: set[str]) -> list[str]:
    return [f"tarjeta {id_} ignorada: documento no válido" for id_ in sorted(invalidas)]


def _separar(estado: dict) -> tuple[list[dict], set[str]]:
    """Tarjetas válidas del archivo (con su id) e ids de las que no lo son, que nadie toca."""
    tarjetas, invalidas = [], set()
    for id_, datos in estado["tarjetas"].items():
        if _tarjeta_valida(datos):
            tarjetas.append({**datos, "id": id_})
        else:
            invalidas.add(id_)
    return tarjetas, invalidas


def _semaforo(tarjetas: list[dict]) -> str:
    niveles = {t.get("nivel") for t in tarjetas if t.get("columna") in ("nuevos", "en_curso")}
    return "rojo" if "rojo" in niveles else "ambar" if "ambar" in niveles else "verde"


def _activa(tarjeta: dict, hoy: str) -> dict:
    return {
        "id": tarjeta["id"], "cliente": tarjeta.get("cliente", "global"), "titulo": tarjeta.get("titulo", tarjeta.get("check", "")),
        "nivel": tarjeta.get("nivel"), "valores": tarjeta.get("detalle", []), "fiabilidad": tarjeta.get("fiabilidad", "comprobado"),
        "marca": tarjeta.get("marca"), "dias": (date.fromisoformat(hoy) - date.fromisoformat(tarjeta.get("primera_vez", hoy))).days,
    }


def planificar(parte: dict, tarjetas: list[dict], *, modo: str = "plan", ignorar: set[str] = frozenset(), fecha_esperada: str | None = None) -> dict:
    hoy = parte["compacto"]["fecha"]
    resultados = parte["resultados"]
    nombres = parte.get("tenants", {})
    por_id = {t["id"]: t for t in tarjetas}
    avisos, cambios_plan = [], []
    cruzado = False
    if parte.get("parcial"):
        avisos.append("parte parcial: el semáforo del tablero no lo representa, locuta resumen_voz")
    if fecha_esperada and hoy != fecha_esperada:
        avisos.append(f"parte de {hoy}, se esperaba el de {fecha_esperada}: no se mueve nada")
    elif any(t.get("ultima_vez", "") > hoy for t in tarjetas):
        avisos.append(f"parte antiguo ({hoy}): hay tarjetas más recientes, no se mueve nada")
    else:
        cruzado = True
        for (ambito, check), grupo in agrupar(resultados).items():
            id_ = id_tarjeta(ambito, check)
            if id_ in ignorar:
                continue
            tarjeta = por_id.get(id_)
            cambios = decidir(grupo, tarjeta, parcial=bool(parte.get("parcial")), hoy=hoy, modo=modo, cliente=nombres.get(ambito, "global"))
            if cambios:
                cambios_plan.append({"id": id_, "crear": tarjeta is None, "data": cambios})
                por_id[id_] = {**(tarjeta or {}), **cambios, "id": id_}
    activas = [t for t in por_id.values() if t.get("columna") in ("nuevos", "en_curso")]
    orden = sorted(activas, key=lambda t: (t.get("nivel") != "rojo", t.get("primera_vez", hoy)))
    return {
        "fecha": hoy,
        "fiable": not avisos and not ignorar,
        "cruzado": cruzado,
        "cambios": cambios_plan,
        "semaforo": _semaforo(activas),
        "voz": {"activas": [_activa(t, hoy) for t in orden], "dejadas": sum(t.get("columna") == "dejados" for t in por_id.values())},
        "sin_comprobar": [f"{nombres.get(r['ambito'], 'global')}: {NOMBRE_CHECK.get(r['check'], r['check'])}: {ocultar(r.get('valor') or r.get('detalle') or r['estado'])}"
                          for r in resultados if r["estado"] in ("na", "error")],
        "avisos": avisos,
    }


def ultimo_parte(directorio: Path) -> Path:
    """El parte completo más reciente; los parciales se piden con --parte."""
    completos = sorted(p for p in Path(directorio).iterdir() if PARTE_COMPLETO.match(p.name))
    if not completos:
        raise FileNotFoundError(f"no hay partes en {directorio}")
    return completos[-1]


def vista(estado: dict, *, existe: bool = True) -> dict:
    """El tablero tal como lo consumen el mod y Ío: tarjetas válidas con su id, semáforo y si hay algo que deshacer."""
    tarjetas, invalidas = _separar(estado)
    um = estado.get("ultimo_movimiento")
    por_id = {t["id"]: t for t in tarjetas}
    return {
        "existe": existe, "rev": estado["rev"], "parte_fecha": estado.get("parte_fecha"),
        "semaforo": _semaforo(tarjetas),
        "puede_deshacer": bool(um) and por_id.get(um.get("id"), {}).get("columna") == um.get("a"),
        "ultimo_movimiento": um,
        "tarjetas": tarjetas,
        "avisos": _avisos_invalidas(invalidas),
    }


def _texto(v: dict) -> str:
    if not v["existe"]:
        return "No hay tablero todavía."
    lineas = [f"Tablero (parte del {v['parte_fecha'] or '—'}, semáforo {v['semaforo']})"]
    for columna in ORDEN_COLUMNAS:
        propias = sorted((t for t in v["tarjetas"] if t["columna"] == columna), key=lambda t: (t["nivel"] != "rojo", t.get("cliente", ""), t["id"]))
        lineas.append(f"\n{NOMBRE_COLUMNA[columna]} ({len(propias)})")
        lineas += [f"  [{t['nivel']}] {t.get('cliente', 'global')} · {t.get('titulo', t.get('check', ''))} · {'; '.join(t['detalle'])}  ({t['id']})" for t in propias]
    return "\n".join(lineas + [f"\n⚠ {a}" for a in v["avisos"]])


def _imprimir(datos: dict) -> None:
    print(json.dumps(datos, ensure_ascii=False, indent=1))


def _leer_parte(opciones: argparse.Namespace) -> dict:
    ruta = opciones.parte or ultimo_parte(PARTES)
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _planificar(estado: dict, opciones: argparse.Namespace, modo: str) -> dict:
    tarjetas, invalidas = _separar(estado)
    plan = planificar(_leer_parte(opciones), tarjetas, modo=modo, ignorar=invalidas, fecha_esperada=opciones.fecha)
    plan["avisos"] = _avisos_invalidas(invalidas) + plan["avisos"]
    return plan


def _cmd_ver(opciones: argparse.Namespace) -> int:
    try:
        v = vista(almacen.leer(ARCHIVO))
    except FileNotFoundError:
        v = vista(almacen.vacio(), existe=False)
    if opciones.json:
        _imprimir(v)
    else:
        print(_texto(v))
    return 0


def _cmd_plan(opciones: argparse.Namespace) -> int:
    """Simulación: enseña lo que haría `aplicar`, sin escribir. `semilla` parte de un tablero vacío si no hay archivo."""
    try:
        estado = almacen.leer(ARCHIVO)
    except FileNotFoundError:
        if opciones.orden != "semilla":
            raise
        estado = almacen.vacio()
    _imprimir(_planificar(estado, opciones, opciones.orden))
    return 0


def _cmd_aplicar(opciones: argparse.Namespace) -> int:
    with almacen.con_cerrojo(ARCHIVO, almacen.ESPERA):
        try:
            estado = almacen.leer(ARCHIVO)
        except FileNotFoundError:
            if not opciones.crear:
                raise
            estado = almacen.vacio()
        plan = _planificar(estado, opciones, "plan")
        cambios = plan.pop("cambios")
        for c in cambios:
            estado["tarjetas"][c["id"]] = c["data"] if c["crear"] else {**estado["tarjetas"][c["id"]], **c["data"]}
        fecha = plan["fecha"] if plan["cruzado"] and not plan["avisos"] else estado.get("parte_fecha")
        if cambios or fecha != estado.get("parte_fecha") or not ARCHIVO.exists():
            almacen.guardar(ARCHIVO, {**estado, "parte_fecha": fecha})
    _imprimir({**plan, "aplicados": len(cambios)})
    return 0


def _cmd_mover(opciones: argparse.Namespace) -> int:
    with almacen.con_cerrojo(ARCHIVO, almacen.ESPERA):
        estado = almacen.leer(ARCHIVO)
        tarjeta = estado["tarjetas"].get(opciones.id)
        if not _tarjeta_valida(tarjeta):
            print(f"tablero: no hay ninguna tarjeta válida con el id {opciones.id}", file=sys.stderr)
            return 1
        actual = tarjeta["columna"]
        if opciones.desde and actual != opciones.desde:
            print(f"tablero: {opciones.id} ya no está en {opciones.desde}, está en {actual}", file=sys.stderr)
            return 4
        if actual == opciones.columna:
            print(f"tablero: {opciones.id} ya está en {actual}", file=sys.stderr)
            return 1
        estado["ultimo_movimiento"] = {"id": opciones.id, "de": actual, "a": opciones.columna, "marca": tarjeta.get("marca"), "origen": opciones.origen}
        estado["tarjetas"][opciones.id] = {**tarjeta, **mover(tarjeta, opciones.columna, opciones.origen, opciones.hoy or date.today().isoformat())}
        estado = almacen.guardar(ARCHIVO, estado)
    _imprimir(vista(estado))
    return 0


def _cmd_deshacer(opciones: argparse.Namespace) -> int:
    with almacen.con_cerrojo(ARCHIVO, almacen.ESPERA):
        estado = almacen.leer(ARCHIVO)
        um = estado.get("ultimo_movimiento")
        tarjeta = estado["tarjetas"].get(um["id"]) if um else None
        if not um or not _tarjeta_valida(tarjeta) or tarjeta["columna"] != um["a"] or um.get("de") not in COLUMNAS:
            print("tablero: no hay ningún movimiento que deshacer", file=sys.stderr)
            return 1
        vuelta = mover(tarjeta, um["de"], opciones.origen, opciones.hoy or date.today().isoformat())
        estado["tarjetas"][um["id"]] = {**tarjeta, **vuelta, "marca": um.get("marca")}
        estado["ultimo_movimiento"] = None
        estado = almacen.guardar(ARCHIVO, estado)
    deshecho = {"id": um["id"], "cliente": tarjeta.get("cliente", "global"), "titulo": tarjeta.get("titulo", tarjeta.get("check", "")), "de": um["a"], "a": um["de"]}
    _imprimir({**vista(estado), "deshecho": deshecho})
    return 0


def _cmd_importar(opciones: argparse.Namespace) -> int:
    """Migración: crea el archivo local a partir de la carpeta exportada de la página. No pisa un tablero que ya exista."""
    with almacen.con_cerrojo(ARCHIVO, almacen.ESPERA):
        if ARCHIVO.exists():
            print(f"tablero: {ARCHIVO} ya existe; no se importa encima", file=sys.stderr)
            return 1
        tarjetas, invalidas, _ = leer_tarjetas(opciones.carpeta)
        if invalidas or not tarjetas:
            raise ValueError(f"documentos no válidos: {sorted(invalidas)}" if invalidas else f"no hay tarjetas en {opciones.carpeta}")
        estado = almacen.vacio()
        for t in tarjetas:
            datos = {k: v for k, v in t.items() if k != "id"}
            estado["tarjetas"][t["id"]] = {**datos, "detalle": [ocultar(str(x)) for x in datos["detalle"]]}
        estado["parte_fecha"] = max(t["ultima_vez"] for t in tarjetas)
        almacen.guardar(ARCHIVO, estado)
    columnas = {c: n for c in ORDEN_COLUMNAS if (n := sum(t["columna"] == c for t in tarjetas))}
    _imprimir({"importadas": len(tarjetas), "columnas": columnas, "archivo": str(ARCHIVO)})
    return 0


def _argumentos() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="narrador tablero", description="Tablero de hallazgos del parte, guardado en un archivo local de este equipo.")
    sub = ap.add_subparsers(dest="orden", required=True)

    def con_parte(p: argparse.ArgumentParser) -> None:
        p.add_argument("--fecha", help="fecha del JSON de narrador parte recién generado; si el parte leído es de otra, no se mueve nada")
        p.add_argument("--parte", type=Path, help="JSON del parte (por defecto, el último completo)")

    def manual(p: argparse.ArgumentParser) -> None:
        p.add_argument("--origen", required=True, choices=ORIGENES_MANUALES, help="quién lo pide: el mod o Ío por voz")
        p.add_argument("--hoy", help=argparse.SUPPRESS)  # para pruebas

    p = sub.add_parser("ver", help="enseña el tablero")
    p.add_argument("--json", action="store_true")
    p.set_defaults(hacer=_cmd_ver)
    for nombre, ayuda in (("plan", "simula el cruce con el parte, sin escribir"), ("semilla", "simula la carga inicial, sin escribir")):
        p = sub.add_parser(nombre, help=ayuda)
        con_parte(p)
        p.set_defaults(hacer=_cmd_plan)
    p = sub.add_parser("aplicar", help="cruza el parte con el tablero y guarda los cambios")
    con_parte(p)
    p.add_argument("--crear", action="store_true", help="estrena el tablero si aún no hay archivo")
    p.set_defaults(hacer=_cmd_aplicar)
    p = sub.add_parser("mover", help="mueve una tarjeta de columna")
    p.add_argument("id")
    p.add_argument("columna", choices=ORDEN_COLUMNAS)
    p.add_argument("--desde", choices=ORDEN_COLUMNAS, help="columna en la que se vio la tarjeta; si ya no está ahí, no se mueve (código 4)")
    manual(p)
    p.set_defaults(hacer=_cmd_mover)
    p = sub.add_parser("deshacer", help="devuelve el último movimiento manual a su columna anterior")
    manual(p)
    p.set_defaults(hacer=_cmd_deshacer)
    p = sub.add_parser("importar", help="crea el tablero a partir de la carpeta exportada de la página web")
    p.add_argument("carpeta", type=Path)
    p.set_defaults(hacer=_cmd_importar)
    return ap


def main(args: list[str]) -> int:
    """0 bien · 1 no hay tal tarjeta o nada que hacer · 3 archivo o parte ilegible · 4 la tarjeta cambió de columna · 5 otro proceso está escribiendo."""
    opciones = _argumentos().parse_args(args)
    try:
        return opciones.hacer(opciones)
    except almacen.CerrojoOcupado as e:
        print(f"tablero: {e}", file=sys.stderr)
        return 5
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"tablero: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
