import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import asistente  # noqa: E402

YO = os.getpid()


def test_cuenta_solo_los_de_fondo_ocupados_y_vivos():
    agentes = [
        {"name": "Ío", "kind": "interactive", "status": "busy", "pid": YO},
        {"name": "io-a-k7q", "kind": "background", "status": "busy", "pid": YO},
        {"name": "io-b-m4z", "kind": "background", "status": None, "pid": None},
        {"name": "io-c-p2r", "kind": "background", "status": "idle", "pid": YO},
    ]
    assert asistente.trabajadores_activos(agentes, registro=[]) == 1


def test_suma_los_claude_p_vivos_del_registro():
    registro = [{"nombre": "io-d-x3y", "tipo": "p", "pid": YO},
                {"nombre": "io-e-z9w", "tipo": "p", "pid": 999999999},
                {"nombre": "io-f-q5n", "tipo": "cola"}]
    assert asistente.trabajadores_activos([], registro=registro) == 1


def test_sin_hueco_por_tope_o_memoria(monkeypatch):
    monkeypatch.setattr(asistente, "trabajadores_activos", lambda: asistente.TOPE_TRABAJADORES)
    monkeypatch.setattr(asistente, "memoria_disponible_gb", lambda: 20.0)
    assert asistente.hay_hueco()[0] is False
    monkeypatch.setattr(asistente, "trabajadores_activos", lambda: 0)
    monkeypatch.setattr(asistente, "memoria_disponible_gb", lambda: 1.0)
    libre, motivo = asistente.hay_hueco()
    assert libre is False and "memoria" in motivo
    monkeypatch.setattr(asistente, "memoria_disponible_gb", lambda: 20.0)
    assert asistente.hay_hueco() == (True, "")


def test_lanzar_sin_hueco_encola_con_nombre(monkeypatch, tmp_path):
    guardado = []
    monkeypatch.setattr(asistente, "resolver_proyecto", lambda p: tmp_path)
    monkeypatch.setattr(asistente, "hay_hueco", lambda: (False, "2 trabajadores activos (tope 2)"))
    monkeypatch.setattr(asistente, "_registro", lambda: [])
    monkeypatch.setattr(asistente, "_guardar", lambda lista: guardado.extend(lista))
    lanzados = []
    monkeypatch.setattr(asistente.subprocess, "Popen", lambda orden, **kw: lanzados.append(orden))
    monkeypatch.setattr(asistente.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no debe lanzar")))
    asistente.lanzar("x", "tarea", contrato=True)
    assert guardado[0]["tipo"] == "cola" and guardado[0]["contrato"] is True
    assert lanzados[0][-2:] == ["despachar", guardado[0]["nombre"]]


def test_despachar_lanza_cuando_hay_hueco(monkeypatch):
    t = {"nombre": "io-x-k7q", "ruta": "/tmp", "tarea": "t", "contrato": True, "modelo": None, "tipo": "cola"}
    monkeypatch.setattr(asistente, "_registro", lambda: [t])
    huecos = iter([(False, "lleno"), (True, "")])
    monkeypatch.setattr(asistente, "hay_hueco", lambda: next(huecos))
    monkeypatch.setattr(asistente.time, "sleep", lambda s: None)
    llamadas = []
    monkeypatch.setattr(asistente, "lanzar", lambda *a, **kw: llamadas.append((a, kw)))
    asistente.despachar("io-x-k7q")
    assert llamadas == [(("/tmp", "t", None, True), {"nombre": "io-x-k7q", "cola": False})]
