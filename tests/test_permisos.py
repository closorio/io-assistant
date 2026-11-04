import fcntl
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import asistente  # noqa: E402
import permisos  # noqa: E402
from comun import RAIZ  # noqa: E402

# Formas reales de `claude agents --json`, observadas el 2026-11-04, con nombres inventados.
FONDO_PERMISO = {"id": "aaa11111", "kind": "background", "name": "fondo", "sessionId": "s-fondo", "cwd": "/tmp/f",
                 "pid": 10, "state": "blocked", "status": "waiting", "waitingFor": "permission prompt"}
FONDO_TRABAJANDO = {"id": "bbb", "kind": "background", "name": "ocupada", "sessionId": "s-oc", "cwd": "/tmp/o",
                    "pid": 11, "state": "working", "status": "busy", "waitingFor": None}
FONDO_SIN_PROCESO = {"id": "ccc", "kind": "background", "name": "residuo", "sessionId": "s-re", "cwd": "/tmp/r",
                     "pid": None, "state": "blocked", "status": None, "waitingFor": None}
FONDO_TERMINADO = {"id": "ddd", "kind": "background", "name": "fin", "sessionId": "s-fin", "cwd": "/tmp/d",
                   "pid": None, "state": "done", "status": None, "waitingFor": None}
INTERACTIVA_PREGUNTA = {"kind": "interactive", "name": "ventana", "sessionId": "s-ven", "cwd": "/tmp/v", "pid": 12,
                        "status": "waiting", "waitingFor": "input needed"}
INTERACTIVA_LIBRE = {"kind": "interactive", "name": "libre", "sessionId": "s-li", "cwd": "/tmp/l", "pid": 13,
                     "status": "idle", "waitingFor": None}


class PendientesTest(unittest.TestCase):
    def test_solo_quien_espera_de_verdad(self):
        lista = [FONDO_PERMISO, FONDO_TRABAJANDO, FONDO_SIN_PROCESO, FONDO_TERMINADO, INTERACTIVA_PREGUNTA,
                 INTERACTIVA_LIBRE]
        self.assertEqual([p["nombre"] for p in permisos.pendientes(lista)], ["fondo", "ventana"])

    def test_motivos_en_llano(self):
        por_nombre = {p["nombre"]: p["motivo"] for p in permisos.pendientes([FONDO_PERMISO, INTERACTIVA_PREGUNTA])}
        self.assertEqual(por_nombre, {"fondo": "un permiso", "ventana": "una respuesta"})

    def test_bloqueada_viva_sin_motivo_no_se_presenta_como_permiso(self):
        viva = dict(FONDO_SIN_PROCESO, pid=99)
        self.assertEqual(permisos.pendientes([viva])[0]["motivo"], "algo")

    def test_motivo_desconocido_no_se_repite_literal(self):
        rara = dict(FONDO_PERMISO, waitingFor="rm -rf /datos del cliente")
        self.assertEqual(permisos.pendientes([rara])[0]["motivo"], "algo")

    def test_nunca_expone_mas_que_nombre_carpeta_y_motivo(self):
        con_extra = dict(FONDO_PERMISO, command="curl secreto")
        self.assertEqual(set(permisos.pendientes([con_extra])[0]), {"clave", "nombre", "carpeta", "motivo"})


class TransicionTest(unittest.TestCase):
    P = {"clave": "s|un permiso", "nombre": "fondo", "carpeta": "/tmp/f", "motivo": "un permiso"}

    def test_avisa_una_sola_vez_al_aparecer(self):
        estado, avisos = permisos.transicion({}, [self.P], 0)
        self.assertEqual(len(avisos), 1)
        estado, avisos = permisos.transicion(estado, [self.P], 15)
        self.assertEqual(avisos, [])

    def test_recordatorios_cada_diez_minutos_y_tres_como_maximo(self):
        estado, avisos = permisos.transicion({}, [self.P], 0)
        total = 0
        for t in range(15, 7200, 15):
            estado, avisos = permisos.transicion(estado, [self.P], t)
            total += len(avisos)
        self.assertEqual(total, 3)

    def test_se_calla_al_resolverse_y_vuelve_a_avisar_si_reaparece_tras_la_gracia(self):
        estado, _ = permisos.transicion({}, [self.P], 0)
        estado, avisos = permisos.transicion(estado, [], 15)
        self.assertEqual(avisos, [])
        estado, _ = permisos.transicion(estado, [], 15 + permisos.GRACIA + 1)
        self.assertEqual(estado, {})
        _, avisos = permisos.transicion(estado, [self.P], 200)
        self.assertEqual(len(avisos), 1)

    def test_parpadeo_dentro_de_la_gracia_no_repite_voz(self):
        estado, _ = permisos.transicion({}, [self.P], 0)
        estado, _ = permisos.transicion(estado, [], 15)
        _, avisos = permisos.transicion(estado, [self.P], 30)
        self.assertEqual(avisos, [])

    def test_cambio_de_motivo_es_un_aviso_nuevo(self):
        estado, _ = permisos.transicion({}, [self.P], 0)
        otro = dict(self.P, clave="s|una respuesta", motivo="una respuesta")
        _, avisos = permisos.transicion(estado, [otro], 15)
        self.assertEqual(len(avisos), 1)

    def test_frase_sin_detalles(self):
        self.assertEqual(permisos.frase(self.P), "La sesión fondo espera un permiso.")


class LeerTest(unittest.TestCase):
    def ejecutar(self, rc, salida):
        r = mock.Mock(returncode=rc, stdout=salida)
        with mock.patch.object(permisos.subprocess, "run", return_value=r), \
                mock.patch.object(permisos, "claude", lambda: "claude"):
            return permisos.leer()

    def test_lista_vacia_no_es_un_fallo(self):
        self.assertEqual(self.ejecutar(0, "[]"), [])

    def test_fallo_devuelve_none_para_no_dar_todo_por_resuelto(self):
        self.assertIsNone(self.ejecutar(1, ""))
        self.assertIsNone(self.ejecutar(0, "no es json"))
        self.assertIsNone(self.ejecutar(0, '{"no": "es lista"}'))

    def test_excepcion_del_proceso_devuelve_none(self):
        with mock.patch.object(permisos.subprocess, "run", side_effect=OSError), \
                mock.patch.object(permisos, "claude", lambda: "claude"):
            self.assertIsNone(permisos.leer())


class CicloTest(unittest.TestCase):
    def test_un_fallo_de_lectura_conserva_el_estado(self):
        estado, _ = permisos.transicion({}, permisos.pendientes([FONDO_PERMISO]), 0)
        nuevo, avisos = permisos.ciclo(estado, None, 15)
        self.assertEqual((nuevo, avisos), (estado, []))

    def test_no_avisa_por_la_propia_shiri(self):
        with mock.patch.object(permisos, "es_sesion_de_io", lambda s: s == "s-ven"):
            _, avisos = permisos.ciclo({}, [INTERACTIVA_PREGUNTA, FONDO_PERMISO], 0)
        self.assertEqual([a["nombre"] for a in avisos], ["fondo"])


class ListarTest(unittest.TestCase):
    def salida(self, lista, *args):
        b = io.StringIO()
        with mock.patch.object(permisos, "leer", lambda: lista), redirect_stdout(b):
            codigo = permisos.main(list(args))
        return codigo, b.getvalue()

    def test_json(self):
        _, s = self.salida([FONDO_PERMISO], "--json")
        self.assertEqual(json.loads(s)[0]["motivo"], "un permiso")

    def test_nadie_espera(self):
        codigo, s = self.salida([INTERACTIVA_LIBRE])
        self.assertEqual(codigo, 0)
        self.assertIn("nadie", s)

    def test_fallo_de_lectura_no_dice_que_nadie_espera(self):
        codigo, s = self.salida(None)
        self.assertEqual(codigo, 1)
        self.assertNotIn("nadie", s)


class RevisionTest(unittest.TestCase):
    """Fallos hallados en la revisión independiente."""
    P = TransicionTest.P

    def test_corte_largo_de_lectura_no_repite_aviso_ni_reinicia_el_tope(self):
        estado, _ = permisos.transicion({}, [self.P], 0)
        estado["s|un permiso"]["recordatorios"] = 2
        for t in (30, 60, 90):
            estado, _ = permisos.ciclo(estado, None, t)
        with mock.patch.object(permisos, "pendientes", lambda _: [self.P]), \
                mock.patch.object(permisos, "es_sesion_de_io", lambda s: False):
            estado, avisos = permisos.ciclo(estado, [FONDO_PERMISO], 105)
        self.assertEqual(avisos, [])
        self.assertEqual(estado["s|un permiso"]["recordatorios"], 2)

    def test_intervalo_mayor_que_la_gracia_no_avisa_en_cada_vuelta(self):
        estado, avisos = permisos.transicion({}, [self.P], 0)
        total = len(avisos)
        for t in (90, 180, 270):
            estado, avisos = permisos.transicion(estado, [self.P], t)
            total += len(avisos)
        self.assertEqual(total, 1)

    def test_tope_agotado_no_silencia_un_permiso_nuevo_encadenado(self):
        estado, _ = permisos.transicion({}, [self.P], 0)
        for t in range(15, 2401, 15):
            estado, _ = permisos.transicion(estado, [self.P], t)
        self.assertEqual(estado[self.P["clave"]]["recordatorios"], permisos.MAX_RECORDATORIOS)
        estado, _ = permisos.transicion(estado, [], 2415)
        total = 0
        for t in range(2430, 2430 + permisos.RECORDATORIO + 1, 15):
            estado, avisos = permisos.transicion(estado, [self.P], t)
            total += len(avisos)
            if t == 2430:
                self.assertEqual(avisos, [])  # la cadena sigue callada al reaparecer...
        self.assertEqual(total, 1)  # ...pero vuelve a recordarse a los 10 min

    def test_entradas_raras_no_rompen(self):
        rara = dict(FONDO_PERMISO, waitingFor=["lista"])
        lista = permisos.pendientes([1, None, rara])
        self.assertEqual([p["motivo"] for p in lista], ["algo"])

    def test_una_excepcion_no_mata_la_vuelta(self):
        for fallo in ("leer", "es_sesion_de_io"):
            with mock.patch.object(permisos, "leer", lambda: [FONDO_PERMISO]), \
                    mock.patch.object(permisos, "es_sesion_de_io", lambda s: False), \
                    mock.patch.object(permisos, fallo, mock.Mock(side_effect=AttributeError)):
                self.assertEqual(permisos.vuelta({"x": 1}, voz=False), {"x": 1})

    def test_fallo_al_avisar_no_mata_la_vuelta_ni_a_los_demas(self):
        otra = dict(FONDO_PERMISO, sessionId="s-otra", name="otra")
        hablar = mock.Mock(side_effect=OSError)
        with mock.patch.object(permisos, "leer", lambda: [FONDO_PERMISO, otra]), \
                mock.patch.object(permisos, "es_sesion_de_io", lambda s: False), \
                mock.patch.object(permisos, "aviso", hablar), redirect_stdout(io.StringIO()):
            permisos.vuelta({}, voz=True)
        self.assertEqual(hablar.call_count, 2)

    def test_el_vigilante_muere_con_su_padre_real(self):
        with tempfile.TemporaryDirectory() as d:
            padre = subprocess.Popen(["sleep", "60"])
            hijo = subprocess.Popen([sys.executable, str(RAIZ / "bin" / "narrador"), "permisos", "vigilar", "--sin-voz",
                                     "--intervalo", "0.2", "--padre", str(padre.pid)],
                                    env=dict(os.environ, XDG_DATA_HOME=d), stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                time.sleep(1)
                self.assertIsNone(hijo.poll(), "debe seguir vivo mientras viva el padre")
                padre.kill()
                padre.wait()
                self.assertEqual(hijo.wait(timeout=20), 0)
            finally:
                padre.kill()
                hijo.kill()
                hijo.wait()

    def test_relanzar_espera_al_vigilante_anterior_en_vez_de_quedarse_sin_ninguno(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(permisos, "RUNTIME", Path(d)), \
                mock.patch.object(permisos, "CERROJO", Path(d) / "c.lock"), \
                mock.patch.object(permisos, "ESPERA_CERROJO", 5), \
                mock.patch.object(permisos, "padre_vivo", lambda pid: False):
            viejo = open(Path(d) / "c.lock", "a")
            fcntl.flock(viejo, fcntl.LOCK_EX)
            threading.Timer(0.3, viejo.close).start()
            inicio = time.monotonic()
            self.assertEqual(permisos.vigilar(voz=False, padre=1), 0)
            self.assertGreater(time.monotonic() - inicio, 0.2)


class AsistenteEstadoTest(unittest.TestCase):
    def test_vivas_muestra_estado_y_motivo_en_ambas_formas(self):
        b = io.StringIO()
        with mock.patch.object(asistente, "agentes", lambda todas=False: [FONDO_SIN_PROCESO, INTERACTIVA_PREGUNTA]), \
                redirect_stdout(b):
            asistente.vivas()
        self.assertIn("residuo  blocked", b.getvalue())
        self.assertIn("ventana  waiting (input needed)", b.getvalue())

    def test_esperar_no_informa_none_como_estado(self):
        t = {"nombre": "x", "ruta": "/tmp", "inicio": 0, "contrato": False, "tipo": "bg"}
        b = io.StringIO()
        vivo = {"name": "x", "status": None, "state": "blocked"}
        with mock.patch.object(asistente, "_buscar_trabajador", lambda n: t), \
                mock.patch.object(asistente, "agentes", lambda todas=False: [vivo]), \
                mock.patch.object(asistente, "ESPERA_AGENTES", 0), mock.patch.object(asistente, "ESPERA_SONDEO", 0), \
                redirect_stdout(b):
            asistente.esperar("x")
        self.assertIn("blocked sin informe", b.getvalue())
        self.assertNotIn("None", b.getvalue())


if __name__ == "__main__":
    unittest.main()
