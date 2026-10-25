import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import decisiones  # noqa: E402

RAZON = "el usuario quiere migrar a Postgres antes del viernes"


def evento(herramienta, entrada, sesion="s1", cwd="/home/u/proyectos/buscasa"):
    return {"hook_event_name": "PreToolUse", "session_id": sesion, "tool_name": herramienta,
            "tool_input": entrada, "cwd": cwd}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raiz = Path(self.tmp.name)
        self.planes = raiz / "plans"
        self.planes.mkdir()
        self.dir = raiz / "decisiones"
        self.parches = [
            mock.patch.object(decisiones, "PLANES", self.planes),
            mock.patch.object(decisiones, "DIR", self.dir),
            mock.patch.object(decisiones, "REGISTRO", self.dir / "decisiones.jsonl"),
            mock.patch.object(decisiones, "CONFIG", self.dir / "config.json"),
        ]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.tmp.cleanup()

    def decision(self, *a, **k):
        r = decisiones.decidir(evento(*a, **k))
        return r and r["hookSpecificOutput"]["permissionDecision"]

    def registro(self):
        return decisiones.leer_registro()

    def plan(self, nombre="plan-a.md"):
        return str(self.planes / nombre)


class PlanTest(Base):
    def test_escribir_plan_sin_razon_bloquea_y_no_apunta(self):
        r = decisiones.decidir(evento("Write", {"file_path": self.plan(), "content": "# Migrar\n\n1. Hacer cosas"}))
        self.assertEqual(r["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("Por qué:", r["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.registro(), [])

    def test_escribir_plan_con_razon_pasa_y_apunta(self):
        contenido = f"# Migrar a Postgres\n\nPor qué: {RAZON}\n\n1. Hacer cosas"
        self.assertIsNone(self.decision("Write", {"file_path": self.plan(), "content": contenido}))
        [d] = self.registro()
        self.assertEqual(d["razon"], RAZON)
        self.assertEqual(d["tipo"], "plan_escribir")
        self.assertEqual(d["sesion"], "s1")
        self.assertEqual(d["proyecto"], "buscasa")
        self.assertEqual(d["herramienta"], "Write")
        self.assertEqual(d["fuente"], "marcador")
        self.assertIn("Migrar a Postgres", d["accion"])
        self.assertEqual(d["v"], decisiones.VERSION)
        self.assertRegex(d["fecha"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_razon_en_comentario_html(self):
        contenido = f"# Plan\n<!-- Por qué: {RAZON} -->\n"
        self.assertIsNone(self.decision("Write", {"file_path": self.plan(), "content": contenido}))
        self.assertEqual(self.registro()[0]["razon"], RAZON)

    def test_razon_demasiado_corta_no_vale(self):
        self.assertEqual(self.decision("Write", {"file_path": self.plan(), "content": "Por qué: sí\n"}), "deny")

    def test_editar_plan_pide_razon_en_new_string(self):
        entrada = {"file_path": self.plan(), "old_string": "a", "new_string": "b"}
        self.assertEqual(self.decision("Edit", entrada), "deny")
        entrada["new_string"] = f"b\n<!-- Porque: {RAZON} -->"
        self.assertIsNone(self.decision("Edit", entrada))
        self.assertEqual(self.registro()[0]["tipo"], "plan_editar")

    def test_editar_plan_se_puede_desactivar(self):
        self.dir.mkdir()
        (self.dir / "config.json").write_text(json.dumps({"editar_plan": False}))
        self.assertIsNone(self.decision("Edit", {"file_path": self.plan(), "old_string": "a", "new_string": "b"}))

    def test_archivo_porque_junto_al_plan_se_consume(self):
        lado = Path(self.plan() + ".porque")
        lado.write_text(RAZON + "\n")
        self.assertIsNone(self.decision("Write", {"file_path": self.plan(), "content": "# Plan"}))
        [d] = self.registro()
        self.assertEqual((d["razon"], d["fuente"]), (RAZON, "archivo"))
        self.assertFalse(lado.exists())
        self.assertEqual(self.decision("Write", {"file_path": self.plan(), "content": "# Plan"}), "deny")

    def test_escribir_el_archivo_porque_no_pide_razon(self):
        self.assertIsNone(self.decision("Write", {"file_path": self.plan() + ".porque", "content": RAZON}))

    def test_archivo_fuera_de_planes_pasa(self):
        self.assertIsNone(self.decision("Write", {"file_path": "/tmp/plan.md", "content": "# x"}))
        self.assertEqual(self.registro(), [])

    def test_ruta_con_virgulilla_y_relativa(self):
        with mock.patch.dict(os.environ, {"HOME": self.tmp.name}):
            self.assertEqual(self.decision("Write", {"file_path": "~/plans/x.md", "content": "# x"}), "deny")


class SalirDelPlanTest(Base):
    def test_exit_plan_mode_sin_razon_bloquea(self):
        self.assertEqual(self.decision("ExitPlanMode", {"plan": "# Plan\n1. algo"}), "deny")

    def test_exit_plan_mode_con_razon_en_el_texto(self):
        self.assertIsNone(self.decision("ExitPlanMode", {"plan": f"# Plan de migración\nPor qué: {RAZON}"}))
        [d] = self.registro()
        self.assertEqual(d["tipo"], "plan_aprobar")
        self.assertIn("Plan de migración", d["accion"])

    def test_exit_plan_mode_sin_texto_usa_la_razon_del_plan_reciente(self):
        Path(self.plan()).write_text(f"# Plan\nPor qué: {RAZON}\n")
        self.assertIsNone(self.decision("ExitPlanMode", {}))
        self.assertEqual(self.registro()[0]["fuente"], "plan")

    def test_exit_plan_mode_ignora_un_plan_viejo(self):
        p = Path(self.plan())
        p.write_text(f"Por qué: {RAZON}\n")
        os.utime(p, (0, 0))
        self.assertEqual(self.decision("ExitPlanMode", {}), "deny")


class TrabajadorTest(Base):
    def test_lanzar_trabajador_sin_razon_bloquea(self):
        r = decisiones.decidir(evento("Bash", {"command": 'narrador trabajador lanzar holo-ui "revisa los tests"'}))
        self.assertEqual(r["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("# Por qué:", r["hookSpecificOutput"]["permissionDecisionReason"])

    def test_lanzar_trabajador_con_comentario_pasa(self):
        cmd = f'narrador trabajador lanzar holo-ui "revisa los tests"  # Por qué: {RAZON}'
        self.assertIsNone(self.decision("Bash", {"command": cmd}))
        [d] = self.registro()
        self.assertEqual(d["tipo"], "trabajador")
        self.assertIn("narrador trabajador lanzar", d["accion"])

    def test_claude_bg_pide_razon(self):
        self.assertEqual(self.decision("Bash", {"command": "cd ~/x && claude --bg 'haz algo'"}), "deny")

    def test_comandos_normales_pasan(self):
        for cmd in ("ls -la", "narrador trabajador lista", "git status", "claude plugin update narrador@agent-voice"):
            self.assertIsNone(self.decision("Bash", {"command": cmd}), cmd)

    def test_herramienta_extra_configurable(self):
        self.assertIsNone(self.decision("Agent", {"prompt": "busca algo"}))
        self.dir.mkdir()
        (self.dir / "config.json").write_text(json.dumps({"herramientas": ["Agent"]}))
        self.assertEqual(self.decision("Agent", {"prompt": "busca algo"}), "deny")
        self.assertIsNone(self.decision("Agent", {"prompt": f"busca algo\nPor qué: {RAZON}"}))
        self.assertEqual(self.registro()[0]["tipo"], "otra")


class GeneralTest(Base):
    def test_otras_herramientas_y_eventos_no_se_tocan(self):
        self.assertIsNone(self.decision("Read", {"file_path": self.plan()}))
        self.assertIsNone(decisiones.decidir({"hook_event_name": "PostToolUse", "tool_name": "ExitPlanMode", "tool_input": {}}))

    def test_desactivado_no_bloquea(self):
        self.dir.mkdir()
        (self.dir / "config.json").write_text(json.dumps({"activo": False}))
        self.assertIsNone(self.decision("ExitPlanMode", {"plan": "x"}))

    def test_registro_es_append_only_y_una_linea_por_decision(self):
        for i in range(3):
            self.decision("ExitPlanMode", {"plan": f"# Plan {i}\nPor qué: {RAZON} {i}"})
        lineas = (self.dir / "decisiones.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(l)["razon"] for l in lineas], [f"{RAZON} {i}" for i in range(3)])

    def test_main_hook_imprime_el_bloqueo_en_json(self):
        datos = json.dumps(evento("ExitPlanMode", {"plan": "x"}))
        salida = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(datos)), redirect_stdout(salida):
            decisiones.main_hook()
        self.assertEqual(json.loads(salida.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")


class CliTest(Base):
    def setUp(self):
        super().setUp()
        self.decision("ExitPlanMode", {"plan": f"# Uno\nPor qué: {RAZON}"}, sesion="aaaa1111", cwd="/x/buscasa")
        self.decision("ExitPlanMode", {"plan": f"# Dos\nPor qué: {RAZON}"}, sesion="bbbb2222", cwd="/x/holo-ui")

    def cli(self, *args):
        salida = io.StringIO()
        with redirect_stdout(salida):
            codigo = decisiones.main(list(args))
        return codigo, salida.getvalue()

    def test_listar(self):
        codigo, texto = self.cli("listar")
        self.assertEqual(codigo, 0)
        self.assertIn("buscasa", texto)
        self.assertIn(f"por qué: {RAZON}", texto)

    def test_listar_filtra_y_da_json(self):
        _, texto = self.cli("listar", "--proyecto", "holo", "--json")
        [d] = [json.loads(l) for l in texto.splitlines()]
        self.assertEqual(d["sesion"], "bbbb2222")
        _, texto = self.cli("listar", "--sesion", "aaaa", "--json")
        self.assertEqual(json.loads(texto)["proyecto"], "buscasa")

    def test_listar_ultimas_n(self):
        _, texto = self.cli("listar", "-n", "1", "--json")
        self.assertEqual(json.loads(texto)["proyecto"], "holo-ui")

    def test_linea_rota_no_tumba_el_listado(self):
        with open(self.dir / "decisiones.jsonl", "a") as f:
            f.write("{a medias\n")
        self.assertEqual(len(self.cli("listar", "--json")[1].splitlines()), 2)

    def test_ruta_y_uso(self):
        self.assertEqual(self.cli("ruta")[1].strip(), str(self.dir / "decisiones.jsonl"))
        with redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(decisiones.main(["otra"]), 2)


if __name__ == "__main__":
    unittest.main()
