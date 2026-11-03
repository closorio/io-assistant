"""Tablero de hallazgos del parte: compara el parte con las tarjetas y decide los cambios.

Lógica pura, sin red ni .env. Quien lee y escribe las tarjetas es Ío, con ArtifactData.
Reglas: docs/superpowers/specs/2026-11-03-tablero-hallazgos-design.md
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parte_matinal import NOMBRE_CHECK  # noqa: E402

MAX_HISTORIAL = 20
MAX_TEXTO = 200
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
