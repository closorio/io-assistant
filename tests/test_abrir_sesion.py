"""Pruebas de `narrador sesion plan | esperar` y de lo que queda sin vigilar (scripts/abrir_sesion.py)."""

import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import abrir_sesion  # noqa: E402
import asistente  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sesiones = self.tmp / "sessions"
        self.sesiones.mkdir()
        self.registro: list[dict] = []
        self.parches = [mock.patch.object(abrir_sesion, "SESIONES", self.sesiones),
                        mock.patch.object(abrir_sesion, "_registro", lambda: list(self.registro)),
                        mock.patch.object(abrir_sesion, "_guardar", lambda lista: self.registro.__init__(lista)),
                        mock.patch.object(asistente, "VIGILANCIA", self.tmp / "vigilancia"),
                        mock.patch.object(abrir_sesion, "PLANES", self.tmp / "plans"),
                        mock.patch.object(abrir_sesion, "ESPERA_SESION", 0.01),
                        mock.patch.object(abrir_sesion, "ESPERA_APERTURA", 0.3)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def sesion(self, sid=SID, pid=None, **campos):
        datos = {"pid": pid or os.getpid(), "sessionId": sid, "cwd": str(self.tmp), "name": "Tema (plan)"} | campos
        (self.sesiones / f"{sid[:6]}.json").write_text(json.dumps(datos), encoding="utf-8")

    def salida(self, f, *a, **k):
        fuera, errores = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(fuera), contextlib.redirect_stderr(errores):
            codigo = f(*a, **k)
        return codigo, fuera.getvalue(), errores.getvalue()


class Plan(Base):
    def setUp(self):
        super().setUp()
        self.prompt = self.tmp / "prompt.md"
        self.prompt.write_text("Encargo: ordenar el vault.\n", encoding="utf-8")
        self.lanzado: list[list[str]] = []
        extra = [mock.patch.object(abrir_sesion, "resolver_proyecto", lambda p: self.tmp),
                 mock.patch.object(abrir_sesion.shutil, "which", lambda n: "/usr/bin/gnome-terminal"),
                 mock.patch.object(abrir_sesion, "_claude_terminal", lambda: "/home/x/.local/bin/claude"),
                 mock.patch.object(abrir_sesion.uuid, "uuid4", lambda: SID),
                 mock.patch.object(abrir_sesion, "_proceso_con", lambda t: False)]
        for p in extra:
            p.start()
        self.parches += extra

    def test_abre_con_id_conocido_ruta_absoluta_y_pie_de_prioridad(self):
        def popen(orden, **k):
            self.lanzado.append(orden)
            self.sesion()
        with mock.patch.object(abrir_sesion.subprocess, "Popen", popen):
            codigo, fuera, _ = self.salida(abrir_sesion.plan, "motor", str(self.prompt), "Tema (plan)")
        self.assertEqual(codigo, 0)
        orden = self.lanzado[0]
        self.assertIn("/home/x/.local/bin/claude", orden)
        self.assertEqual(orden[orden.index("--session-id") + 1], SID)
        self.assertEqual(orden[orden.index("--permission-mode") + 1], "plan")
        self.assertTrue(orden[-1].startswith("Encargo: ordenar el vault."))
        self.assertIn("camino crítico", orden[-1])
        self.assertIn(f"narrador sesion esperar {SID}", fuera)
        self.assertEqual((self.registro[0]["tipo"], self.registro[0]["session_id"]), ("plan", SID))

    def test_si_no_arranca_lo_dice_y_no_la_apunta(self):
        with mock.patch.object(abrir_sesion.subprocess, "Popen", lambda orden, **k: None):
            codigo, _, errores = self.salida(abrir_sesion.plan, "motor", str(self.prompt))
        self.assertEqual(codigo, 1)
        self.assertIn("NO ha arrancado", errores)
        self.assertEqual(self.registro, [])

    def test_prompt_vacio(self):
        self.prompt.write_text("  \n", encoding="utf-8")
        self.assertEqual(self.salida(abrir_sesion.plan, "motor", str(self.prompt))[0], 1)


class Esperar(Base):
    def setUp(self):
        super().setUp()
        self.registro.append({"nombre": "Tema (plan)", "ruta": str(self.tmp), "tipo": "plan", "session_id": SID,
                              "inicio": time.time() - 5})
        self.transcript = self.tmp / "t.jsonl"
        p = mock.patch.object(abrir_sesion, "ruta_transcript", lambda cwd, s: self.transcript)
        p.start()
        self.parches.append(p)

    def turno(self, *bloques):
        contenido = [{"type": "tool_use", "id": "x", "name": b[1:], "input": {}} if b.startswith("@")
                     else {"type": "text", "text": b} for b in bloques]
        self.transcript.write_text(json.dumps({"type": "user", "message": {"content": "encargo"}}) + "\n"
                                   + json.dumps({"type": "assistant", "message": {"content": contenido}}) + "\n", encoding="utf-8")

    def test_plan_listo(self):
        (self.tmp / "plans").mkdir()
        (self.tmp / "plans" / "mi-plan.md").write_text("# Plan", encoding="utf-8")
        self.sesion(status="waiting", waitingFor="permission prompt")
        self.turno("Voy a escribir el plan.", "@ToolSearch")  # el ExitPlanMode pendiente no está en el transcript
        codigo, fuera, _ = self.salida(abrir_sesion.esperar, SID[:8])
        self.assertEqual(codigo, 0)
        self.assertIn("[sesión Tema (plan)] plan listo para aprobar en su ventana", fuera)
        self.assertIn("mi-plan.md", fuera)
        self.assertTrue(asistente.vigilada(SID))
        self.assertTrue((self.tmp / "vigilancia" / f"{SID}.fin").exists())

    def test_permiso_sin_plan_escrito_lo_dice_con_duda(self):
        self.sesion(status="waiting", waitingFor="permission prompt")
        self.turno("@Bash")
        self.assertIn("o pide un permiso", self.salida(abrir_sesion.esperar, SID)[1])

    def test_pregunta_al_usuario(self):
        self.sesion(status="waiting", waitingFor="input needed")
        self.turno("Necesito una decisión.", "@AskUserQuestion")
        self.assertIn("espera una respuesta del usuario", self.salida(abrir_sesion.esperar, "Tema")[1])

    def test_cerrada(self):
        self.assertIn("cerrada", self.salida(abrir_sesion.esperar, SID)[1])

    def test_recien_abierta_y_sin_trabajar_sigue_esperando(self):
        self.sesion(status="idle")
        codigo, fuera, _ = self.salida(abrir_sesion.esperar, SID, 0.0005)
        self.assertIn("sigue trabajando", fuera)
        self.assertFalse((self.tmp / "vigilancia" / f"{SID}.fin").exists())

    def test_desconocida(self):
        with self.assertRaises(SystemExit):
            abrir_sesion.esperar("no-existe")


class SinVigilar(Base):
    def test_plan_viva_sin_vigilante(self):
        self.registro.append({"nombre": "Tema (plan)", "tipo": "plan", "session_id": SID, "inicio": time.time()})
        self.sesion(status="busy")
        self.assertEqual(abrir_sesion.sin_vigilar(), [{"nombre": "Tema (plan)", "orden": f"narrador sesion esperar {SID}"}])
        asistente.marcar_vigilancia(SID)  # este proceso la espera
        self.assertEqual(abrir_sesion.sin_vigilar(), [])

    def test_vigilante_muerto_no_cuenta_y_el_aviso_de_fin_si(self):
        self.registro.append({"nombre": "Tema (plan)", "tipo": "plan", "session_id": SID, "inicio": time.time()})
        self.sesion(status="waiting")
        (self.tmp / "vigilancia").mkdir()
        (self.tmp / "vigilancia" / f"{SID}.pid").write_text("999999999", encoding="utf-8")
        self.assertEqual(len(abrir_sesion.sin_vigilar()), 1)
        asistente.marcar_vigilancia(SID, fin=True)
        self.assertEqual(abrir_sesion.sin_vigilar(), [])

    def test_trabajador_de_fondo(self):
        self.registro.append({"nombre": "io-motor-101010", "tipo": "bg", "inicio": time.time()})
        self.sesion(sid="aaaaaaaa-0000", name="io-motor-101010", status="idle")
        self.assertEqual(abrir_sesion.sin_vigilar(), [])  # ya parado: no necesita vigilante
        self.sesion(sid="aaaaaaaa-0000", name="io-motor-101010", status="busy")
        self.assertEqual(abrir_sesion.sin_vigilar(), [{"nombre": "io-motor-101010", "orden": "narrador trabajador esperar io-motor-101010"}])

    def test_lo_viejo_y_lo_cerrado_no_cuentan(self):
        self.registro.append({"nombre": "Vieja (plan)", "tipo": "plan", "session_id": SID, "inicio": time.time() - 2 * 86400})
        self.registro.append({"nombre": "Cerrada (plan)", "tipo": "plan", "session_id": "otra", "inicio": time.time()})
        self.sesion(status="busy")
        self.assertEqual(abrir_sesion.sin_vigilar(), [])


if __name__ == "__main__":
    unittest.main()
