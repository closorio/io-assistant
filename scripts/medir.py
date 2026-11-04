"""Coste de una sesión de Claude Code, leído de su transcript. Solo imprime números: nunca contenido.

El coste es una estimación a precio de lista (`precios_claude.json`), no una factura. Sirve para
comparar formas de trabajar, sin tener que abrir cada sesión. Reparte por tarea de forma burda: cada
mensaje va a la siguiente tarea con commit en el repositorio.
"""

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from comun import PROYECTOS_CLAUDE

PRECIOS = Path(__file__).with_name("precios_claude.json")
TAREA = re.compile(r"(?<![A-Za-z0-9])t\d{2,3}(?![A-Za-z0-9])")


def cargar_precios() -> dict:
    return json.loads(PRECIOS.read_text(encoding="utf-8"))


def buscar(sesion: str) -> Path:
    hallados = sorted(p for p in PROYECTOS_CLAUDE.glob(f"*/{sesion}*.jsonl"))
    if len(hallados) != 1:
        raise SystemExit(f"la sesión «{sesion}» coincide con {len(hallados)} transcripts; hace falta uno")
    return hallados[0]


def _lineas(ruta: Path):
    with open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            try:
                dato = json.loads(linea)
            except ValueError:
                continue
            if isinstance(dato, dict):
                yield dato


def _mensajes(ruta: Path) -> dict:
    """id → (uso, fecha, modelo). El transcript repite un mensaje por cada bloque: cuenta una vez."""
    vistos = {}
    for d in _lineas(ruta):
        m = d.get("message")
        if isinstance(m, dict) and m.get("id") and isinstance(m.get("usage"), dict) and m.get("model") != "<synthetic>":
            vistos[m["id"]] = (m["usage"], d.get("timestamp") or "", m.get("model") or "?")
    return vistos


def _tokens(uso: dict) -> dict:
    detalle = uso.get("cache_creation") or {}
    if "ephemeral_5m_input_tokens" in detalle or "ephemeral_1h_input_tokens" in detalle:
        c5, c1 = detalle.get("ephemeral_5m_input_tokens") or 0, detalle.get("ephemeral_1h_input_tokens") or 0
    else:
        c5, c1 = uso.get("cache_creation_input_tokens") or 0, 0
    return {"entrada": uso.get("input_tokens") or 0, "cache_5m": c5, "cache_1h": c1,
            "cache_lectura": uso.get("cache_read_input_tokens") or 0, "salida": uso.get("output_tokens") or 0}


def _coste(tokens: dict, modelo: str, precios: dict) -> float | None:
    tarifa = precios["modelos"].get(modelo)
    return None if tarifa is None else sum(tokens[k] * tarifa[k] for k in tokens) / 1_000_000


def _sumar(mensajes: dict, precios: dict) -> tuple[dict, set]:
    total, por_modelo, por_dia, sin_precio = Counter(), Counter(), Counter(), set()
    coste = 0.0
    for uso, fecha, modelo in mensajes.values():
        t = _tokens(uso)
        total.update(t)
        c = _coste(t, modelo, precios)
        if c is None:
            sin_precio.add(modelo)
            continue
        coste += c
        por_modelo[modelo] += c
        por_dia[fecha[:10]] += c
    return {"mensajes": len(mensajes), "tokens": dict(total) or {k: 0 for k in ("entrada", "cache_5m", "cache_1h", "cache_lectura", "salida")},
            "coste": round(coste, 2), "por_modelo": {k: round(v, 2) for k, v in por_modelo.items()},
            "por_dia": {k: round(v, 2) for k, v in sorted(por_dia.items())}}, sin_precio


def _archivos_subagentes(ruta: Path) -> list[Path]:
    return sorted((ruta.parent / ruta.stem / "subagents").glob("*.jsonl"))


def resumen(ruta: Path, precios: dict | None = None) -> dict:
    precios = precios or cargar_precios()
    principal, sp1 = _sumar(_mensajes(ruta), precios)
    subs = {}
    archivos = _archivos_subagentes(ruta)
    for a in archivos:
        subs.update(_mensajes(a))
    subagentes, sp2 = _sumar(subs, precios)
    subagentes["archivos"] = len(archivos)
    compactas = [d["compactMetadata"] for d in _lineas(ruta)
                 if d.get("subtype") == "compact_boundary" and isinstance(d.get("compactMetadata"), dict)]
    return {"sesion": ruta.stem, "precios": precios["fecha"], "principal": principal, "subagentes": subagentes,
            "coste_total": round(principal["coste"] + subagentes["coste"], 2), "sin_precio": sorted(sp1 | sp2),
            "compactaciones": {"manuales": sum(c.get("trigger") == "manual" for c in compactas),
                               "automaticas": sum(c.get("trigger") == "auto" for c in compactas),
                               "tokens_antes": [c.get("preTokens") for c in compactas]}}


def tarea_de(asunto: str) -> str | None:
    hallada = TAREA.search(asunto)
    return hallada.group(0) if hallada else None


def commits_con_tarea(repo: str) -> list[tuple[str, str]]:
    salida = subprocess.run(["git", "-C", repo, "log", "--all", "--format=%cI%x09%s"], capture_output=True, text=True,
                            check=True).stdout
    filas = (linea.split("\t", 1) for linea in salida.splitlines() if "\t" in linea)
    return [(fecha, t) for fecha, asunto in filas if (t := tarea_de(asunto))]


def _instante(fecha: str) -> datetime:
    return datetime.fromisoformat(fecha.replace("Z", "+00:00"))


def por_tarea(ruta: Path, commits: list[tuple[str, str]], precios: dict | None = None) -> dict:
    precios = precios or cargar_precios()
    orden = sorted((_instante(f), t) for f, t in commits)
    mensajes = _mensajes(ruta)
    for a in _archivos_subagentes(ruta):
        mensajes.update(_mensajes(a))
    tareas, sin_asignar = Counter(), 0.0
    for uso, fecha, modelo in mensajes.values():
        c = _coste(_tokens(uso), modelo, precios)
        if c is None or not fecha:
            continue
        cuando = _instante(fecha)
        destino = next((t for f, t in orden if f >= cuando), None)
        if destino:
            tareas[destino] += c
        else:
            sin_asignar += c
    return {"tareas": {k: round(v, 2) for k, v in sorted(tareas.items())}, "sin_asignar": round(sin_asignar, 2)}


def imprimir(r: dict) -> None:
    print(f"sesión {r['sesion'][:8]}: ≈ {r['coste_total']} $ a precio de lista ({r['precios']}); no es una factura")
    for nombre in ("principal", "subagentes"):
        p = r[nombre]
        print(f"  {nombre}: ≈ {p['coste']} $ · {p['mensajes']} mensajes · {p['tokens']['salida']} de salida · "
              f"{p['tokens']['cache_lectura']} leídos de caché · {p['tokens']['cache_5m'] + p['tokens']['cache_1h']} escritos en caché")
    c = r["compactaciones"]
    print(f"  compactaciones: {c['manuales']} manuales, {c['automaticas']} automáticas; tokens antes: {c['tokens_antes']}")
    if r["sin_precio"]:
        print(f"  ojo, sin precio (no suman coste): {', '.join(r['sin_precio'])}")


def main(args: list[str]) -> int:
    if not args or args[0].startswith("-"):
        raise SystemExit("uso: narrador medir SESIÓN [--json] [--por-tarea REPO]")
    ruta = buscar(args[0])
    r = resumen(ruta)
    if "--por-tarea" in args:
        r["por_tarea"] = por_tarea(ruta, commits_con_tarea(args[args.index("--por-tarea") + 1]))
    if "--json" in args:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        imprimir(r)
        for t, c in r.get("por_tarea", {}).get("tareas", {}).items():
            print(f"  {t}: ≈ {c} $")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
