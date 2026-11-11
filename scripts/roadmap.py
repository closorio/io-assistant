"""Seguimiento del roadmap por proyecto: lee el vault conocimiento/ de cada proyecto y su git.

  narrador roadmap [--json] [PROYECTO | RUTA | --activo]

--activo elige el proyecto de tu sesión interactiva de Claude Code con actividad más reciente
(ni Ío ni trabajadores): sube desde su carpeta hasta encontrar conocimiento/roadmap/.

Cada proyecto lleva en su raíz un vault <proyecto>/conocimiento/ con notas roadmap/*.md
(frontmatter: tipo: roadmap, fase, estado, responsable, inicio, objetivo, hitos_total,
hitos_hechos, cerrado, actualizado, siguiente). Por proyecto separa:

  medido    avance (hitos hechos/total), deriva frente a la fecha objetivo, cierres de fase,
            commits de las últimas 4 semanas, último movimiento, días sin tocar, responsable
            y siguiente paso: datos tal cual están en las notas y en git.
  estimado  fecha prevista para los hitos que faltan al ritmo real (hitos hechos por semana
            desde el inicio, corregido por la actividad de las últimas 4 semanas frente a la
            media), con su confianza y por qué; dice «pocos datos» cuando los hay.

Segunda fuente, para proyectos con una sola hoja de ruta: un archivo .md (ruta relativa a la
raíz en "roadmap_md") con una tabla bajo «## Rumbo vigente (DD-MM-AAAA)» de columnas
| # | Acción | Dueño | Hecho cuando | Tope | Puertas |. Cada fila cuenta como una fase de un hito:
hecha si el título de la Acción (su negrita inicial) o «Hecho cuando» llevan ✅ o «hecha»;
aparcada si dicen «congelad» o «aparcad»; las de «al final» van detrás. El siguiente paso es
la primera fila abierta. La fecha del encabezado es la de actualización; la fecha objetivo
solo si una celda dice «objetivo … DD-MM». El archivo solo se lee.

Sin fecha objetivo escrita no hay deriva: se dice «sin fecha objetivo», nunca se inventa.
Solo lectura, solo biblioteca estándar. La lista de proyectos se cambia con
~/.local/share/narrador/roadmap.json:
  {"proyectos": [{"nombre": "...", "ruta": "...", "roadmap_md": "conocimiento/60-backlog/roadmap.md"}]}
("roadmap_md" es opcional; sin ella se leen las notas de conocimiento/roadmap/).
"""

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from comun import RUNTIME

DOCS = Path.home() / "Documentos"
PROYECTOS_DEFECTO = [
    {"nombre": "project-soma", "ruta": str(DOCS / "thereisnospoon" / "project-soma")},
    {"nombre": "holo-ui", "ruta": str(DOCS / "thereisnospoon" / "holo-ui")},
    {"nombre": "vindam_dashboard_engine",
     "ruta": str(DOCS / "greedisgood" / "vindam platform" / "vindam_dashboard_engine"),
     "roadmap_md": "conocimiento/60-backlog/roadmap.md"},
]
CONFIG = RUNTIME / "roadmap.json"
VENTANA = 28  # días: «las últimas 4 semanas»
ESTADOS = {"hecho": "hecho", "hecha": "hecho", "cerrado": "hecho", "cerrada": "hecho",
           "en-curso": "en-curso", "en curso": "en-curso", "encurso": "en-curso",
           "aparcado": "aparcado", "aparcada": "aparcado", "pausa": "aparcado",
           "pendiente": "pendiente"}
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CASILLA = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s*(.*)$")


# --- lectura de notas -------------------------------------------------------------------

def _valor(texto: str):
    t = texto.strip()
    if not t:
        return ""
    if t[0] in "\"'" and t[-1] == t[0] and len(t) >= 2:
        return t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        return [_valor(x) for x in t[1:-1].split(",") if x.strip()]
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    return t


def frontmatter(texto: str) -> tuple[dict, str]:
    """Frontmatter YAML plano (clave: valor), el que escriben las plantillas del vault."""
    if not texto.startswith("---"):
        return {}, texto
    lineas = texto.split("\n")
    for i in range(1, len(lineas)):
        if lineas[i].strip() == "---":
            datos = {}
            for linea in lineas[1:i]:
                m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", linea)
                if m:
                    datos[m.group(1)] = _valor(m.group(2))
            return datos, "\n".join(lineas[i + 1:])
    return {}, texto


def _fecha(valor) -> date | None:
    if isinstance(valor, str) and FECHA.match(valor.strip()):
        try:
            return date.fromisoformat(valor.strip())
        except ValueError:
            return None
    return None


def _entero(valor) -> int | None:
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and re.fullmatch(r"\d+", valor.strip()):
        return int(valor)
    return None


def casillas(cuerpo: str) -> tuple[int, int]:
    """(hechas, total) de las casillas de la sección «Hitos»; las «(opcional)» no cuentan."""
    hechas = total = 0
    dentro = False
    for linea in cuerpo.split("\n"):
        if linea.startswith("#"):
            dentro = linea.lstrip("#").strip().lower() == "hitos"
            continue
        m = CASILLA.match(linea) if dentro else None
        if not m or not m.group(2).strip() or "(opcional)" in m.group(2).lower():
            continue
        total += 1
        hechas += m.group(1).lower() == "x"
    return hechas, total


def pendientes(cuerpo: str, maximo: int = 6) -> list[str]:
    """Textos de las casillas sin marcar de la sección «Hitos», en orden."""
    salida, dentro = [], False
    for linea in cuerpo.split("\n"):
        if linea.startswith("#"):
            dentro = linea.lstrip("#").strip().lower() == "hitos"
            continue
        m = CASILLA.match(linea) if dentro else None
        if m and m.group(1) == " " and m.group(2).strip():
            salida.append(m.group(2).strip())
            if len(salida) >= maximo:
                break
    return salida


def leer_nota(ruta: Path) -> dict | None:
    try:
        datos, cuerpo = frontmatter(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    if datos.get("tipo") != "roadmap":
        return None
    avisos = []
    estado_crudo = str(datos.get("estado", "")).strip().lower()
    estado = ESTADOS.get(estado_crudo, "pendiente")
    if estado_crudo and estado_crudo not in ESTADOS:
        avisos.append(f"estado desconocido «{estado_crudo}»")
    hechas, total_c = casillas(cuerpo)
    total = _entero(datos.get("hitos_total"))
    hechos = _entero(datos.get("hitos_hechos"))
    if not total and total_c:
        total, hechos = total_c, hechas
    total, hechos = total or 0, hechos or 0
    if total_c and (total, hechos) != (total_c, hechas):
        avisos.append(f"frontmatter {hechos}/{total} y casillas {hechas}/{total_c} no cuadran")
    if hechos > total:
        avisos.append(f"más hitos hechos ({hechos}) que en total ({total})")
        hechos = total
    cerrado = _fecha(datos.get("cerrado"))
    if estado == "hecho" and not cerrado:
        avisos.append("hecha sin fecha de cierre")
    for clave in ("inicio", "objetivo", "cerrado", "actualizado"):
        v = datos.get(clave)
        if v not in (None, "") and not _fecha(v):
            avisos.append(f"{clave} no es una fecha AAAA-MM-DD: «{v}»")
    responsable = datos.get("responsable", "")
    if isinstance(responsable, list):
        responsable = ", ".join(map(str, responsable))
    return {
        "nota": ruta.stem,
        "fase": str(datos.get("fase", "")),
        "estado": estado,
        "responsable": str(responsable),
        "inicio": _fecha(datos.get("inicio")),
        "objetivo": _fecha(datos.get("objetivo")),
        "cerrado": cerrado,
        "actualizado": _fecha(datos.get("actualizado")),
        "hitos_total": total,
        "hitos_hechos": hechos,
        "siguiente": str(datos.get("siguiente", "")),
        "pendientes": pendientes(cuerpo),
        "avisos": avisos,
    }


# --- tabla «Rumbo vigente» de un archivo único ------------------------------------------

RUMBO = re.compile(r"^(#{1,6})\s+Rumbo vigente\b(.*)$", re.IGNORECASE)
HECHA = re.compile(r"✅|\bhecha\b", re.IGNORECASE)
APARCADA = re.compile(r"congelad|aparcad", re.IGNORECASE)
AL_FINAL = re.compile(r"\bal final\b", re.IGNORECASE)
DIA = r"(\d{4}-\d{2}-\d{2}|\b\d{1,2}-\d{1,2}(?:-\d{4})?\b)"
CIERRE = re.compile(r"(?:✅|\bhecha\b)[^|]{0,15}?" + DIA, re.IGNORECASE)
OBJETIVO = re.compile(r"\bobjetivo\b[^;|]{0,40}?" + DIA, re.IGNORECASE)
VACIA = {"", "—", "–", "-"}
COLUMNAS = {"#": "numero", "accion": "accion", "dueno": "dueno", "hecho cuando": "hecho_cuando",
            "tope": "tope", "puertas": "puertas"}


def celdas(linea: str) -> list[str]:
    """Celdas de una fila de tabla; no corta en «|» dentro de `código`, [[enlace|alias]] o «\\|»."""
    t = linea.strip()
    t = t[1:] if t.startswith("|") else t
    t = t[:-1] if t.endswith("|") and not t.endswith("\\|") else t
    salida, actual, codigo, enlace, i = [], "", False, 0, 0
    while i < len(t):
        c = t[i]
        if c == "\\" and t[i + 1:i + 2] == "|":
            actual += "|"
            i += 2
            continue
        if c == "`":
            codigo = not codigo
        elif not codigo and t[i:i + 2] == "[[":
            enlace += 1
        elif not codigo and t[i:i + 2] == "]]" and enlace:
            enlace -= 1
        if c == "|" and not codigo and not enlace:
            salida.append(actual.strip())
            actual = ""
        else:
            actual += c
        i += 1
    salida.append(actual.strip())
    return salida


def _limpiar(texto: str) -> str:
    t = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", texto)
    t = re.sub(r"\[\[([^\]]*)\]\]", lambda m: m.group(1).rsplit("/", 1)[-1], t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = t.replace("`", "").replace("**", "").replace("__", "").replace("✅", "")
    t = re.sub(r"~~[^~]*~~", "", t)
    for _ in range(3):  # paréntesis, también anidados
        t = re.sub(r"\s*\([^()]*\)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _titulo(celda: str) -> str:
    """La negrita inicial de la celda, o la primera frase si no empieza en negrita."""
    t = celda.strip()
    if t.startswith("**"):
        fin = t.find("**", 2)
        if fin > 2:
            return t[2:fin]
    return re.split(r"(?<=[.;])\s", t, maxsplit=1)[0]


def resumir(celda: str, maximo: int = 90) -> str:
    """Una frase corta y sin markdown a partir de una celda larga."""
    t = _limpiar(_titulo(celda)).rstrip(" :;,.")
    if len(t) > maximo:
        t = t[:maximo - 1].rsplit(" ", 1)[0].rstrip(" :;,.") + "…"
    return t


def _dia(texto: str, base: date | None) -> date | None:
    """AAAA-MM-DD o DD-MM[-AAAA]; sin año toma el de la fecha base (o el siguiente si queda muy atrás)."""
    if FECHA.match(texto):
        return _fecha(texto)
    partes = [int(x) for x in texto.split("-")]
    anio = partes[2] if len(partes) == 3 else (base or date.today()).year
    try:
        d = date(anio, partes[1], partes[0])
    except ValueError:
        return None
    if len(partes) == 2 and base and d < base - timedelta(days=180):
        d = d.replace(year=d.year + 1)
    return d


def _duenos(celda: str) -> str:
    """«Sesión, lo hecho; usuario, el push» → «Sesión, Usuario»: el actor de cada tramo."""
    vistos = []
    for tramo in _limpiar(celda).split(";"):
        actor = tramo.split(",")[0].strip()
        actor = actor[:1].upper() + actor[1:]
        if actor and actor not in VACIA and actor not in vistos:
            vistos.append(actor)
    return ", ".join(vistos)


def _normal(cabecera: str) -> str:
    t = _limpiar(cabecera).lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return t


def leer_rumbo(ruta: Path) -> tuple[list[dict], date | None, str]:
    """(filas como notas, fecha del encabezado, error) de la tabla «Rumbo vigente»."""
    try:
        lineas = ruta.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError) as e:
        return [], None, f"no se pudo leer {ruta}: {e}"
    inicio = next((i for i, l in enumerate(lineas) if RUMBO.match(l)), None)
    if inicio is None:
        return [], None, f"la hoja de ruta no tiene tabla «Rumbo vigente»: {ruta}"
    nivel, resto = RUMBO.match(lineas[inicio]).groups()
    m = re.search(DIA, resto)
    fecha = _dia(m.group(1), None) if m and m.group(1).count("-") == 2 else None
    tabla: list[str] = []
    for linea in lineas[inicio + 1:]:
        cab = re.match(r"^(#{1,6})\s", linea)
        if cab and len(cab.group(1)) <= len(nivel):
            break
        if linea.lstrip().startswith("|"):
            tabla.append(linea)
        elif tabla:
            break
    if len(tabla) < 2:
        return [], fecha, f"la hoja de ruta no tiene tabla «Rumbo vigente»: {ruta}"
    claves = [COLUMNAS.get(_normal(c), "") for c in celdas(tabla[0])]
    if "accion" not in claves:
        return [], fecha, f"la tabla «Rumbo vigente» no tiene columna «Acción»: {ruta}"
    filas, al_final = [], []
    for linea in tabla[1:]:
        valores = celdas(linea)
        if all(re.fullmatch(r":?-{2,}:?", v or "--") for v in valores):
            continue
        f = {k: v for k, v in zip(claves, valores) if k}
        accion, hc = f.get("accion", ""), f.get("hecho_cuando", "")
        if not accion.strip():
            continue
        titulo = _titulo(accion)
        marcas = titulo + " | " + hc
        estado = ("hecho" if HECHA.search(marcas) else
                  "aparcado" if APARCADA.search(marcas) else "pendiente")
        cierre = CIERRE.search(marcas) if estado == "hecho" else None
        objetivo = next((d for v in valores if (o := OBJETIVO.search(v)) and (d := _dia(o.group(1), fecha))), None)
        numero = f.get("numero", "").strip() or str(len(filas) + len(al_final) + 1)
        fase = resumir(accion)
        fila = {
            "nota": f"{numero}. {fase}",
            "numero": numero,
            "fase": fase,
            "estado": estado,
            "responsable": _duenos(f.get("dueno", "")),
            "inicio": None,
            "objetivo": objetivo,
            "cerrado": _dia(cierre.group(1), fecha) if cierre else None,
            "actualizado": fecha,
            "hitos_total": 1,
            "hitos_hechos": int(estado == "hecho"),
            "siguiente": "",
            "pendientes": ([f"hecho cuando: {resumir(hc, 110)}"]
                           if estado != "hecho" and _limpiar(hc) not in VACIA else []),
            "tope": "" if _limpiar(f.get("tope", "")) in VACIA else resumir(f.get("tope", "")),
            "puertas": "" if _limpiar(f.get("puertas", "")) in VACIA else resumir(f.get("puertas", ""), 110),
            "avisos": [],
        }
        (al_final if AL_FINAL.search(marcas) else filas).append(fila)
    filas += al_final
    sig = next((n for n in filas if n["estado"] == "pendiente"), None)
    if sig:
        sig["siguiente"] = sig["fase"]
    if not filas:
        return [], fecha, f"la tabla «Rumbo vigente» no tiene filas: {ruta}"
    return filas, fecha, ""


# --- git (solo lectura) -----------------------------------------------------------------

def _git(ruta: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ruta), *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def datos_git(ruta: Path, hoy: date) -> dict | None:
    if _git(ruta, "rev-parse", "--git-dir") is None:
        return None
    desde = (hoy - timedelta(days=VENTANA)).isoformat()
    recientes = _git(ruta, "rev-list", "--count", "--all", "--no-merges", f"--since={desde}")
    total = _git(ruta, "rev-list", "--count", "--all", "--no-merges")
    raices = _git(ruta, "log", "--all", "--max-parents=0", "--format=%cs") or ""
    ultimo = _git(ruta, "log", "-1", "--all", "--format=%cs%x09%s") or ""
    fecha_u, _, asunto = ultimo.partition("\t")
    primeros = sorted(f for f in raices.split("\n") if FECHA.match(f))
    sucio = _git(ruta, "status", "--porcelain", "--untracked-files=no")
    return {
        "cambios_sin_commit": len([x for x in sucio.split("\n") if x.strip()]) if sucio is not None else None,
        "commits_4_semanas": int(recientes) if recientes and recientes.isdigit() else 0,
        "commits_total": int(total) if total and total.isdigit() else 0,
        "primer_commit": _fecha(primeros[0]) if primeros else None,
        "ultimo_commit": _fecha(fecha_u),
        "ultimo_asunto": asunto[:140],
    }


# --- cálculo ----------------------------------------------------------------------------

def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def semaforo_de(deriva: int | None, desfase_estimado: int | None, hay_objetivo: bool) -> str:
    """rojo: objetivo pasado > 7 días · ámbar: pasado ≤ 7 días o la previsión lo supera · verde."""
    if not hay_objetivo:
        return "sin_objetivo"
    if deriva is not None and deriva > 7:
        return "rojo"
    if (deriva is not None and deriva > 0) or (desfase_estimado is not None and desfase_estimado > 0):
        return "ambar"
    return "verde"


def calcular(nombre: str, ruta: Path, notas: list[dict], git: dict | None, hoy: date) -> dict:
    total = sum(n["hitos_total"] for n in notas)
    hechos = sum(n["hitos_hechos"] for n in notas)
    abiertas = [n for n in notas if n["estado"] != "hecho"]
    fases = {e: sum(n["estado"] == e for n in notas) for e in ("hecho", "en-curso", "pendiente", "aparcado")}
    limite = hoy - timedelta(days=VENTANA)
    cierres = sorted((n for n in notas if n["cerrado"] and n["cerrado"] >= limite),
                     key=lambda n: n["cerrado"], reverse=True)

    # Deriva medida: días que una fase abierta lleva pasada de su fecha objetivo.
    vencidas = [((hoy - n["objetivo"]).days, n) for n in abiertas if n["objetivo"] and n["objetivo"] < hoy]
    deriva, deriva_nota = (max(vencidas, key=lambda x: x[0]) if vencidas else (None, None))
    con_objetivo = [n for n in abiertas if n["objetivo"]]
    objetivo = max((n["objetivo"] for n in con_objetivo), default=None)
    cerradas_tarde = [((n["cerrado"] - n["objetivo"]).days, n["nota"]) for n in notas
                      if n["estado"] == "hecho" and n["cerrado"] and n["objetivo"]]

    en_curso = sorted((n for n in notas if n["estado"] == "en-curso"),
                      key=lambda n: n["actualizado"] or date.min, reverse=True)
    candidatas = en_curso + [n for n in notas if n["estado"] == "pendiente"]
    sig = next((n for n in candidatas if n["siguiente"].strip()), None)
    responsables = sorted({r.strip() for n in (en_curso or abiertas) for r in n["responsable"].split(",") if r.strip()})

    ultimo = git["ultimo_commit"] if git else None
    ultima_nota = max((n["actualizado"] for n in notas if n["actualizado"]), default=None)
    medido = {
        "hitos_hechos": hechos,
        "hitos_total": total,
        "avance_pct": round(100 * hechos / total) if total else None,
        "fases": fases,
        "fases_total": len(notas),
        "deriva_dias": deriva,
        "deriva_fase": deriva_nota["nota"] if deriva_nota else None,
        "fecha_objetivo": _iso(objetivo),
        "fases_con_objetivo": len(con_objetivo),
        "cierres_con_desfase": [{"nota": nota, "dias": d} for d, nota in cerradas_tarde],
        "cierres_4_semanas": [{"nota": n["nota"], "cerrado": _iso(n["cerrado"])} for n in cierres],
        "commits_4_semanas": git["commits_4_semanas"] if git else None,
        "commits_total": git["commits_total"] if git else None,
        "ultimo_movimiento": _iso(ultimo),
        "ultimo_movimiento_texto": git["ultimo_asunto"] if git else "",
        "dias_sin_tocar": (hoy - ultimo).days if ultimo else None,
        "cambios_sin_commit": git.get("cambios_sin_commit") if git else None,
        "ultima_nota_actualizada": _iso(ultima_nota),
        "responsable": ", ".join(responsables),
        "siguiente": sig["siguiente"] if sig else "",
        "siguiente_fase": sig["nota"] if sig else "",
    }
    estimado = estimar(notas, hechos, total, git, hoy, objetivo)
    sem = semaforo_de(deriva, estimado["desfase_dias"], objetivo is not None or deriva is not None)
    if deriva is not None and deriva > 0:
        texto = f"{deriva} días tarde ({deriva_nota['nota']})"
    elif objetivo is None:
        texto = "sin fecha objetivo"
    elif estimado["desfase_dias"] is not None and estimado["desfase_dias"] > 0:
        texto = f"en fecha, pero la previsión se pasa {estimado['desfase_dias']} días"
    else:
        texto = f"en fecha (objetivo {objetivo.isoformat()})"
    avisos = [f"{n['nota']}: {a}" for n in notas for a in n["avisos"]]
    return {
        "nombre": nombre,
        "ruta": str(ruta),
        "vault": str(ruta / "conocimiento"),
        "error": "",
        "semaforo": sem,
        "deriva_texto": texto,
        "medido": medido,
        "estimado": estimado,
        "avisos": avisos,
        "notas": [{**{k: v for k, v in n.items() if k != "avisos"},
                   **{k: _iso(n[k]) for k in ("inicio", "objetivo", "cerrado", "actualizado")}} for n in notas],
    }


def estimar(notas: list[dict], hechos: int, total: int, git: dict | None, hoy: date,
            objetivo: date | None) -> dict:
    """Fecha prevista para los hitos que faltan. Ritmo = hitos hechos por semana desde el
    inicio, por la actividad reciente (commits de 4 semanas frente a la media del repo)."""
    restantes = max(total - hechos, 0)
    pocos: list[str] = []
    inicios = [n["inicio"] for n in notas if n["inicio"]]
    desde = min(inicios + ([git["primer_commit"]] if git and git["primer_commit"] else []), default=None)
    semanas = (hoy - desde).days / 7 if desde else 0.0
    base = {"hitos_restantes": restantes, "desde": _iso(desde), "semanas_de_historia": round(semanas, 1),
            "ritmo_hitos_semana": None, "ritmo_historico_semana": None, "factor_actividad": None, "semanas_restantes": None,
            "fecha_prevista": None, "desfase_dias": None, "confianza": "baja", "pocos_datos": True,
            "motivo": ""}
    if total == 0:
        return {**base, "motivo": "sin hitos definidos en las notas"}
    if restantes == 0:
        return {**base, "fecha_prevista": None, "confianza": "alta", "pocos_datos": False,
                "motivo": "todos los hitos están hechos"}
    if not desde or semanas < 1:
        return {**base, "motivo": "pocos datos: menos de una semana de historia"}
    if hechos == 0:
        return {**base, "motivo": "pocos datos: aún no hay hitos hechos para medir el ritmo"}

    historico = hechos / semanas
    if git and git["commits_4_semanas"] == 0:
        ultimo = git["ultimo_commit"].isoformat() if git["ultimo_commit"] else "?"
        return {**base, "ritmo_hitos_semana": 0.0, "ritmo_historico_semana": round(historico, 2),
                "motivo": f"parado: 0 commits en 4 semanas (último el {ultimo}); al ritmo reciente no hay fecha"}
    factor = 1.0
    if git and git["commits_total"] and semanas >= 4:
        media_4s = git["commits_total"] / semanas * 4
        factor = min(max(git["commits_4_semanas"] / media_4s, 0.25), 2.0) if media_4s else 1.0
    elif git is None:
        pocos.append("sin git: no se corrige por la actividad reciente")
    ritmo = historico * factor
    semanas_r = restantes / ritmo
    prevista = hoy + timedelta(days=round(semanas_r * 7))
    if hechos < 3:
        pocos.append(f"solo {hechos} hito(s) hecho(s)")
    if semanas < 4:
        pocos.append(f"solo {semanas:.1f} semanas de historia")
    if git and git["commits_4_semanas"] < 5:
        pocos.append(f"solo {git['commits_4_semanas']} commits en 4 semanas")
    if not any(n["cerrado"] for n in notas):
        pocos.append("ninguna fase con fecha de cierre")
    confianza = "baja" if len(pocos) >= 2 or hechos < 3 else "media" if pocos else "alta"
    return {**base,
            "ritmo_hitos_semana": round(ritmo, 2),
            "ritmo_historico_semana": round(historico, 2),
            "factor_actividad": round(factor, 2),
            "semanas_restantes": round(semanas_r, 1),
            "fecha_prevista": prevista.isoformat(),
            "desfase_dias": (prevista - objetivo).days if objetivo else None,
            "confianza": confianza,
            "pocos_datos": confianza == "baja",
            "motivo": ("pocos datos: " if confianza == "baja" else "") + "; ".join(pocos)}


def proyectos() -> list[dict]:
    try:
        datos = json.loads(CONFIG.read_text(encoding="utf-8"))
        lista = [p for p in datos.get("proyectos", []) if p.get("nombre") and p.get("ruta")]
        if lista:
            return lista
    except (OSError, ValueError, AttributeError):
        pass
    return PROYECTOS_DEFECTO


SESIONES = Path.home() / ".claude" / "sessions"


def _viva(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def sesion_activa() -> dict | None:
    """La sesión interactiva del usuario con actividad más reciente (sin Ío ni trabajadores)."""
    mejor, cuando = None, -1
    for f in SESIONES.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("kind") != "interactive" or d.get("agent") == "narrador:io" or d.get("name") in ("Ío", "Io", "Shiri"):
            continue
        if not d.get("cwd") or not _viva(d.get("pid")):
            continue
        t = max(int(d.get("statusUpdatedAt") or 0), int(d.get("updatedAt") or 0))
        if t > cuando:
            mejor, cuando = d, t
    return mejor


def _archivos_conocidos() -> list[str]:
    """Rutas relativas de hoja de ruta única que traen los proyectos configurados."""
    return sorted({p["roadmap_md"] for p in proyectos() if p.get("roadmap_md")})


def entrada_de(raiz: Path) -> dict:
    """El proyecto configurado con esa raíz; si no lo hay, uno nuevo con su hoja de ruta si la tiene."""
    raiz = Path(raiz).expanduser().resolve()
    for p in proyectos():
        try:
            if Path(p["ruta"]).expanduser().resolve() == raiz:
                return dict(p)
        except (OSError, RuntimeError):
            continue
    entrada = {"nombre": raiz.name, "ruta": str(raiz)}
    if not (raiz / "conocimiento" / "roadmap").is_dir():
        rel = next((r for r in _archivos_conocidos() if (raiz / r).is_file()), None)
        if rel:
            entrada["roadmap_md"] = rel
    return entrada


def raiz_de(cwd: str) -> Path:
    """Sube desde cwd hasta la carpeta con conocimiento/roadmap (o con la hoja de ruta única de un
    proyecto configurado); si no hay, la raíz git (o cwd)."""
    ruta = Path(cwd).expanduser().resolve()
    archivos = _archivos_conocidos()
    for r in (ruta, *ruta.parents):
        if (r / "conocimiento" / "roadmap").is_dir() or any((r / a).is_file() for a in archivos):
            return r
        if r == Path.home():
            break
    top = _git(ruta, "rev-parse", "--show-toplevel")
    if top:
        top_p = Path(top.strip())
        # un worktree de .claude/worktrees cuelga del repo principal
        partes = top_p.parts
        if ".claude" in partes:
            top_p = Path(*partes[:partes.index(".claude")])
        return top_p
    return ruta


def informe(p: dict, hoy: date) -> dict:
    ruta = Path(p["ruta"]).expanduser()
    carpeta = ruta / "conocimiento" / "roadmap"
    vacio = {"nombre": p["nombre"], "ruta": str(ruta), "vault": str(ruta / "conocimiento"),
             "semaforo": "sin_objetivo", "deriva_texto": "", "medido": None, "estimado": None,
             "avisos": [], "notas": []}
    if p.get("roadmap_md"):
        archivo = ruta / p["roadmap_md"]
        vacio = {**vacio, "fuente": str(archivo), "fuente_tipo": "tabla", "rumbo_fecha": None}
        if not archivo.is_file():
            return {**vacio, "error": f"sin hoja de ruta: falta {archivo}"}
        filas, fecha, error = leer_rumbo(archivo)
        if error:
            return {**vacio, "rumbo_fecha": _iso(fecha), "error": error}
        git = datos_git(ruta, hoy)
        if git and fecha and (not git["primer_commit"] or git["primer_commit"] < fecha):
            # el ritmo se mide desde que se fijó el rumbo, no desde el primer commit del repo
            git = {**git, "primer_commit": fecha}
        r = calcular(p["nombre"], ruta, filas, git, hoy)
        sig = next((n for n in filas if n["siguiente"]), None)
        r["medido"]["siguiente_fase"] = f"acción {sig['numero']}" if sig else ""
        return {**r, "fuente": str(archivo), "fuente_tipo": "tabla", "rumbo_fecha": _iso(fecha)}
    if not carpeta.is_dir():
        return {**vacio, "error": f"sin vault: falta {carpeta}"}
    notas = [n for f in sorted(carpeta.glob("*.md")) if (n := leer_nota(f))]
    if not notas:
        return {**vacio, "error": "el vault no tiene notas de roadmap (tipo: roadmap)"}
    return calcular(p["nombre"], ruta, notas, datos_git(ruta, hoy), hoy)


def texto(r: dict) -> str:
    if r["error"]:
        return f"{r['nombre']}: {r['error']}"
    m, e = r["medido"], r["estimado"]
    avance = f"{m['hitos_hechos']}/{m['hitos_total']} hitos" + (f" ({m['avance_pct']} %)" if m["avance_pct"] is not None else "")
    f = m["fases"]
    lineas = [f"{r['nombre']}  [{r['semaforo']}]  {r['deriva_texto']}",
              "  medido:",
              f"    avance {avance} · fases: {f['hecho']} hechas, {f['en-curso']} en curso, "
              f"{f['pendiente']} pendientes, {f['aparcado']} aparcadas",
              f"    commits en 4 semanas: {m['commits_4_semanas'] if m['commits_4_semanas'] is not None else 'sin git'}"
              f" · cierres en 4 semanas: {len(m['cierres_4_semanas'])}",
              f"    último movimiento: {m['ultimo_movimiento'] or '?'}"
              + (f" ({m['dias_sin_tocar']} días sin tocar)" if m["dias_sin_tocar"] is not None else "")
              + (f" · {m['ultimo_movimiento_texto']}" if m["ultimo_movimiento_texto"] else ""),
              f"    archivos con cambios sin commit: {m['cambios_sin_commit']}" if m["cambios_sin_commit"] else "",
              f"    responsable: {m['responsable'] or '?'}",
              f"    siguiente ({m['siguiente_fase'] or '-'}): {m['siguiente'] or 'sin siguiente paso'}"]
    if r.get("fuente_tipo") == "tabla":
        iconos = {"hecho": "✓", "en-curso": "●", "aparcado": "◌"}
        lineas.append(f"  acciones (rumbo vigente del {r.get('rumbo_fecha') or '?'}):")
        for n in r["notas"]:
            extra = [x for x in (n["responsable"], f"objetivo {n['objetivo']}" if n["objetivo"] else "",
                                 f"cerrada {n['cerrado']}" if n["cerrado"] else "") if x]
            lineas.append(f"    {iconos.get(n['estado'], '○')} {n['nota']}" + (f" · {' · '.join(extra)}" if extra else ""))
    lineas.append("  estimado:")
    if e["fecha_prevista"]:
        lineas.append(f"    {e['hitos_restantes']} hitos restantes a {e['ritmo_hitos_semana']} por semana"
                      f" → hacia el {e['fecha_prevista']} · confianza {e['confianza']}")
    else:
        lineas.append(f"    sin previsión · {e['hitos_restantes']} hitos restantes")
    if e["motivo"]:
        lineas.append(f"    {e['motivo']}")
    for a in r["avisos"][:6]:
        lineas.append(f"  aviso: {a}")
    return "\n".join(x for x in lineas if x)


def main(args: list[str]) -> int:
    como_json = "--json" in args
    hoy = date.today()
    resto = []
    i = 0
    while i < len(args):
        if args[i] == "--hoy" and i + 1 < len(args):  # para pruebas
            hoy = date.fromisoformat(args[i + 1])
            i += 2
            continue
        if args[i] in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        if args[i] != "--json":
            resto.append(args[i])
        i += 1
    lista = proyectos()
    activo = None
    if "--activo" in resto:
        resto = [x for x in resto if x != "--activo"]
        ses = sesion_activa()
        if not ses:
            print("no hay ninguna sesión interactiva tuya abierta", file=sys.stderr)
            return 2
        raiz = raiz_de(ses["cwd"])
        activo = {"sesion": ses.get("name") or ses.get("sessionId", "")[:8], "cwd": ses["cwd"]}
        lista = [entrada_de(raiz)]
    elif resto and Path(resto[0]).expanduser().is_dir():
        raiz = raiz_de(resto[0])
        lista = [entrada_de(raiz)]
    elif resto:
        filtro = resto[0].lower()
        lista = [p for p in lista if filtro in p["nombre"].lower()]
        if not lista:
            print(f"no hay ningún proyecto que se llame «{resto[0]}»", file=sys.stderr)
            return 1
    informes = [informe(p, hoy) for p in lista]
    if como_json:
        print(json.dumps({"generado": datetime.now().isoformat(timespec="seconds"), "hoy": hoy.isoformat(),
                          "activo": activo, "proyectos": informes}, ensure_ascii=False, indent=2))
    else:
        if activo:
            print(f"(sesión activa: {activo['sesion']} · {activo['cwd']})\n")
        print("\n\n".join(texto(r) for r in informes))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main(sys.argv[1:]))
