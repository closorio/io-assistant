import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import guardia  # noqa: E402

SECRETO = "valor-secreto-de-prueba"


def bash(comando):
    return guardia.categorias("Bash", {"command": comando}, guardia.PROTEGIDAS)


class CategoriasTest(unittest.TestCase):
    def test_comandos_vigilados(self):
        casos = {"git stash": "stash", "git stash pop": "stash", "git reset --hard HEAD~1": "reset_hard",
                 "git push origin x": "push", "git push --force": "push_forzado", "git push -f": "push_forzado",
                 "git push origin +x": "push_forzado", "git clean -fd": "clean_f", "git clean --force": "clean_f",
                 "git branch -D x": "branch_D", "git worktree remove ../x": "worktree_remove"}
        for comando, esperada in casos.items():
            self.assertEqual(bash(comando), [esperada], comando)

    def test_formas_que_las_reglas_deny_no_captan(self):
        for comando in ("git -C . push origin x", "git -c a=b push", "git 'push'", "cd x && git push",
                        'sh -c "git push"', "bash -lc 'git push'", "FOO=1 git push", "/usr/bin/git push",
                        "env FOO=1 git push", "timeout 30 git push", "(git push)"):
            self.assertEqual(bash(comando), ["push"], comando)

    def test_palabras_de_shell_y_lanzadores(self):
        for comando, esperada in {"if true; then git stash; fi": "stash", "while x; do git push; done": "push",
                                  "! git stash": "stash", "{ git stash; }": "stash", "sudo git push": "push",
                                  "echo x | xargs git push": "push", "xargs -n1 git stash": "stash"}.items():
            self.assertEqual(bash(comando), [esperada], comando)

    def test_refspec_que_borra_en_remoto(self):
        self.assertEqual(bash("git push origin :rama"), ["push_forzado"])

    def test_no_confunde_texto_con_comandos(self):
        for comando in ('git commit -m "no hagas git push ni git stash"', "echo git push", "git log --grep=push",
                        "git status", "git branch -d x", "git reset --soft HEAD~1", "git clean -n", "ls", "",
                        'grep "git push" archivo'):
            self.assertEqual(bash(comando), [], comando)

    def test_varias_en_un_comando_sin_repetir(self):
        self.assertEqual(bash("git stash; git push; git stash pop"), ["stash", "push"])

    def test_comando_ilegible_no_rompe(self):
        self.assertEqual(bash('git push "sin cerrar'), ["push"])

    def test_rutas_protegidas(self):
        for ruta in (".env", "/a/b/.env.local", "/a/tenants/x/y.json", "tenants/z"):
            self.assertEqual(guardia.categorias("Edit", {"file_path": ruta}, guardia.PROTEGIDAS), ["ruta_protegida"], ruta)
        self.assertEqual(guardia.categorias("NotebookEdit", {"notebook_path": "/a/.env"}, guardia.PROTEGIDAS), ["ruta_protegida"])
        for ruta in ("/a/b.py", "/a/env.py", "/a/tenants.py", "/a/mis-tenants/x"):
            self.assertEqual(guardia.categorias("Write", {"file_path": ruta}, guardia.PROTEGIDAS), [], ruta)

    def test_entradas_raras(self):
        self.assertEqual(guardia.categorias("Read", {"file_path": ".env"}, guardia.PROTEGIDAS), [])
        self.assertEqual(guardia.categorias("Bash", {"command": 7}, guardia.PROTEGIDAS), [])
        self.assertEqual(guardia.categorias("Bash", None, guardia.PROTEGIDAS), [])


class RegistroTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.log = Path(d.name) / "sub" / "g.jsonl"
        p = mock.patch.object(guardia, "REGISTRO", self.log)
        p.start()
        self.addCleanup(p.stop)

    def ejecutar(self, evento):
        s = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(evento))), redirect_stdout(s):
            codigo = guardia.principal(["--modo", "registro"])
        self.assertEqual((codigo, s.getvalue()), (0, ""), "nunca decide ni escribe en stdout")

    def test_registra_categoria_y_nunca_el_comando(self):
        self.ejecutar({"hook_event_name": "PreToolUse", "session_id": "abcdefghij", "tool_name": "Bash", "cwd": "/a/vindam_x",
                       "agent_type": "Explore", "tool_input": {"command": f"git push https://{SECRETO}@host/r"}})
        texto = self.log.read_text()
        self.assertNotIn(SECRETO, texto)
        fila = json.loads(texto)
        self.assertEqual(fila["categorias"], ["push"])
        self.assertEqual((fila["sesion"], fila["carpeta"], fila["herramienta"], fila["agente"]),
                         ("abcdefgh", "vindam_x", "Bash", "Explore"))
        self.assertEqual(oct(self.log.stat().st_mode & 0o777), "0o600")

    def test_ruta_protegida_no_guarda_la_ruta(self):
        self.ejecutar({"session_id": "s", "tool_name": "Edit", "cwd": "/a", "tool_input": {"file_path": f"/a/tenants/{SECRETO}/x"}})
        self.assertNotIn(SECRETO, self.log.read_text())

    def test_registra_tambien_lo_inocuo_para_probar_que_el_hook_actua(self):
        self.ejecutar({"session_id": "s", "tool_name": "Bash", "cwd": "/a", "tool_input": {"command": "ls"}})
        self.assertEqual(json.loads(self.log.read_text())["categorias"], [])

    def test_entrada_ilegible_no_hace_nada(self):
        s = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("{roto")), redirect_stdout(s):
            self.assertEqual(guardia.principal([]), 0)
        self.assertEqual(s.getvalue(), "")

    def test_no_poder_escribir_no_falla(self):
        with mock.patch.object(guardia, "REGISTRO", Path("/proc/nope/g.jsonl")):
            self.ejecutar({"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "git push"}})

    def test_no_hay_modo_que_bloquee_todavia(self):
        s = io.StringIO()
        evento = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "git push --force"}}
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(evento))), redirect_stdout(s):
            self.assertEqual(guardia.principal(["--modo", "activo"]), 0)
        self.assertEqual(s.getvalue(), "")

    def test_resumen(self):
        for c in ("git push", "git push", "ls"):
            self.ejecutar({"session_id": "s", "tool_name": "Bash", "cwd": "/a/b", "tool_input": {"command": c}})
        s = io.StringIO()
        with redirect_stdout(s):
            guardia.resumen()
        self.assertIn("3 llamadas", s.getvalue())
        self.assertIn("push: 2", s.getvalue())


class ComandoRealTest(unittest.TestCase):
    """El comando tal como irá en settings.local.json, ejecutado por un shell de verdad."""

    def lanzar(self, script, entrada, d):
        return subprocess.run(guardia.comando_hook(script), shell=True, input=entrada, capture_output=True, text=True,
                              env=dict(os.environ, XDG_DATA_HOME=d), timeout=20)

    def test_script_ausente_no_da_codigo_2_que_bloquearia(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.lanzar(Path(d) / "no-existe.py", "{}", d)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_script_real_con_entrada_rota(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.lanzar(RAIZ / "scripts" / "guardia.py", "{roto", d)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_script_real_registra(self):
        with tempfile.TemporaryDirectory() as d:
            evento = json.dumps({"session_id": "s", "tool_name": "Bash", "cwd": "/a", "tool_input": {"command": "git stash"}})
            r = self.lanzar(RAIZ / "scripts" / "guardia.py", evento, d)
            fila = json.loads((Path(d) / "narrador" / "guardia.jsonl").read_text())
        self.assertEqual((r.returncode, r.stdout, fila["categorias"]), (0, "", ["stash"]))

    def test_configuracion_es_async_y_sin_args(self):
        c = guardia.configuracion("/x/guardia.py")["hooks"]["PreToolUse"][0]
        self.assertEqual(c["matcher"], "Bash|Edit|Write|NotebookEdit")
        h = c["hooks"][0]
        self.assertTrue(h["async"])
        self.assertTrue(h["command"].endswith("|| true"))


if __name__ == "__main__":
    unittest.main()
