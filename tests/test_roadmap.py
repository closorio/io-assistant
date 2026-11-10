import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import roadmap  # noqa: E402

HOY = date(2026, 11, 9)


def nota(carpeta: Path, nombre: str, cuerpo: str = "", **campos) -> None:
    lineas = ["---", "tipo: roadmap"]
    for k, v in campos.items():
        lineas.append(f"{k}: {v}" if isinstance(v, int) else f'{k}: "{v}"')
    lineas += ["---", f"# {nombre}", "", cuerpo]
    (carpeta / f"{nombre}.md").write_text("\n".join(lineas), encoding="utf-8")


def git(n4=20, total=100, primero=date(2026, 8, 1), ultimo=date(2026, 11, 7)):
    return {"commits_4_semanas": n4, "commits_total": total, "primer_commit": primero,
            "ultimo_commit": ultimo, "ultimo_asunto": "feat: algo"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name) / "proy"
        self.dir = self.raiz / "conocimiento" / "roadmap"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def informe(self, g=None):
        with mock.patch.object(roadmap, "datos_git", return_value=g):
            return roadmap.informe({"nombre": "proy", "ruta": str(self.raiz)}, HOY)


class Notas(Base):
    def test_casillas_cuentan_y_las_opcionales_no(self):
        hechas, total = roadmap.casillas("## Hitos\n- [x] A0\n- [ ] A1\n- [ ] A6 (opcional)\n## Estado\n- [ ] fuera\n")
        self.assertEqual((hechas, total), (1, 2))

    def test_frontmatter_vacio_toma_las_casillas(self):
        nota(self.dir, "F1", "## Hitos\n- [x] a\n- [x] b\n- [ ] c\n", estado="en-curso")
        r = self.informe()
        self.assertEqual((r["medido"]["hitos_hechos"], r["medido"]["hitos_total"]), (2, 3))

    def test_descuadre_avisa(self):
        nota(self.dir, "F1", "## Hitos\n- [x] a\n- [ ] b\n", estado="en-curso", hitos_total=5, hitos_hechos=1)
        self.assertTrue(any("no cuadran" in a for a in self.informe()["avisos"]))

    def test_hecha_se_normaliza_y_pide_cierre(self):
        nota(self.dir, "F1", estado="hecha", hitos_total=1, hitos_hechos=1)
        r = self.informe()
        self.assertEqual(r["medido"]["fases"]["hecho"], 1)
        self.assertTrue(any("sin fecha de cierre" in a for a in r["avisos"]))

    def test_sin_vault_es_un_error_legible(self):
        r = roadmap.informe({"nombre": "x", "ruta": str(Path(self.tmp.name) / "nada")}, HOY)
        self.assertIn("sin vault", r["error"])


class Deriva(Base):
    def test_sin_objetivo_no_inventa(self):
        nota(self.dir, "F1", estado="en-curso", hitos_total=4, hitos_hechos=2, inicio="2026-10-01")
        r = self.informe(git())
        self.assertEqual(r["semaforo"], "sin_objetivo")
        self.assertEqual(r["deriva_texto"], "sin fecha objetivo")
        self.assertIsNone(r["medido"]["deriva_dias"])
        self.assertIsNone(r["estimado"]["desfase_dias"])

    def test_objetivo_pasado_mas_de_una_semana_es_rojo(self):
        nota(self.dir, "F1", estado="en-curso", hitos_total=4, hitos_hechos=2, objetivo="2026-10-20")
        r = self.informe(git())
        self.assertEqual((r["semaforo"], r["medido"]["deriva_dias"]), ("rojo", 20))

    def test_objetivo_lejano_y_buen_ritmo_es_verde(self):
        nota(self.dir, "F1", estado="en-curso", hitos_total=10, hitos_hechos=9,
             inicio="2026-08-01", objetivo="2027-06-01", cerrado="")
        r = self.informe(git())
        self.assertEqual(r["semaforo"], "verde")

    def test_prevision_pasada_del_objetivo_es_ambar(self):
        nota(self.dir, "F1", estado="en-curso", hitos_total=40, hitos_hechos=3,
             inicio="2026-08-01", objetivo="2026-11-20")
        r = self.informe(git())
        self.assertEqual(r["semaforo"], "ambar")
        self.assertGreater(r["estimado"]["desfase_dias"], 0)


class Estimacion(Base):
    def test_ritmo_y_fecha(self):
        # 14 semanas desde el 2026-08-03, 7 hitos hechos: 0,5 por semana; actividad igual a la media.
        nota(self.dir, "F1", estado="en-curso", hitos_total=9, hitos_hechos=7, inicio="2026-08-03",
             cerrado="")
        e = self.informe(git(n4=40, total=140, primero=date(2026, 8, 3)))["estimado"]
        self.assertAlmostEqual(e["ritmo_hitos_semana"], 0.5, places=2)
        self.assertEqual(e["fecha_prevista"], "2026-12-07")

    def test_pocos_datos_lo_dice(self):
        nota(self.dir, "F1", estado="en-curso", hitos_total=6, hitos_hechos=1, inicio="2026-10-20")
        e = self.informe(git(n4=2, total=3, primero=date(2026, 10, 20)))["estimado"]
        self.assertTrue(e["pocos_datos"])
        self.assertIn("pocos datos", e["motivo"])

    def test_proyecto_parado_no_tiene_fecha(self):
        nota(self.dir, "F1", estado="en-curso", hitos_total=10, hitos_hechos=8, inicio="2026-08-01")
        e = self.informe(git(n4=0, total=150))["estimado"]
        self.assertIsNone(e["fecha_prevista"])
        self.assertIn("parado", e["motivo"])
        self.assertTrue(e["pocos_datos"])

    def test_sin_hitos_hechos_no_hay_fecha(self):
        nota(self.dir, "F1", estado="pendiente", hitos_total=3, hitos_hechos=0, inicio="2026-09-01")
        e = self.informe(git())["estimado"]
        self.assertIsNone(e["fecha_prevista"])


class Cli(Base):
    def test_json_y_filtro(self):
        nota(self.dir, "F1", estado="en-curso", hitos_total=2, hitos_hechos=1, siguiente="medir")
        with mock.patch.object(roadmap, "proyectos", return_value=[{"nombre": "proy", "ruta": str(self.raiz)},
                                                                   {"nombre": "otro", "ruta": "/no"}]), \
                mock.patch.object(roadmap, "datos_git", return_value=None):
            salida = io.StringIO()
            with redirect_stdout(salida):
                self.assertEqual(roadmap.main(["--json", "proy", "--hoy", "2026-11-09"]), 0)
        datos = json.loads(salida.getvalue())
        self.assertEqual([p["nombre"] for p in datos["proyectos"]], ["proy"])
        self.assertEqual(datos["proyectos"][0]["medido"]["siguiente"], "medir")


if __name__ == "__main__":
    unittest.main()


class ProyectoActivoTest(unittest.TestCase):
    def test_raiz_sube_hasta_el_vault(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d) / "proy"
            (raiz / "conocimiento" / "roadmap").mkdir(parents=True)
            (raiz / "src" / "a").mkdir(parents=True)
            self.assertEqual(roadmap.raiz_de(str(raiz / "src" / "a")), raiz.resolve())

    def test_sesion_activa_ignora_io_y_trabajadores(self):
        with tempfile.TemporaryDirectory() as d:
            ses = Path(d)
            vivo = __import__("os").getpid()
            filas = [
                {"pid": vivo, "kind": "interactive", "agent": "narrador:io", "name": "Ío", "cwd": "/x/io", "updatedAt": 900},
                {"pid": vivo, "kind": "background", "cwd": "/x/trab", "updatedAt": 800},
                {"pid": vivo, "kind": "interactive", "name": "viejo", "cwd": "/x/viejo", "updatedAt": 100},
                {"pid": vivo, "kind": "interactive", "name": "nuevo", "cwd": "/x/nuevo", "statusUpdatedAt": 500},
                {"pid": 999999999, "kind": "interactive", "name": "muerto", "cwd": "/x/muerto", "updatedAt": 990},
            ]
            for i, f in enumerate(filas):
                (ses / f"{i}.json").write_text(json.dumps(f), encoding="utf-8")
            with mock.patch.object(roadmap, "SESIONES", ses):
                self.assertEqual(roadmap.sesion_activa()["name"], "nuevo")
