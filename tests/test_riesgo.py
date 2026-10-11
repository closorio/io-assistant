"""Pruebas de riesgo.py. Ejecuta: python3 -m unittest discover -s tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from riesgo import CONFIRMAR, LIBRE, clasificar, interpretar  # noqa: E402


class Interpretar(unittest.TestCase):
    def test_media(self):
        casos = {
            "Sí.": "si", "Sí, hazlo.": "si", "Ío, sí": "si", "Vale": "si", "Adelante.": "si",
            "De acuerdo": "si", "Confirmo": "si",
            "No.": "no", "No, espera": "no", "Sí, pero espera": "no", "Vale, no": "no", "No sé si": "no",
            "Cancela": "no",
            "¿Sí?": "duda", "si quieres luego": "duda", "Hmm": "duda", "": "duda", "Explícame primero": "duda",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(interpretar(texto, alta=False), esperado)

    def test_alta_exige_confirmo(self):
        casos = {
            "Confirmo.": "si", "Ío, confirmo": "si", "Lo confirmo": "si",
            "Sí": "duda", "Vale, adelante": "duda", "Confírmalo": "duda",
            "No confirmo": "no", "Confirmo, pero espera": "no",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(interpretar(texto, alta=True), esperado)


class Clasificar(unittest.TestCase):
    def test_correo(self):
        for servidor in ("mcp__claude_ai_Gmail__", "mcp__plugin_legal_gmail__"):
            v = clasificar(servidor + "send_message", {"to": ["ana@x.com"], "subject": "Hola", "body": "uno dos tres"})
            self.assertEqual(v.nivel, CONFIRMAR)
            self.assertTrue(v.alta)
            self.assertIn("ana@x.com", v.resumen)
            self.assertIn("Hola", v.resumen)
        self.assertEqual(clasificar("mcp__claude_ai_Gmail__reply", {}).nivel, CONFIRMAR)
        self.assertEqual(clasificar("mcp__claude_ai_Gmail__forward", {}).nivel, CONFIRMAR)

    def test_leer_correo_es_libre(self):
        for accion in ("search_threads", "get_thread", "get_message", "list_labels", "create_draft"):
            with self.subTest(accion=accion):
                self.assertEqual(clasificar("mcp__claude_ai_Gmail__" + accion, {}).nivel, LIBRE)

    def test_calendario(self):
        v = clasificar("mcp__claude_ai_Google_Calendar__create_event",
                       {"summary": "Demo", "start": {"dateTime": "2026-10-12T10:00"}})
        self.assertEqual(v.nivel, CONFIRMAR)
        self.assertFalse(v.alta)
        self.assertIn("Demo", v.resumen)
        con_invitados = clasificar("mcp__claude_ai_Google_Calendar__create_event",
                                   {"summary": "Demo", "attendees": ["a@x.com"]})
        self.assertTrue(con_invitados.alta)
        self.assertEqual(clasificar("mcp__claude_ai_Google_Calendar__list_events", {}).nivel, LIBRE)

    def test_git_push(self):
        normal = clasificar("Bash", {"command": "git push origin main"}, proyecto="holo-ui")
        self.assertEqual(normal.nivel, CONFIRMAR)
        self.assertFalse(normal.alta)
        self.assertIn("holo-ui", normal.resumen)
        self.assertTrue(clasificar("Bash", {"command": "git push --force origin main"}).alta)
        self.assertTrue(clasificar("Bash", {"command": "git push -f"}).alta)
        self.assertEqual(clasificar("Bash", {"command": "git add . && git commit -m x && git push"}).nivel, CONFIRMAR)
        self.assertEqual(clasificar("Bash", {"command": "git -C ../otro push"}).nivel, CONFIRMAR)
        self.assertEqual(clasificar("Bash", {"command": "cd x\ngit push"}).nivel, CONFIRMAR)

    def test_lo_normal_es_libre(self):
        for comando in ("ls -la", "git status", "git commit -m 'push del botón'", "npm test",
                        "git log --oneline", "echo pushing"):
            with self.subTest(comando=comando):
                self.assertEqual(clasificar("Bash", {"command": comando}).nivel, LIBRE)
        self.assertEqual(clasificar("Read", {"file_path": "/x"}).nivel, LIBRE)
        self.assertEqual(clasificar("Edit", {"file_path": "/x"}).nivel, LIBRE)


if __name__ == "__main__":
    unittest.main()
