"""Tonos cortos de la cabina: «trabajador terminado», «puerta lista» y «error».

Los wav viven en el mod (mods/io-cabina/assets/tonos/). La cabina no los toca ella: llama a
`narrador tono NOMBRE`, que respeta lo que ya gestiona el narrador:

- con el narrador en silencio, o la escucha en pausa, no suena nada;
- si Ío está hablando o tiene frases en cola, espera a que acabe (hasta ESPERA_MAX s) y, si
  sigue, se calla: un tono encima de una locución estorba más de lo que avisa;
- sale por la misma salida que la voz (`destino`) y al volumen de `tonos.volumen` (0–1).

Solo biblioteca estándar.
"""

import subprocess
import sys
import time
from pathlib import Path

from comun import RAIZ, enviar, leer_config

CARPETA = RAIZ / "mods" / "io-cabina" / "assets" / "tonos"
NOMBRES = ("terminado", "puerta", "error")
ESPERA_MAX = 10.0  # s que aguarda a que Ío deje de hablar
SONDEO = 0.25


def ocupada() -> bool:
    """Ío está hablando o tiene algo en cola. Sin daemon, no lo está."""
    try:
        e = enviar({"cmd": "estado"}, esperar_respuesta=True, timeout=0.3) or {}
    except (OSError, ValueError):
        return False
    return bool(e.get("hablando")) or int(e.get("en_cola") or 0) > 0


def motivo_para_callar(cfg: dict) -> str | None:
    if cfg.get("silencio"):
        return "el narrador está en silencio"
    if (cfg.get("escucha") or {}).get("pausa"):
        return "la escucha está en pausa"
    if not (cfg.get("tonos") or {}).get("activos", True):
        return "los tonos están desactivados"
    return None


def orden_reproducir(cfg: dict, archivo: Path) -> list[str]:
    reproductor = cfg.get("reproductor") or "pw-play"
    if reproductor != "pw-play":
        return [reproductor, str(archivo)]
    volumen = max(0.0, min(float((cfg.get("tonos") or {}).get("volumen", 0.4)), 1.0))
    orden = ["pw-play", f"--volume={volumen:.2f}"]
    if cfg.get("destino"):
        orden.append(f"--target={cfg['destino']}")
    return orden + [str(archivo)]


def tono(nombre: str, espera_max: float = ESPERA_MAX, ocupada=ocupada, ejecutar=subprocess.run) -> tuple[bool, str]:
    """(sonó, por qué). Nunca lanza: un tono que no suena no es un fallo."""
    archivo = Path(nombre) if nombre.endswith(".wav") else CARPETA / f"{nombre}.wav"
    if not archivo.exists():
        return False, f"no existe el tono {archivo}"
    cfg = leer_config()
    motivo = motivo_para_callar(cfg)
    if motivo:
        return False, motivo
    limite = time.monotonic() + espera_max
    while ocupada():
        if time.monotonic() >= limite:
            return False, "Ío sigue hablando"
        time.sleep(SONDEO)
    try:
        r = ejecutar(orden_reproducir(cfg, archivo), capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"no pude reproducirlo: {type(e).__name__}"
    return (r.returncode == 0), ("sonó" if r.returncode == 0 else f"el reproductor salió con {r.returncode}")


def main(args: list[str]) -> int:
    if not args:
        print(f"uso: narrador tono {'|'.join(NOMBRES)}|ARCHIVO.wav", file=sys.stderr)
        return 2
    sono, porque = tono(args[0])
    print(porque)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
