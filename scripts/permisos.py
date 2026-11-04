"""Qué sesiones de Claude Code te están esperando, y aviso por voz sin gastar tokens.

Lee `claude agents --json`, la forma soportada de ver el estado desde fuera. Solo muestra nombre,
carpeta y motivo: nunca el comando que se quiere aprobar. Avisa, pero no aprueba: un permiso solo se
responde en la ventana de su sesión.
"""

import fcntl
import json
import os
import subprocess
import sys
import time

from asistente import aviso, claude, corta, entorno_limpio
from comun import RAIZ, RUNTIME
from pretool import es_sesion_de_io

INTERVALO = 15  # s entre miradas
RECORDATORIO = 600  # s entre recordatorios de lo mismo
MAX_RECORDATORIOS = 3
GRACIA = 60  # s que se recuerda algo ya resuelto: una sesión que encadena permisos no repite la voz
ESPERA_CERROJO = 30  # s que espera un vigilante nuevo a que salga el de la sesión anterior
CERROJO = RUNTIME / "permisos.lock"

MOTIVOS = {
    "permission prompt": "un permiso",
    "sandbox request": "un permiso de red",
    "input needed": "una respuesta",
    "worker request": "una petición de un trabajador",
    "dialog open": "que cierres un diálogo",
}


def leer() -> list[dict] | None:
    """La lista de sesiones, o None si no se pudo leer (no es lo mismo que «no hay nadie»)."""
    try:
        r = subprocess.run([claude(), "agents", "--json"], capture_output=True, text=True, timeout=30)
        lista = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit):
        return None
    return lista if isinstance(lista, list) else None


def pendientes(lista: list[dict]) -> list[dict]:
    salida = []
    for a in lista:
        if not isinstance(a, dict):
            continue
        espera = a.get("waitingFor") or a.get("status") == "waiting" or a.get("state") == "blocked"
        # una sesión de fondo sin proceso no espera a nadie: es lo que quedó de una que ya no corre
        if not espera or (a.get("kind") == "background" and not a.get("pid")):
            continue
        razon = a.get("waitingFor")
        motivo = MOTIVOS.get(razon, "algo") if isinstance(razon, str) else "algo"
        sesion = a.get("sessionId") or a.get("id") or a.get("name")
        salida.append({"clave": f"{sesion}|{motivo}", "nombre": a.get("name") or "sin nombre",
                       "carpeta": corta(a.get("cwd") or ""), "motivo": motivo})
    return salida


def frase(p: dict) -> str:
    return f"La sesión {p['nombre']} espera {p['motivo']}."


def transicion(estado: dict, lista: list[dict], ahora: float) -> tuple[dict, list[dict]]:
    """(estado nuevo, avisos que dar). Sin E/S: avisa al aparecer y recuerda, con tope."""
    claves = {p["clave"] for p in lista}
    # solo caduca lo que ya no está: si sigue ahí tras un corte de lectura, es lo mismo de antes
    nuevo = {c: (e if c in claves else dict(e, ausente=True)) for c, e in estado.items()
             if c in claves or ahora - e["visto"] <= GRACIA}
    avisos = []
    for p in lista:
        e = nuevo.get(p["clave"])
        if e is None:
            nuevo[p["clave"]] = {"visto": ahora, "ultimo": ahora, "recordatorios": 0}
            avisos.append(p)
            continue
        if e.get("ausente"):  # se resolvió y pide otra cosa: sin voz ahora, pero con recordatorios nuevos
            nuevo[p["clave"]] = {"visto": ahora, "ultimo": ahora, "recordatorios": 0}
            continue
        e = nuevo[p["clave"]] = dict(e, visto=ahora)
        if ahora - e["ultimo"] >= RECORDATORIO and e["recordatorios"] < MAX_RECORDATORIOS:
            e.update(ultimo=ahora, recordatorios=e["recordatorios"] + 1)
            avisos.append(p)
    return nuevo, avisos


def ciclo(estado: dict, lista: list[dict] | None, ahora: float) -> tuple[dict, list[dict]]:
    """Una vuelta del vigilante. Si no se pudo leer, no cambia nada: así un fallo no repite avisos."""
    if lista is None:
        return estado, []
    # Shiri ya te habla en su propia ventana; avisar de ella sería decirlo dos veces
    ajenas = [a for a in lista if not es_sesion_de_io(a.get("sessionId"))]
    return transicion(estado, pendientes(ajenas), ahora)


def vuelta(estado: dict, voz: bool) -> dict:
    """Una mirada completa. Nada de lo que falle aquí puede parar al vigilante."""
    try:
        estado, avisos = ciclo(estado, leer(), time.time())
    except Exception as e:
        print(f"no pude mirar las sesiones: {type(e).__name__}", file=sys.stderr, flush=True)
        return estado
    for p in avisos:
        print(f"{time.strftime('%H:%M:%S')} {frase(p)}", flush=True)
        if voz:
            try:
                aviso(frase(p))
            except Exception as e:
                print(f"no pude avisar: {type(e).__name__}", file=sys.stderr, flush=True)
    return estado


def padre_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def vigilar(intervalo: float = INTERVALO, voz: bool = True, padre: int | None = None) -> int:
    """Con `padre`, termina cuando muere ese proceso: `bin/io` no llega a su `finally` si cierras la terminal."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cerrojo = open(CERROJO, "a")
    limite = time.monotonic() + (ESPERA_CERROJO if padre else 0)
    while True:
        try:
            fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= limite:
                print("el vigilante ya está en marcha")
                return 0
            time.sleep(0.1)
    estado: dict = {}
    while padre is None or padre_vivo(padre):
        estado = vuelta(estado, voz)
        time.sleep(intervalo)
    return 0


def arrancar_vigilante(padre: int) -> subprocess.Popen:
    """Lo lanza aparte y sin terminal, atado a la vida de `padre`."""
    return subprocess.Popen([sys.executable, str(RAIZ / "bin" / "narrador"), "permisos", "vigilar", "--padre", str(padre)],
                            env=entorno_limpio(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def main(args: list[str]) -> int:
    if args[:1] == ["vigilar"]:
        intervalo = float(args[args.index("--intervalo") + 1]) if "--intervalo" in args else INTERVALO
        padre = int(args[args.index("--padre") + 1]) if "--padre" in args else None
        return vigilar(intervalo, voz="--sin-voz" not in args, padre=padre)
    lista = leer()
    if lista is None:
        print("no pude leer el estado de las sesiones")
        return 1
    espera = pendientes(lista)
    if "--json" in args:
        print(json.dumps([{k: p[k] for k in ("nombre", "carpeta", "motivo")} for p in espera], ensure_ascii=False))
    elif not espera:
        print("nadie te espera")
    else:
        for p in espera:
            print(f"{p['nombre']}  espera {p['motivo']}  {p['carpeta']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
