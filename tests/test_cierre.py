"""Pruebas del hook de cierre de turno (scripts/cierre.py)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import abrir_sesion  # noqa: E402
import cierre  # noqa: E402
import visor  # noqa: E402


def usuario(texto):
    return {"type": "user", "message": {"content": texto}}


def resultado():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def asistente(*bloques):
    contenido = [{"type": "tool_use", "id": "t1", "name": b[1:], "input": {}} if b.startswith("@")
                 else {"type": "text", "text": b} for b in bloques]
    return {"type": "assistant", "message": {"content": contenido}}


class Revisar(unittest.TestCase):
    def test_lista_de_pendientes_bloquea(self):
        for texto in ("Hecho.\n\n**Pendiente**\n- Usuario: firmar D5, D6 y D7", "## Falta\n1. Enviar el mensaje",
                      "Listo.\n- Usuario: enviar el mensaje", "Te toca:\n- revisar el PR", "Pendientes del usuario:\n- nada"):
            motivo, casos = cierre.revisar([texto], [], [])
            self.assertIn("pendientes_en_texto", casos, texto)
            self.assertIn("AskUserQuestion", motivo)

    def test_texto_normal_no_bloquea(self):
        for texto in ("🎙️ Hecho, la suite está en verde.", "Falta el punto 3 del informe, lo hago ahora.",
                      "El usuario: no aparece al principio", "Queda pendiente de mezclar, ya lo he lanzado."):
            self.assertEqual(cierre.revisar([texto], [], []), (None, []), texto)

    def test_con_pregunta_de_opciones_no_bloquea(self):
        motivo, casos = cierre.revisar(["Pendiente:\n- elegir fuente de precios"], ["Bash", "AskUserQuestion"], [])
        self.assertIsNone(motivo)
        self.assertEqual(casos, [])

    def test_pregunta_en_texto_solo_se_anota(self):
        motivo, casos = cierre.revisar(["He terminado.\n¿Lanzo la corrida?"], [], [])
        self.assertIsNone(motivo)
        self.assertEqual(casos, ["pregunta_en_texto"])

    def test_sesion_sin_vigilar_bloquea_con_la_orden(self):
        motivo, casos = cierre.revisar(["🎙️ Abierta."], [], [{"nombre": "Motor (plan)", "orden": "narrador sesion esperar abc"}])
        self.assertEqual(casos, ["sin_vigilar"])
        self.assertIn("narrador sesion esperar abc", motivo)


class Decidir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.transcript = self.tmp / "s.jsonl"
        self.parches = [mock.patch.object(cierre, "es_sesion_de_io", lambda s: s == "io"),
                        mock.patch.object(cierre, "REGISTRO", self.tmp / "cierre.jsonl"),
                        mock.patch.object(abrir_sesion, "sin_vigilar", lambda: [])]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def escribir(self, *registros):
        self.transcript.write_text("\n".join(json.dumps(r) for r in registros) + "\n", encoding="utf-8")

    def evento(self, **extra):
        return {"hook_event_name": "Stop", "session_id": "io", "transcript_path": str(self.transcript)} | extra

    def test_bloquea_y_anota_sin_guardar_el_texto(self):
        self.escribir(usuario("estado de vindam"), asistente("Pendiente:\n- Usuario: firmar D5"))
        r = cierre.decidir(self.evento())
        self.assertEqual(r["decision"], "block")
        fila = json.loads((self.tmp / "cierre.jsonl").read_text(encoding="utf-8"))
        self.assertEqual((fila["casos"], fila["accion"]), (["pendientes_en_texto"], "bloqueo"))
        self.assertNotIn("D5", json.dumps(fila))

    def test_solo_mira_el_ultimo_turno(self):
        self.escribir(usuario("uno"), asistente("Pendiente:\n- Usuario: firmar"), usuario("dos"),
                      asistente("@Bash"), resultado(), asistente("🎙️ Hecho."))
        self.assertIsNone(cierre.decidir(self.evento()))

    def test_pregunta_de_opciones_en_el_turno(self):
        self.escribir(usuario("uno"), asistente("Falta:\n- elegir", "@AskUserQuestion"), resultado(), asistente("🎙️ Anotado."))
        self.assertIsNone(cierre.decidir(self.evento()))

    def test_no_insiste_dos_veces_en_el_mismo_turno(self):
        self.escribir(usuario("uno"), asistente("Pendiente:\n- Usuario: firmar"))
        self.assertIsNone(cierre.decidir(self.evento(stop_hook_active=True)))
        self.assertEqual(json.loads((self.tmp / "cierre.jsonl").read_text(encoding="utf-8"))["accion"], "repetido")

    def test_otra_sesion_no_se_toca(self):
        self.escribir(usuario("uno"), asistente("Pendiente:\n- Usuario: firmar"))
        self.assertIsNone(cierre.decidir(self.evento(session_id="otra")))
        self.assertFalse((self.tmp / "cierre.jsonl").exists())

    def test_mensaje_final_que_aun_no_esta_en_el_transcript(self):
        self.escribir(usuario("uno"))
        r = cierre.decidir(self.evento(last_assistant_message="Falta:\n- Usuario: enviar el mensaje"))
        self.assertEqual(r["decision"], "block")

    def test_sin_transcript_no_falla(self):
        self.assertIsNone(cierre.decidir(self.evento(transcript_path=str(self.tmp / "no-existe.jsonl"))))

    def test_sin_vigilar_llega_al_bloqueo(self):
        self.escribir(usuario("abre el plan"), asistente("🎙️ Abierta."))
        with mock.patch.object(abrir_sesion, "sin_vigilar", lambda: [{"nombre": "X (plan)", "orden": "narrador sesion esperar 123"}]):
            r = cierre.decidir(self.evento())
        self.assertIn("narrador sesion esperar 123", r["reason"])


class Proceso(unittest.TestCase):
    def test_entrada_rota_sale_con_cero_y_en_silencio(self):
        r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "cierre.py")], input="{roto", capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


class UltimoTurno(unittest.TestCase):
    def test_un_resultado_de_herramienta_no_abre_turno(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.jsonl"
            f.write_text("\n".join(json.dumps(r) for r in (
                usuario("uno"), asistente("viejo"), usuario([{"type": "text", "text": "dos"}]),
                asistente("a", "@Bash"), resultado(), asistente("b"))) + "\nrota\n", encoding="utf-8")
            self.assertEqual(visor.ultimo_turno(f), (["a", "b"], ["Bash"]))

    def test_turno_que_empieza_antes_de_la_cola(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.jsonl"
            relleno = json.dumps({"type": "api-request-blob", "message": {"content": [{"type": "text", "text": "x" * 500}]}})
            f.write_text("\n".join([json.dumps(usuario("uno")), json.dumps(asistente("plan", "@ExitPlanMode")), relleno, relleno]) + "\n",
                         encoding="utf-8")
            with mock.patch.object(visor, "COLA_TURNO", 600):
                self.assertEqual(visor.ultimo_turno(f), (["plan"], ["ExitPlanMode"]))


if __name__ == "__main__":
    unittest.main()
