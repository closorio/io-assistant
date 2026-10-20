"""Pruebas de la grabación de la huella de voz (necesitan numpy: usa .runtime/venv-tests)."""

import fcntl
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

try:
    import huella
except ImportError:  # sin numpy
    huella = None


@unittest.skipIf(huella is None, "falta numpy")
class Grabar(unittest.TestCase):
    def test_dos_grabaciones_a_la_vez_no_se_pisan_la_pausa(self):
        """La segunda grabación debe negarse: si no, leería «pausa: true» como estado previo y dejaría el oído
        sin micrófono al terminar (pasó el 2026-10-20)."""
        with mock.patch.object(huella, "RUNTIME", Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))), \
                mock.patch.object(huella, "Huella", lambda: None), \
                mock.patch.object(huella, "leer_config") as leer, \
                mock.patch.object(huella, "guardar_config") as guardar:
            otra = open(huella.RUNTIME / "huella.lock", "w")
            fcntl.flock(otra, fcntl.LOCK_EX | fcntl.LOCK_NB)  # «otra» grabación en marcha
            with self.assertRaises(SystemExit):
                huella.grabar(1)
            self.assertFalse(leer.called)  # no llegó a tocar la configuración
            self.assertFalse(guardar.called)
            otra.close()

    def test_la_pausa_se_restaura_aunque_la_grabacion_falle(self):
        cfg = {"escucha": {"pausa": False}}
        with mock.patch.object(huella, "RUNTIME", Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))), \
                mock.patch.object(huella, "Huella", lambda: None), \
                mock.patch.object(huella, "leer_config", lambda: {"escucha": dict(cfg["escucha"])}), \
                mock.patch.object(huella, "guardar_config", lambda c: cfg.update(c)), \
                mock.patch.object(huella, "_grabar", mock.Mock(side_effect=OSError("sin micrófono"))):
            with self.assertRaises(OSError):
                huella.grabar(1)
        self.assertFalse(cfg["escucha"]["pausa"])


if __name__ == "__main__":
    unittest.main()
