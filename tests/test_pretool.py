import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pretool  # noqa: E402


def evento(herramienta, entrada, sesion="io"):
    return {"hook_event_name": "PreToolUse", "session_id": sesion, "tool_name": herramienta, "tool_input": entrada, "cwd": "/tmp"}


class DecidirTest(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(pretool, "es_sesion_de_io", lambda s: s == "io")
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def decision(self, *a, **k):
        r = pretool.decidir(evento(*a, **k))
        return r and r["hookSpecificOutput"]["permissionDecision"]

    def test_git_push_pregunta(self):
        self.assertEqual(self.decision("Bash", {"command": "git push origin main"}), "ask")

    def test_correo_pregunta(self):
        self.assertEqual(self.decision("mcp__claude_ai_Gmail__send_message", {"to": ["a@b.c"], "subject": "x"}), "ask")

    def test_calendario_pregunta(self):
        self.assertEqual(self.decision("mcp__claude_ai_Google_Calendar__create_event", {"summary": "x"}), "ask")

    def test_comando_libre_pasa(self):
        self.assertIsNone(self.decision("Bash", {"command": "ls -la"}))

    def test_otra_sesion_no_se_toca(self):
        self.assertIsNone(self.decision("Bash", {"command": "git push"}, sesion="otra"))


if __name__ == "__main__":
    unittest.main()
