"""Tablero de hallazgos del parte: compara el parte con las tarjetas y decide los cambios.

Lógica pura, sin red ni .env. Quien lee y escribe las tarjetas es Ío, con ArtifactData.
Reglas: docs/superpowers/specs/2026-11-03-tablero-hallazgos-design.md
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parte_matinal import NOMBRE_CHECK, PARTES  # noqa: E402

MAX_HISTORIAL = 20
MAX_TEXTO = 200
MAX_LOTE = 50
COLUMNAS = {"nuevos", "en_curso", "dejados", "resueltos"}
PARTE_COMPLETO = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
ESTIMADOS = {"openai_saldo"}
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
    situacion = "anomalia" if nivel else "sin_comprobar" if estados & {"na", "error"} else "verde"
    valores = [ocultar(r.get("valor") or r.get("detalle") or r["estado"]) for r in propios if r["estado"] in ("rojo", "ambar")]
    return {"ambito": ambito, "check": check, "situacion": situacion, "nivel": nivel, "valores": valores}


def _mover(tarjeta: dict, a: str, marca: str, hoy: str) -> dict:
    linea = {"fecha": hoy, "de": tarjeta["columna"], "a": a, "origen": "parte"}
    return {"columna": a, "marca": marca, "historial": [*tarjeta.get("historial", []), linea][-MAX_HISTORIAL:]}


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
        return _mover(tarjeta, "resueltos", "automatica", hoy) if columna != "resueltos" else None
    cambios = _distintos(tarjeta, {"nivel": grupo["nivel"], "detalle": grupo["valores"], "ultima_vez": hoy})
    if columna == "resueltos":
        cambios |= _mover(tarjeta, "nuevos", "reabierta", hoy)
    elif columna == "dejados" and tarjeta.get("nivel") == "ambar" and grupo["nivel"] == "rojo":
        cambios |= _mover(tarjeta, "nuevos", "empeorada", hoy)
    return cambios or None


def leer_tarjetas(directorio: Path, versiones: dict[str, int]) -> tuple[list[dict], set[str], list[str]]:
    """Tarjetas válidas, ids inválidos (que el plan no debe tocar) y avisos. Sin carpeta lanza FileNotFoundError.

    Los archivos de ArtifactData con out_dir solo traen el cuerpo: el id es el nombre del archivo y la
    versión viene del listado que devuelve esa misma lectura.
    """
    tarjetas, invalidas = [], set()
    archivos = {a.stem: a for a in Path(directorio).iterdir() if a.suffix == ".json"}
    for id_ in sorted(archivos.keys() | versiones.keys()):
        try:
            datos = json.loads(archivos[id_].read_text(encoding="utf-8"))
            valida = datos.get("columna") in COLUMNAS and isinstance(versiones.get(id_), int)
        except (KeyError, ValueError, AttributeError):
            valida = False
        if valida:
            tarjetas.append({**datos, "id": id_, "version": versiones[id_]})
        else:
            invalidas.add(id_)
    return tarjetas, invalidas, [f"tarjeta {id_} ignorada: documento no válido" for id_ in sorted(invalidas)]


def _escritura(id_: str, cambios: dict, tarjeta: dict | None) -> dict:
    if tarjeta is None:
        return {"op": "set", "collection": "tarjetas", "doc_id": id_, "data": cambios}
    return {"op": "update", "collection": "tarjetas", "doc_id": id_, "data": cambios, "if_version": tarjeta["version"]}


def _activa(tarjeta: dict, hoy: str) -> dict:
    return {
        "id": tarjeta["id"], "cliente": tarjeta.get("cliente", "global"), "titulo": tarjeta.get("titulo", tarjeta.get("check", "")),
        "nivel": tarjeta.get("nivel"), "valores": tarjeta.get("detalle", []), "fiabilidad": tarjeta.get("fiabilidad", "comprobado"),
        "marca": tarjeta.get("marca"), "dias": (date.fromisoformat(hoy) - date.fromisoformat(tarjeta.get("primera_vez", hoy))).days,
    }


def planificar(parte: dict, tarjetas: list[dict], *, modo: str = "plan", ignorar: set[str] = frozenset()) -> dict:
    hoy = parte["compacto"]["fecha"]
    resultados = parte["resultados"]
    nombres = parte.get("tenants", {})
    por_id = {t["id"]: t for t in tarjetas}
    avisos, escrituras = [], []
    if any(t.get("ultima_vez", "") > hoy for t in tarjetas):
        avisos.append(f"parte antiguo ({hoy}): hay tarjetas más recientes, no se mueve nada")
    else:
        for (ambito, check), grupo in agrupar(resultados).items():
            id_ = id_tarjeta(ambito, check)
            if id_ in ignorar:
                continue
            tarjeta = por_id.get(id_)
            cambios = decidir(grupo, tarjeta, parcial=bool(parte.get("parcial")), hoy=hoy, modo=modo, cliente=nombres.get(ambito, "global"))
            if cambios:
                escrituras.append(_escritura(id_, cambios, tarjeta))
                por_id[id_] = {**(tarjeta or {}), **cambios, "id": id_}
    activas = [t for t in por_id.values() if t.get("columna") in ("nuevos", "en_curso")]
    niveles = {t.get("nivel") for t in activas}
    orden = sorted(activas, key=lambda t: (t.get("nivel") != "rojo", t.get("primera_vez", hoy)))
    return {
        "fecha": hoy,
        "fiable": not avisos and not ignorar,
        "lotes": [escrituras[i:i + MAX_LOTE] for i in range(0, len(escrituras), MAX_LOTE)],
        "semaforo": "rojo" if "rojo" in niveles else "ambar" if "ambar" in niveles else "verde",
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


def main(args: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="narrador tablero", description="Calcula los cambios del tablero de hallazgos a partir del parte. No escribe nada.")
    ap.add_argument("modo", choices=["plan", "semilla"])
    ap.add_argument("--tarjetas", required=True, type=Path, help="carpeta con las tarjetas guardadas por ArtifactData list con out_dir")
    ap.add_argument("--versiones", required=True, help='JSON {id: version} del listado de esa misma lectura; {} si no hay tarjetas')
    ap.add_argument("--parte", type=Path, help="JSON del parte (por defecto, el último completo)")
    opciones = ap.parse_args(args)
    try:
        ruta = opciones.parte or ultimo_parte(PARTES)
        parte = json.loads(ruta.read_text(encoding="utf-8"))
        tarjetas, invalidas, avisos = leer_tarjetas(opciones.tarjetas, json.loads(opciones.versiones))
        plan = planificar(parte, tarjetas, modo=opciones.modo, ignorar=invalidas)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"tablero: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    plan["avisos"] = avisos + plan["avisos"]
    print(json.dumps(plan, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
