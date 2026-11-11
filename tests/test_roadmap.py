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


TABLA = """---
name: roadmap
tipo: indice
---

# Hoja de ruta

Texto de entrada con una tabla vieja que no cuenta:

| a | b |
|---|---|
| 1 | 2 |

## Rumbo vigente (10-11-2026)

Sale de la revisión de rumbo ([[destino]]).

| # | Acción | Dueño | Hecho cuando | Tope | Puertas |
|---|---|---|---|---|---|
| 1 | **Estrenar el alta con Acme, nativo en el motor, en dev** (decisión del usuario: `dev.acme.test`, ver [[plan-m|el plan M]]): firmar D5. **10-11: hecho hasta la v3 en borrador** | Usuario; sesión, la versión de Acme | Acme con versión activa y M-01 anotado | 5 días hábiles | Encender el motor, producción |
| 2 | **Cerrar Loyal: ✅ hecha el 10-11, congelado como corpus** ([[2026-11-10-loyal]]). Versión 18 | Sesión | ✅ Resultado anotado | Gastado: 0,479 USD | Ninguna abierta |
| 3 | **Camino a producción:** ✅ script de rueda; ✅ motor 0.19.1. Queda: push y PR | Sesión, lo hecho; usuario, el push; el otro desarrollador, el despliegue | Producción con ≥ 0.18 | 2 días de sesión | Push, fusión a `main` |
| 4 | **Beta a sombra:** versión con `consentimiento.senales` | Usuario, la confirmación; sesión, la versión | 2 semanas sin divergencias | 5 días de sesión; encendido objetivo, semana del 30-11 | Encender el motor |
| 5 | **F3 y F4 congeladas** (38 tareas) hasta que haya sombra | Sesión | — | — | — |
| 6 | Fachada pública del motor con prueba de frontera (la app importa 16 módulos internos) | Sesión | Aparcada hasta después de la sombra | — | — |
| 7 | Revisión legal: una nota por cliente con la cláusula que lo cubre | Usuario | Al final del proyecto | — | — |

- **Regla de corte:** dos semanas sin cambio.
"""


class TablaRumbo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name) / "motor"
        self.md = self.raiz / "conocimiento" / "60-backlog" / "roadmap.md"
        self.md.parent.mkdir(parents=True)
        self.md.write_text(TABLA, encoding="utf-8")
        self.p = {"nombre": "motor", "ruta": str(self.raiz), "roadmap_md": "conocimiento/60-backlog/roadmap.md"}

    def tearDown(self):
        self.tmp.cleanup()

    def informe(self, g=None):
        with mock.patch.object(roadmap, "datos_git", return_value=g):
            return roadmap.informe(self.p, HOY)

    def filas(self):
        return {n["numero"]: n for n in self.informe()["notas"]}

    def test_saca_las_siete_acciones(self):
        r = self.informe()
        self.assertEqual(r["error"], "")
        self.assertEqual(len(r["notas"]), 7)
        self.assertEqual(r["fuente"], str(self.md))

    def test_hecho_bien_contado(self):
        m = self.informe()["medido"]
        self.assertEqual((m["hitos_hechos"], m["hitos_total"]), (1, 7))
        self.assertEqual(m["fases"], {"hecho": 1, "en-curso": 0, "pendiente": 4, "aparcado": 2})

    def test_los_tic_de_subpasos_no_cierran_la_accion(self):
        f = self.filas()
        self.assertEqual(f["2"]["estado"], "hecho")
        self.assertEqual(f["3"]["estado"], "pendiente")
        self.assertEqual(f["2"]["cerrado"], "2026-11-10")

    def test_aparcadas_y_al_final(self):
        f = self.filas()
        self.assertEqual(f["5"]["estado"], "aparcado")
        self.assertEqual(f["6"]["estado"], "aparcado")
        self.assertEqual(f["7"]["estado"], "pendiente")
        self.assertEqual(self.informe()["notas"][-1]["numero"], "7")

    def test_al_final_va_detras_aunque_no_sea_la_ultima(self):
        texto = TABLA.replace("| 7 | Revisión legal", "| 0 | Revisión legal")
        lineas = texto.split("\n")
        i7 = next(i for i, l in enumerate(lineas) if l.startswith("| 0 |"))
        fila = lineas.pop(i7)
        i1 = next(i for i, l in enumerate(lineas) if l.startswith("| 1 | **Estrenar"))
        lineas.insert(i1, fila)
        self.md.write_text("\n".join(lineas), encoding="utf-8")
        r = self.informe()
        self.assertEqual(r["notas"][-1]["numero"], "0")
        self.assertEqual(r["medido"]["siguiente_fase"], "acción 1")

    def test_siguiente_es_la_primera_abierta(self):
        m = self.informe()["medido"]
        self.assertEqual(m["siguiente_fase"], "acción 1")
        self.assertEqual(m["siguiente"], "Estrenar el alta con Acme, nativo en el motor, en dev")

    def test_responsable_sale_del_dueno(self):
        f = self.filas()
        self.assertEqual(f["1"]["responsable"], "Usuario, Sesión")
        self.assertEqual(f["3"]["responsable"], "Sesión, Usuario, El otro desarrollador")

    def test_resumen_corto_sin_markdown(self):
        f = self.filas()
        self.assertEqual(f["2"]["fase"], "Cerrar Loyal: hecha el 10-11, congelado como corpus")
        self.assertEqual(f["3"]["fase"], "Camino a producción")
        self.assertEqual(f["6"]["fase"], "Fachada pública del motor con prueba de frontera")
        for n in self.informe()["notas"]:
            self.assertNotRegex(n["fase"] + n["nota"] + " ".join(n["pendientes"]), r"\*\*|\[\[|`|✅")
            self.assertLessEqual(len(n["fase"]), 90)

    def test_resumen_largo_se_corta(self):
        corto = roadmap.resumir("**" + "palabra " * 40 + "**")
        self.assertLessEqual(len(corto), 90)
        self.assertTrue(corto.endswith("…"))

    def test_fecha_del_encabezado_y_objetivo_de_la_celda(self):
        r = self.informe()
        f = {n["numero"]: n for n in r["notas"]}
        self.assertEqual(r["rumbo_fecha"], "2026-11-10")
        self.assertEqual(f["1"]["actualizado"], "2026-11-10")
        self.assertEqual(f["4"]["objetivo"], "2026-11-30")
        self.assertIsNone(f["1"]["objetivo"])
        self.assertEqual(r["medido"]["fecha_objetivo"], "2026-11-30")

    def test_el_ritmo_se_mide_desde_el_rumbo(self):
        e = self.informe(git(primero=date(2025, 1, 1)))["estimado"]
        self.assertEqual(e["desde"], "2026-11-10")
        self.assertIsNone(e["fecha_prevista"])
        self.assertIn("pocos datos", e["motivo"])

    def test_sin_objetivo_no_inventa(self):
        self.md.write_text(TABLA.replace("encendido objetivo, semana del 30-11", "sin más"), encoding="utf-8")
        r = self.informe()
        self.assertEqual(r["deriva_texto"], "sin fecha objetivo")
        self.assertTrue(all(n["objetivo"] is None for n in r["notas"]))

    def test_encabezado_sin_fecha(self):
        self.md.write_text(TABLA.replace("## Rumbo vigente (10-11-2026)", "## Rumbo vigente"), encoding="utf-8")
        r = self.informe()
        self.assertEqual(len(r["notas"]), 7)
        self.assertIsNone(r["rumbo_fecha"])

    def test_celda_con_barra_dentro_de_enlace(self):
        self.assertEqual(roadmap.celdas("| a | [[x|y]] `p|q` | c |"), ["a", "[[x|y]] `p|q`", "c"])

    def test_sin_tabla_es_un_error_legible(self):
        self.md.write_text("# nada\n", encoding="utf-8")
        self.assertIn("Rumbo vigente", self.informe()["error"])

    def test_sin_archivo_es_un_error_legible(self):
        self.md.unlink()
        self.assertIn("sin hoja de ruta", self.informe()["error"])

    def test_raiz_reconoce_el_archivo(self):
        (self.raiz / "src" / "a").mkdir(parents=True)
        with mock.patch.object(roadmap, "proyectos", return_value=[self.p]):
            self.assertEqual(roadmap.raiz_de(str(self.raiz / "src" / "a")), self.raiz.resolve())
            self.assertEqual(roadmap.entrada_de(self.raiz)["roadmap_md"], "conocimiento/60-backlog/roadmap.md")

    def test_ruta_o_activo_usan_la_tabla(self):
        with mock.patch.object(roadmap, "proyectos", return_value=[self.p]), \
                mock.patch.object(roadmap, "datos_git", return_value=None):
            salida = io.StringIO()
            with redirect_stdout(salida):
                self.assertEqual(roadmap.main(["--json", str(self.raiz), "--hoy", "2026-11-09"]), 0)
        self.assertEqual(len(json.loads(salida.getvalue())["proyectos"][0]["notas"]), 7)

    def test_defecto_trae_la_ruta_del_motor(self):
        motor = next(p for p in roadmap.PROYECTOS_DEFECTO if p["nombre"] == "vindam_dashboard_engine")
        self.assertEqual(motor["roadmap_md"], "conocimiento/60-backlog/roadmap.md")

    def test_config_lleva_la_ruta(self):
        cfg = Path(self.tmp.name) / "roadmap.json"
        cfg.write_text(json.dumps({"proyectos": [self.p]}), encoding="utf-8")
        with mock.patch.object(roadmap, "CONFIG", cfg):
            self.assertEqual(roadmap.proyectos()[0]["roadmap_md"], "conocimiento/60-backlog/roadmap.md")

    def test_texto_lista_las_acciones(self):
        salida = roadmap.texto(self.informe())
        self.assertIn("acciones (rumbo vigente del 2026-11-10):", salida)
        self.assertIn("✓ 2. Cerrar Loyal", salida)
        self.assertIn("◌ 5. F3 y F4 congeladas", salida)
