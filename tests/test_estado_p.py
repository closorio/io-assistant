import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import asistente  # noqa: E402


def _log(tmp_path, *resultados):
    log = tmp_path / "w.log"
    log.write_text("\n".join(json.dumps({"type": "result", "result": r, "is_error": False}) for r in resultados) + "\n")
    return str(log)


def test_vivo_con_result_sigue_trabajando(tmp_path):
    # forma real del 2026-11-10: turno cerrado con «vuelvo cuando termine la suite», proceso vivo
    t = {"log": _log(tmp_path, "La suite sigue en marcha; vuelvo cuando termine."), "pid": os.getpid()}
    assert asistente._estado_p(t)[0] == "trabajando"


def test_muerto_da_el_ultimo_result(tmp_path):
    t = {"log": _log(tmp_path, "primero", "informe final"), "pid": 2 ** 22 + 12345}
    assert asistente._estado_p(t) == ("terminado", "informe final")


def test_muerto_sin_result(tmp_path):
    log = tmp_path / "w.log"
    log.write_text("")
    assert asistente._estado_p({"log": str(log), "pid": 2 ** 22 + 12345})[0] == "parado sin resultado"
