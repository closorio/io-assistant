"""Pruebas de quién puede cortar la voz de Ío. Ejecuta: python3 -m unittest discover -s tests

Las del oído necesitan numpy (el python del venv: ~/.local/share/narrador/venv/bin/python).
"""

import json
import socket
import sys
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import daemon  # noqa: E402
import hook  # noqa: E402

try:
    import numpy as np
    import oido
except ImportError:  # sin el venv
    oido = None

AVISO_MONITOR = ('<task-notification>\n<task-id>b5y2yibao</task-id>\n<summary>Monitor event: "parte cada 10 min del '
                 'mundo simulado"</summary>\n<event>[parte10] 17:52 trabajando</event>\n</task-notification>')


def ejecutar_hook(datos: dict) -> list:
    """Corre el hook con `datos` por stdin; devuelve las órdenes que habría enviado al daemon."""
    enviadas = []
    with mock.patch.object(hook, "enviar", lambda orden, *a, **k: enviadas.append(orden)), \
            mock.patch.object(hook, "anotar", lambda mensaje: None), \
            mock.patch.object(sys, "stdin", mock.Mock(read=lambda *a: json.dumps(datos))):
        hook.main()
    return enviadas


class Hook(unittest.TestCase):
    def test_aviso_de_monitor_no_calla(self):
        self.assertEqual(ejecutar_hook({"hook_event_name": "UserPromptSubmit", "session_id": "io",
                                        "prompt": AVISO_MONITOR}), [])

    def test_tarea_en_segundo_plano_no_calla(self):
        prompt = "  <task-notification> <task-id>b9k</task-id> <status>completed</status> </task-notification>"
        self.assertEqual(ejecutar_hook({"hook_event_name": "UserPromptSubmit", "session_id": "io", "prompt": prompt}), [])

    def test_lo_que_escribes_calla_solo_tu_sesion(self):
        ordenes = ejecutar_hook({"hook_event_name": "UserPromptSubmit", "session_id": "io", "prompt": "alto"})
        self.assertEqual(len(ordenes), 1)
        self.assertEqual((ordenes[0]["cmd"], ordenes[0]["sesion"]), ("vaciar", "io"))
        self.assertIn("has escrito «alto»", ordenes[0]["origen"])

    def test_mencionar_un_aviso_no_es_un_aviso(self):
        self.assertFalse(hook.es_aviso("explícame qué es un <task-notification>"))
        self.assertEqual(hook.resumen_aviso(AVISO_MONITOR), 'Monitor event: "parte cada 10 min del mundo simulado"')


class ProcesoFalso:
    def __init__(self):
        self.terminado = False

    def poll(self):
        return 0 if self.terminado else None

    def terminate(self):
        self.terminado = True


class Daemon(unittest.TestCase):
    def setUp(self):
        self.parches = [mock.patch.object(daemon, "log", lambda m: self.log.append(m)),
                        mock.patch.object(daemon, "cola", deque()),
                        mock.patch.dict(daemon.estado, {"proc": None, "motor": None, "cortada": None,
                                                        "sesion": None, "generacion": 0})]
        self.log = []
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def sonando(self, sesion):
        daemon.estado["proc"], daemon.estado["sesion"] = ProcesoFalso(), sesion

    def test_el_corte_guarda_quien_lo_ordena(self):
        self.sonando("io")
        daemon.vaciar(motivo="vaciar · oído: corte por voz")
        self.assertTrue(daemon.estado["proc"].terminado)
        self.assertEqual(daemon.estado["cortada"], "vaciar · oído: corte por voz")

    def test_vaciar_de_otra_sesion_no_corta(self):
        self.sonando("io")
        daemon.cola.extend([("de io", 0.0, "io"), ("del mentor", 0.0, "mentor")])
        daemon.vaciar("mentor", "vaciar · hook")
        self.assertFalse(daemon.estado["proc"].terminado)
        self.assertEqual([f[0] for f in daemon.cola], ["de io"])
        self.assertIn("vaciadas 1 frase(s) en cola ← vaciar · hook", self.log)

    def test_vaciar_de_su_sesion_corta(self):
        self.sonando("io")
        daemon.vaciar("io", "vaciar · hook")
        self.assertEqual(daemon.estado["cortada"], "vaciar · hook")

    def test_quien_da_origen_sesion_y_proceso(self):
        a, b = socket.socketpair()
        with a, b:
            texto = daemon.quien(a, {"cmd": "vaciar", "origen": "oído: frase tuya", "sesion": "655f6dc2-225c"})
        self.assertTrue(texto.startswith("oído: frase tuya · sesión 655f6dc2 · pid "), texto)

    def test_procesar_pasa_el_motivo(self):
        self.sonando(None)
        daemon.procesar({"cmd": "saltar"}, "pid 1 narrador saltar")
        self.assertEqual(daemon.estado["cortada"], "saltar · pid 1 narrador saltar")


@unittest.skipIf(oido is None, "necesita numpy (el python del venv)")
class Oido(unittest.TestCase):
    def setUp(self):
        self.o = oido.Oido.__new__(oido.Oido)  # sin cargar Whisper ni el micrófono
        self.o.cfg = {"escucha": {"nombre": "Ío", "ventana": 300, "agrupar": 0, "corte": 0.25, "silencio_fin": 0.8,
                                  "interrumpir": True, "huella": True, "huella_umbral": 0.5}}
        self.o.hablando, self.o.hablo_io, self.o.ventana_hasta, self.o.ventana_abierta = True, 0.0, 0.0, False
        self.o.despierta = oido.re.compile(r"\b(?:h?io)\b")
        self.o.en_voz = self.o.transcribiendo = False
        self.o.frases = oido.queue.Queue()
        self.o.pendiente, self.o.pendiente_huella = [], None
        self.o.pendiente_desde = self.o.pendiente_hasta = 0.0
        self.o.cerrojo_parrafo = oido.threading.Lock()
        self.callado, self.publicado = [], []
        self.parches = [mock.patch.object(oido.Oido, "callar_a_io", staticmethod(lambda m: self.callado.append(m))),
                        mock.patch.object(oido, "publicar", lambda r: self.publicado.append(r)),
                        mock.patch.object(oido, "sonar", lambda *a, **k: None),
                        mock.patch.object(oido, "log", lambda m: None)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def con_huella(self, parecido):
        return mock.patch.object(self.o, "parecido", lambda audio: parecido)

    def test_corte_por_voz_solo_con_tu_huella(self):
        audio = np.zeros(16000, np.float32)
        for parecido, corta in ((None, False), (0.08, False), (0.49, False), (0.72, True)):
            self.callado.clear()
            with self.con_huella(parecido):
                self.o.cortar_si_eres_tu(audio, 0.9)
            self.assertEqual(bool(self.callado), corta, parecido)
        self.assertIn("huella 0.72", self.callado[0])
        self.assertIn("voz 0.90", self.callado[0])

    def test_frase_ajena_no_calla_ni_llega(self):
        with self.con_huella(0.06), mock.patch.object(self.o, "_whisper", lambda *a: ("Ío, suscríbete al canal", 10)):
            self.o.transcribir(np.zeros(16000, np.float32), 0.0, 0.8)
        self.assertEqual((self.callado, self.publicado), ([], []))

    def test_frase_tuya_calla_y_llega(self):
        with self.con_huella(0.81), mock.patch.object(self.o, "_whisper", lambda *a: ("Ío, para", 10)):
            self.o.transcribir(np.zeros(16000, np.float32), 0.0, 0.8)
        self.assertEqual(len(self.callado), 1)
        self.assertEqual(self.publicado, [{"texto": "Ío, para"}])

    def test_sin_huella_la_frase_llega_pero_no_calla(self):
        with self.con_huella(None), mock.patch.object(self.o, "_whisper", lambda *a: ("Ío, para", 10)):
            self.o.transcribir(np.zeros(16000, np.float32), 0.0, 0.8)
        self.assertEqual((self.callado, self.publicado), ([], [{"texto": "Ío, para"}]))

    def test_parrafo_calla_solo_si_alguna_frase_era_tuya(self):
        for huella, calla in ((None, False), (0.7, True)):
            self.callado.clear()
            self.o.pendiente, self.o.pendiente_huella = ["Ío, mira esto"], huella
            self.o.soltar_parrafo(forzar=True)
            self.assertEqual(bool(self.callado), calla)

    def test_un_parrafo_tuyo_en_camino_mantiene_la_ventana(self):
        ahora = oido.time.monotonic()
        self.o.ventana_abierta, self.o.ventana_hasta, self.o.hablando = True, ahora + 1, False
        self.o.pendiente = ["sigo con lo de antes"]  # frases ya confirmadas por la huella, esperando a juntarse
        with mock.patch.object(self.o, "io_trabajando", lambda: False):
            self.o.mantener_ventana()
        self.assertGreater(self.o.ventana_hasta, ahora + 290)  # el plazo (300) vuelve a estar entero

    def test_la_voz_cruda_no_mantiene_la_ventana(self):
        """Un vídeo o alguien al lado activan el VAD, pero no son tu huella: la cuenta sigue corriendo."""
        ahora = oido.time.monotonic()
        self.o.ventana_abierta, self.o.ventana_hasta, self.o.hablando, self.o.en_voz = True, ahora + 1, False, True
        with mock.patch.object(self.o, "io_trabajando", lambda: False):
            self.o.mantener_ventana()
        self.assertAlmostEqual(self.o.ventana_hasta, ahora + 1, delta=0.1)

    def test_una_frase_tuya_confirmada_renueva_la_ventana(self):
        ahora = oido.time.monotonic()
        self.o.ventana_hasta = ahora + 1
        with self.con_huella(0.8), mock.patch.object(self.o, "_whisper", lambda *a: ("y otra cosa más", 10)):
            self.o.transcribir(np.zeros(16000, np.float32), ahora, 0.8, inicio=ahora - 2)
        self.assertGreater(self.o.ventana_hasta, ahora + 290)

    def test_tu_voz_no_abre_una_ventana_cerrada(self):
        self.o.ventana_abierta, self.o.ventana_hasta, self.o.hablando, self.o.en_voz = False, 0.0, False, True
        with mock.patch.object(self.o, "io_trabajando", lambda: False):
            self.o.mantener_ventana()
        self.assertEqual((self.o.ventana_abierta, self.o.ventana_hasta), (False, 0.0))

    def test_la_ventana_se_cierra_con_todo_parado(self):
        avisos = []
        self.o.ventana_abierta, self.o.ventana_hasta, self.o.hablando, self.o.en_voz = True, oido.time.monotonic() - 1, False, False
        with mock.patch.object(self.o, "io_trabajando", lambda: False), \
                mock.patch.object(self.o, "avisar_ventana_cerrada", lambda: avisos.append(1)):
            self.o.mantener_ventana()
        self.assertEqual((self.o.ventana_abierta, avisos), (False, [1]))

    def test_frase_que_empieza_dentro_de_la_ventana_vale_aunque_acabe_fuera(self):
        ahora = oido.time.monotonic()
        self.o.ventana_hasta = ahora + 1
        with self.con_huella(None), mock.patch.object(self.o, "_whisper", lambda *a: ("y además mira el log", 10)):
            self.o.transcribir(np.zeros(16000, np.float32), ahora + 5, 0.8, inicio=ahora)
        self.assertEqual(self.publicado, [{"texto": "y además mira el log"}])

    def test_trocear_no_corta_directamente(self):
        """Voz sobre Ío con `interrumpir`: no se le corta en el bucle del VAD, se comprueba la huella aparte."""
        comprobaciones = []
        vad = mock.Mock(side_effect=lambda bloque: 0.9)
        bloques = [np.zeros(oido.BLOQUE, np.float32)] * 40
        hilo_inmediato = mock.Mock(side_effect=lambda target, args, daemon: mock.Mock(start=lambda: target(*args)))
        with mock.patch.object(self.o, "cortar_si_eres_tu", lambda audio, voz: comprobaciones.append(voz)), \
                mock.patch.object(oido.threading, "Thread", hilo_inmediato), \
                mock.patch.object(self.o, "_soltar_frase", lambda *a: None):
            self.o.trocear(bloques, vad, mic=True)
        self.assertEqual(self.callado, [])
        self.assertEqual(len(comprobaciones), 1)  # una sola vez por frase
        self.assertAlmostEqual(comprobaciones[0], 0.9)

    def test_trocear_sin_interrumpir_no_comprueba(self):
        self.o.cfg["escucha"]["interrumpir"] = False
        comprobaciones = []
        with mock.patch.object(self.o, "cortar_si_eres_tu", lambda audio, voz: comprobaciones.append(voz)), \
                mock.patch.object(self.o, "_soltar_frase", lambda *a: None):
            self.o.trocear([np.zeros(oido.BLOQUE, np.float32)] * 40, mock.Mock(return_value=0.9), mic=True)
        self.assertEqual((comprobaciones, self.callado), ([], []))


if __name__ == "__main__":
    unittest.main()
