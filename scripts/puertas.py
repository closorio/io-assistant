"""Registro de puertas: lo que necesita un sí del usuario antes de que Ío lo haga.

Una puerta es un paso preparado (un push, un gasto, un envío…) con su comando, su coste y cómo se
deshace. Ío la registra con `narrador puerta añadir` a la vez que la pregunta con AskUserQuestion; la
cabina la enseña con botones «Sí» y «No». Responder solo anota la respuesta: **nada aquí ejecuta el
comando**. Ejecutarlo, y luego cerrar la puerta, sigue siendo trabajo de Ío.

Vive en RUNTIME/puertas.json, con cerrojo y escritura atómica como el tablero.
Solo biblioteca estándar.
"""

import json
import os
import sys
import time
from pathlib import Path

from comun import RUNTIME
from tablero_archivo import CerrojoOcupado, con_cerrojo

ARCHIVO = RUNTIME / "puertas.json"
VERSION = 1
GUARDAR_CERRADAS = 100  # las cerradas más recientes que se conservan, para el historial
ESPERA_SONDEO = 2.0  # s entre miradas de `esperar`

ABIERTA, SI, NO, CERRADA = "abierta", "si", "no", "cerrada"
RESPUESTAS = {"si": SI, "sí": SI, "s": SI, "yes": SI, "no": NO, "n": NO}
ORIGENES = ("cabina", "voz", "cli")

USO = """uso: narrador puerta añadir "TÍTULO" --comando "CMD" [--coste C] [--vuelta V] [--proyecto P] [--json]
       narrador puerta lista [--json] [--todas]
       narrador puerta responder ID si|no [--origen cabina|voz|cli] [--json]
       narrador puerta cerrar ID [--nota TEXTO]
       narrador puerta esperar ID [--max MIN]"""


class PuertaError(Exception):
    def __init__(self, mensaje: str, codigo: int):
        super().__init__(mensaje)
        self.codigo = codigo


# --- almacén -------------------------------------------------------------------------

def vacio() -> dict:
    return {"v": VERSION, "rev": 0, "puertas": []}


def leer(ruta: Path = ARCHIVO) -> dict:
    """El registro; sin archivo, uno vacío. Un archivo roto es un error, nunca un registro vacío."""
    try:
        texto = Path(ruta).read_text(encoding="utf-8")
    except FileNotFoundError:
        return vacio()
    try:
        datos = json.loads(texto)
    except ValueError as e:
        raise PuertaError(f"puertas: {ruta} no es JSON ({e})", 3) from e
    if not (isinstance(datos, dict) and isinstance(datos.get("puertas"), list)):
        raise PuertaError(f"puertas: {ruta} no tiene la forma de un registro de puertas", 3)
    return datos


def guardar(datos: dict, ruta: Path = ARCHIVO) -> dict:
    """Escribe de una vez y sube `rev`. Llámalo con el cerrojo tomado."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cerradas = [i for i, p in enumerate(datos["puertas"]) if p.get("estado") == CERRADA]
    viejas = set(cerradas[:-GUARDAR_CERRADAS])  # solo se olvidan las cerradas más antiguas
    datos = {"v": VERSION, "rev": int(datos.get("rev", 0)) + 1,
             "puertas": [p for i, p in enumerate(datos["puertas"]) if i not in viejas]}
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(datos, ensure_ascii=False, indent=1) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ruta)
    finally:
        tmp.unlink(missing_ok=True)
    return datos


def ahora_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def buscar(datos: dict, ident: str) -> dict:
    p = next((p for p in datos["puertas"] if p.get("id") == ident), None)
    if p is None:
        raise PuertaError(f"puertas: no hay ninguna puerta «{ident}» (mira narrador puerta lista)", 3)
    return p


# --- operaciones (sin salida por pantalla) ---------------------------------------------

def anadir(titulo: str, comando: str, coste: str = "", vuelta: str = "", proyecto: str = "",
           ruta: Path = ARCHIVO) -> dict:
    from asistente import id_corto  # aquí: asistente arrastra el visor y no hace falta para leer

    titulo, comando = titulo.strip(), comando.strip()
    if not titulo or not comando:
        raise PuertaError("puertas: una puerta necesita título y comando", 2)
    with con_cerrojo(ruta):
        datos = leer(ruta)
        puerta = {
            "id": id_corto({p.get("id", "") for p in datos["puertas"]}),
            "titulo": titulo, "comando": comando, "coste": coste.strip(), "vuelta": vuelta.strip(),
            "proyecto": proyecto.strip(), "estado": ABIERTA, "creada": ahora_iso(),
            "respondida": None, "origen": None, "nota": "",
        }
        datos["puertas"].append(puerta)
        guardar(datos, ruta)
    return puerta


def responder(ident: str, respuesta: str, origen: str = "cli", ruta: Path = ARCHIVO) -> dict:
    """Anota sí o no en una puerta abierta. No ejecuta nada. Si ya tenía respuesta, código 4."""
    estado = RESPUESTAS.get(respuesta.strip().lower())
    if estado is None:
        raise PuertaError(f"puertas: la respuesta es «si» o «no», no «{respuesta}»", 2)
    if origen not in ORIGENES:
        raise PuertaError(f"puertas: origen desconocido «{origen}» ({', '.join(ORIGENES)})", 2)
    with con_cerrojo(ruta):
        datos = leer(ruta)
        p = buscar(datos, ident)
        if p.get("estado") != ABIERTA:
            raise PuertaError(f"puertas: la puerta {ident} ya no está abierta (está en «{p.get('estado')}»)", 4)
        p.update(estado=estado, respondida=ahora_iso(), origen=origen)
        guardar(datos, ruta)
    return p


def cerrar(ident: str, nota: str = "", ruta: Path = ARCHIVO) -> dict:
    """Da la puerta por terminada: Ío ya ejecutó el comando, o lo descartó."""
    with con_cerrojo(ruta):
        datos = leer(ruta)
        p = buscar(datos, ident)
        p.update(estado=CERRADA, cerrada=ahora_iso(), nota=nota.strip() or p.get("nota", ""))
        guardar(datos, ruta)
    return p


def pendientes(datos: dict, todas: bool = False) -> list[dict]:
    """Lo que la cabina enseña: abiertas y respondidas sin cerrar (todas, con --todas)."""
    return [p for p in datos["puertas"] if todas or p.get("estado") != CERRADA]


def esperar(ident: str, maximo_min: float | None = None, ruta: Path = ARCHIVO,
            sondeo: float = ESPERA_SONDEO) -> dict:
    """Bloquea hasta que la puerta deja de estar abierta, o hasta `maximo_min`. Para un Monitor."""
    inicio = time.monotonic()
    while True:
        p = buscar(leer(ruta), ident)
        if p.get("estado") != ABIERTA:
            return p
        if maximo_min is not None and time.monotonic() - inicio > maximo_min * 60:
            return p
        time.sleep(sondeo)


# --- texto ---------------------------------------------------------------------------

NOMBRES = {ABIERTA: "abierta", SI: "sí", NO: "no", CERRADA: "cerrada"}


def linea(p: dict) -> str:
    extra = " · ".join(x for x in (p.get("proyecto"), f"coste {p['coste']}" if p.get("coste") else "") if x)
    return (f"{p['id']}  {NOMBRES.get(p.get('estado'), p.get('estado'))}  «{p['titulo']}»"
            + (f"  ({extra})" if extra else "")
            + f"\n    comando: {p['comando']}"
            + (f"\n    vuelta atrás: {p['vuelta']}" if p.get("vuelta") else ""))


def evento(p: dict) -> str:
    """La línea que recibe Ío cuando una puerta deja de estar abierta (Monitor de `esperar`)."""
    if p.get("estado") == SI:
        return (f"[puerta {p['id']}] sí a «{p['titulo']}» (desde {p.get('origen') or '?'}). "
                f"Nada se ha ejecutado: el comando preparado es `{p['comando']}`. Ejecútalo tú y luego "
                f"`narrador puerta cerrar {p['id']}`.")
    if p.get("estado") == NO:
        return (f"[puerta {p['id']}] no a «{p['titulo']}» (desde {p.get('origen') or '?'}). "
                f"No lo ejecutes; ciérrala con `narrador puerta cerrar {p['id']}`.")
    if p.get("estado") == CERRADA:
        return f"[puerta {p['id']}] cerrada: «{p['titulo']}»" + (f" ({p['nota']})" if p.get("nota") else "")
    return f"[puerta {p['id']}] sigue abierta: «{p['titulo']}»"


# --- CLI -----------------------------------------------------------------------------

def _opcion(args: list[str], nombre: str, defecto: str = "") -> tuple[str, list[str]]:
    if nombre in args:
        i = args.index(nombre)
        if i + 1 >= len(args):
            raise PuertaError(f"puertas: falta el valor de {nombre}", 2)
        return args[i + 1], args[:i] + args[i + 2:]
    return defecto, args


def main(args: list[str], ruta: Path = ARCHIVO) -> int:
    try:
        return _main(args, ruta)
    except PuertaError as e:
        print(e, file=sys.stderr)
        return e.codigo
    except CerrojoOcupado as e:
        print(f"puertas: {e}", file=sys.stderr)
        return 5


def _main(args: list[str], ruta: Path) -> int:
    if not args:
        print(USO, file=sys.stderr)
        return 2
    orden, resto = args[0], args[1:]
    como_json = "--json" in resto
    resto = [a for a in resto if a != "--json"]
    if orden in ("añadir", "anadir", "nueva"):
        comando, resto = _opcion(resto, "--comando")
        coste, resto = _opcion(resto, "--coste")
        vuelta, resto = _opcion(resto, "--vuelta")
        proyecto, resto = _opcion(resto, "--proyecto")
        p = anadir(" ".join(resto), comando, coste, vuelta, proyecto, ruta)
        print(json.dumps(p, ensure_ascii=False) if como_json else p["id"])
        return 0
    if orden == "lista":
        todas = "--todas" in resto
        lista = pendientes(leer(ruta), todas)
        if como_json:
            print(json.dumps({"puertas": lista}, ensure_ascii=False))
        elif not lista:
            print("no hay puertas abiertas")
        else:
            print("\n".join(linea(p) for p in lista))
        return 0
    if orden == "responder" and len(resto) >= 2:
        origen, resto = _opcion(resto, "--origen", "cli")
        p = responder(resto[0], resto[1], origen, ruta)
        print(json.dumps(p, ensure_ascii=False) if como_json else evento(p))
        return 0
    if orden == "cerrar" and resto:
        nota, resto = _opcion(resto, "--nota")
        p = cerrar(resto[0], nota, ruta)
        print(json.dumps(p, ensure_ascii=False) if como_json else evento(p))
        return 0
    if orden == "esperar" and resto:
        maximo, resto = _opcion(resto, "--max")
        try:
            p = esperar(resto[0], float(maximo) if maximo else None, ruta)
        except KeyboardInterrupt:
            return 130
        print(evento(p), flush=True)
        return 0
    print(USO, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
