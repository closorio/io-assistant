"""Pruebas del pipeline de voz del daemon (sintetizar la siguiente mientras suena la actual) y de
`narrador trabajador esperar`. Ejecuta: python3 -m unittest discover -s tests"""

import sys
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import asistente  # noqa: E402
import daemon  # noqa: E402


class MotorFalso:
    """Sintetiza en `tarda` s y «reproduce» con un proceso que dura `suena` s (sin audio)."""

    def __init__(self, tarda: float, suena: float):
        self.tarda, self.suena = tarda, suena
        self.sintetizadas: list[str] = []

    def preparar(self, texto):
        time.sleep(self.tarda)
        self.sintetizadas.append(texto)
        return ["sleep", str(self.suena)], None

    def cancelar(self):
        pass


class Pipeline(unittest.TestCase):
    """Los dos hilos del daemon se arrancan una sola vez para toda la clase (son hilos sin fin): cada prueba
    les cambia las colas, el motor y el log por debajo, y al terminar espera a que queden parados."""

    actual: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.permanentes = [mock.patch.object(daemon, "log", lambda m: cls.actual["log"].append(m)),
                           mock.patch.object(daemon, "motor", lambda nombre: cls.actual["motor"]),
                           mock.patch.object(daemon, "cadena", lambda principal: ["falso"])]
        for p in cls.permanentes:
            p.start()
        threading.Thread(target=daemon.sintetizador, daemon=True).start()
        threading.Thread(target=daemon.reproductor, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for p in cls.permanentes:
            p.stop()

    def setUp(self):
        self.motor = MotorFalso(tarda=0.15, suena=0.3)
        self.log = []
        Pipeline.actual = {"motor": self.motor, "log": self.log}
        self.parches = [mock.patch.object(daemon, "cola", deque()),
                        mock.patch.object(daemon, "preparadas", deque()),
                        mock.patch.object(daemon, "vaciados", {}),
                        mock.patch.dict(daemon.estado, {"proc": None, "motor": None, "cortada": None,
                                                        "sesion": None, "generacion": 0})]
        for p in self.parches:
            p.start()

    def tearDown(self):
        daemon.vaciar(motivo="fin de la prueba")
        fin = time.monotonic() + 3
        while time.monotonic() < fin and (daemon.cola or daemon.preparadas or daemon.estado["proc"] is not None):
            time.sleep(0.02)
        time.sleep(0.2)  # por si el sintetizador estaba a mitad de una frase
        for p in self.parches:
            p.stop()

    def decir(self, texto, sesion="io"):
        daemon.procesar({"cmd": "decir", "texto": texto, "sesion": sesion})

    def esperar_log(self, patron: str, n: int = 1, limite: float = 3.0):
        fin = time.monotonic() + limite
        while sum(patron in m for m in self.log) < n and time.monotonic() < fin:
            time.sleep(0.02)
        return [m for m in self.log if patron in m]

    def test_la_siguiente_se_sintetiza_mientras_suena_la_actual(self):
        self.decir("uno")
        self.decir("dos")
        self.decir("tres")
        sonadas = self.esperar_log("hasta_sonar=", 3)
        self.assertEqual(len(sonadas), 3, self.log)
        esperas = [int(m.split("hasta_sonar=")[1].split("ms")[0]) for m in sonadas]
        # La primera espera su síntesis (150 ms); las demás ya estaban listas cuando acabó la anterior,
        # así que su espera es la suma de lo que sonó antes, sin sumar una síntesis por frase.
        self.assertLess(esperas[0], 300, esperas)
        self.assertLess(esperas[2], 150 + 2 * 300 + 150, esperas)
        self.assertEqual(self.motor.sintetizadas, ["uno", "dos", "tres"])

    def test_no_se_adelanta_mas_de_una(self):
        for t in ("uno", "dos", "tres", "cuatro"):
            self.decir(t)
        time.sleep(0.4)  # suena «uno» (0,3 s) y «dos» está preparada; «tres» todavía no se ha sintetizado del todo
        self.assertLessEqual(len(self.motor.sintetizadas), 3, self.motor.sintetizadas)
        self.esperar_log("hasta_sonar=", 4)

    def test_vaciar_tira_lo_sintetizado_y_lo_que_se_sintetiza(self):
        self.decir("uno")
        self.decir("dos")
        self.decir("tres")
        time.sleep(0.2)  # «uno» suena, «dos» se está sintetizando
        daemon.vaciar("io", "vaciar · hook")
        time.sleep(0.6)
        self.assertEqual(len(self.esperar_log("hasta_sonar=")), 1)
        self.assertTrue(any("descartada antes de sonar «dos»" in m for m in self.log), self.log)
        self.assertTrue(any("vaciadas 1 frase(s) en cola" in m for m in self.log), self.log)
        self.assertEqual(daemon.estado["cortada"], "vaciar · hook")

    def test_vaciar_de_otra_sesion_deja_sonar_lo_mio(self):
        self.decir("del mentor", sesion="mentor")
        self.decir("de io", sesion="io")
        time.sleep(0.2)
        daemon.vaciar("io", "vaciar · hook")
        sonadas = self.esperar_log("hasta_sonar=")
        self.assertEqual(len(sonadas), 1)
        self.assertIn("«del mentor»", sonadas[0])
        self.assertIsNone(daemon.estado["cortada"])

    def test_lo_que_llega_despues_del_vaciado_suena(self):
        self.decir("vieja")
        daemon.vaciar("io", "vaciar · hook")
        self.decir("nueva")
        sonadas = self.esperar_log("hasta_sonar=")
        self.assertEqual(len(sonadas), 1)
        self.assertIn("«nueva»", sonadas[0])

    def test_estado_cuenta_cola_y_preparadas(self):
        self.motor.suena = 1.0
        for t in ("uno", "dos", "tres"):
            self.decir(t)
        time.sleep(0.45)
        e = daemon.procesar({"cmd": "estado"})
        self.assertTrue(e["hablando"])
        self.assertEqual(e["en_cola"], 2)
        daemon.vaciar(motivo="fin de la prueba")


class Esperar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.t = {"nombre": "io-prueba-010203", "ruta": str(self.tmp), "tarea": "probar", "contrato": True,
                  "modelo": "opus", "inicio": time.time() - 600, "tipo": "bg"}
        self.parches = [mock.patch.object(asistente, "_registro", lambda: [self.t]),
                        mock.patch.object(asistente, "_archivo_resultado", lambda nombre: self.tmp / f"{nombre}.md"),
                        mock.patch.object(asistente, "ESPERA_SONDEO", 0.05),
                        mock.patch.object(asistente, "INFORME_QUIETO", 0.0),
                        mock.patch.object(asistente, "ESPERA_AGENTES", 0.0)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def test_con_informe_imprime_el_resumen_de_una_vez(self):
        (self.tmp / "io-prueba-010203.md").write_text(
            "Resumen: Arreglé el fallo del login y los tests pasan.\nQueda pendiente el correo.\n\n## Pendiente\n- nada\n",
            encoding="utf-8")
        with mock.patch.object(asistente, "agentes", lambda todas=False: []), \
                mock.patch("builtins.print") as p:
            self.assertEqual(asistente.esperar("prueba"), 0)
        salida = p.call_args[0][0]
        self.assertTrue(salida.startswith("[trabajador io-prueba-010203] terminado"), salida)
        self.assertIn("Resumen: Arreglé el fallo del login y los tests pasan. Queda pendiente el correo.", salida)
        self.assertIn("Informe completo:", salida)

    def test_sin_informe_y_sin_actividad_lo_dice(self):
        with mock.patch.object(asistente, "agentes", lambda todas=False: [{"name": "io-prueba-010203", "status": "idle"}]), \
                mock.patch("builtins.print") as p:
            self.assertEqual(asistente.esperar("io-prueba-010203"), 1)
        self.assertIn("idle sin informe", p.call_args[0][0])

    def test_sigue_trabajando_al_agotar_el_maximo(self):
        with mock.patch.object(asistente, "agentes", lambda todas=False: [{"name": "io-prueba-010203", "status": "busy"}]), \
                mock.patch("builtins.print") as p:
            self.assertEqual(asistente.esperar("io-prueba-010203", maximo_min=0.001), 0)
        self.assertIn("sigue trabajando", p.call_args[0][0])

    def test_resumen_voz_para_antes_del_primer_titulo(self):
        self.assertEqual(asistente.resumen_voz("# Informe\nHecho A.\nHecho B.\n\n## Pendiente\nC"), "Hecho A. Hecho B.")


class EntornoLimpio(unittest.TestCase):
    def test_quita_las_variables_de_la_sesion_y_deja_el_resto(self):
        with mock.patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "x", "CLAUDECODE": "1", "AI_AGENT": "1",
                                            "CLAUDE_CONFIG_DIR": "/c", "HOME": "/h"}, clear=True):
            e = asistente.entorno_limpio()
        self.assertEqual(e, {"CLAUDE_CONFIG_DIR": "/c", "HOME": "/h", "NARRADOR_IO": "1"})


if __name__ == "__main__":
    unittest.main()
