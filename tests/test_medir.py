import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import medir  # noqa: E402

PRECIOS = {"fecha": "2026-11-04", "modelos": {"m": {"entrada": 2, "cache_5m": 3, "cache_1h": 4, "cache_lectura": 1, "salida": 10}}}
SECRETO = "contenido-que-no-debe-salir"


def msg(id_, ts="2026-10-24T10:00:00.000Z", modelo="m", **uso):
    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": id_, "model": modelo, "usage": base | uso, "content": [{"type": "text", "text": SECRETO}]}}


def compacta(disparo, tokens):
    return {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-10-24T11:00:00.000Z",
            "compactMetadata": {"trigger": disparo, "preTokens": tokens}}


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        self.ruta = self.raiz / "abc123.jsonl"

    def escribir(self, lineas, sub=()):
        self.ruta.write_text("\n".join(json.dumps(x) if isinstance(x, dict) else x for x in lineas) + "\n")
        if sub:
            (self.raiz / "abc123" / "subagents").mkdir(parents=True)
            (self.raiz / "abc123" / "subagents" / "a.jsonl").write_text("\n".join(json.dumps(x) for x in sub) + "\n")


class ResumenTest(Base):
    def test_mensaje_repetido_cuenta_una_vez(self):
        self.escribir([msg("x", output_tokens=1_000_000), msg("x", output_tokens=1_000_000)])
        r = medir.resumen(self.ruta, PRECIOS)
        self.assertEqual(r["principal"]["tokens"]["salida"], 1_000_000)
        self.assertEqual(r["principal"]["coste"], 10)

    def test_subagentes_se_suman_aparte(self):
        self.escribir([msg("x", output_tokens=1_000_000)], sub=[msg("y", output_tokens=2_000_000)])
        r = medir.resumen(self.ruta, PRECIOS)
        self.assertEqual(r["subagentes"]["coste"], 20)
        self.assertEqual(r["subagentes"]["archivos"], 1)
        self.assertEqual(r["coste_total"], 30)

    def test_cache_con_detalle_de_caducidad(self):
        self.escribir([msg("x", cache_creation_input_tokens=3_000_000,
                           cache_creation={"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 2_000_000})])
        self.assertEqual(medir.resumen(self.ruta, PRECIOS)["principal"]["coste"], 11)

    def test_cache_sin_detalle_usa_la_tarifa_de_5m(self):
        self.escribir([msg("x", cache_creation_input_tokens=1_000_000)])
        self.assertEqual(medir.resumen(self.ruta, PRECIOS)["principal"]["coste"], 3)

    def test_modelo_sin_precio_no_inventa_coste_y_se_declara(self):
        self.escribir([msg("x", modelo="nuevo", output_tokens=1_000_000)])
        r = medir.resumen(self.ruta, PRECIOS)
        self.assertEqual(r["principal"]["coste"], 0)
        self.assertEqual(r["sin_precio"], ["nuevo"])
        self.assertEqual(r["principal"]["tokens"]["salida"], 1_000_000)

    def test_sintetico_se_ignora(self):
        self.escribir([msg("x", modelo="<synthetic>", output_tokens=5)])
        r = medir.resumen(self.ruta, PRECIOS)
        self.assertEqual(r["principal"]["mensajes"], 0)
        self.assertEqual(r["sin_precio"], [])

    def test_compactaciones(self):
        self.escribir([compacta("manual", 900), compacta("auto", 800)])
        c = medir.resumen(self.ruta, PRECIOS)["compactaciones"]
        self.assertEqual((c["manuales"], c["automaticas"], c["tokens_antes"]), (1, 1, [900, 800]))

    def test_linea_rota_no_rompe(self):
        self.escribir(["{no es json", msg("x", output_tokens=1)])
        self.assertEqual(medir.resumen(self.ruta, PRECIOS)["principal"]["mensajes"], 1)

    def test_el_contenido_nunca_sale(self):
        self.escribir([msg("x", output_tokens=1), compacta("auto", 1)], sub=[msg("y", output_tokens=1)])
        r = medir.resumen(self.ruta, PRECIOS)
        self.assertNotIn(SECRETO, json.dumps(r))
        b = io.StringIO()
        with redirect_stdout(b):
            medir.imprimir(r)
        self.assertNotIn(SECRETO, b.getvalue())


class PorTareaTest(Base):
    COMMITS = [("2026-10-24T12:00:00+00:00", "t16"), ("2026-10-24T14:00:00+00:00", "t33")]

    def test_reparte_al_siguiente_commit_con_tarea(self):
        self.escribir([msg("a", ts="2026-10-24T11:00:00.000Z", output_tokens=1_000_000),
                       msg("b", ts="2026-10-24T13:00:00.000Z", output_tokens=2_000_000),
                       msg("c", ts="2026-10-24T15:00:00.000Z", output_tokens=3_000_000)])
        t = medir.por_tarea(self.ruta, self.COMMITS, PRECIOS)
        self.assertEqual(t["tareas"], {"t16": 10, "t33": 20})
        self.assertEqual(t["sin_asignar"], 30)

    def test_varios_commits_seguidos_de_la_misma_tarea_se_acumulan(self):
        self.escribir([msg("a", ts="2026-10-24T11:00:00.000Z", output_tokens=1_000_000),
                       msg("b", ts="2026-10-24T12:30:00.000Z", output_tokens=1_000_000)])
        t = medir.por_tarea(self.ruta, [("2026-10-24T12:00:00+00:00", "t16"), ("2026-10-24T13:00:00+00:00", "t16")], PRECIOS)
        self.assertEqual(t["tareas"], {"t16": 20})

    def test_tarea_del_asunto(self):
        self.assertEqual(medir.tarea_de("fix(t08): algo y t09"), "t08")
        self.assertEqual(medir.tarea_de("Merge branch 'feature/t85-nombre' into develop"), "t85")
        self.assertIsNone(medir.tarea_de("corpus: sin tarea; contiene http2 y test12"))


class BuscarTest(Base):
    def test_prefijo_unico_y_ambiguo(self):
        (self.raiz / "p1").mkdir()
        (self.raiz / "p2").mkdir()
        (self.raiz / "p1" / "abc1.jsonl").write_text("")
        (self.raiz / "p2" / "abc2.jsonl").write_text("")
        with mock.patch.object(medir, "PROYECTOS_CLAUDE", self.raiz):
            self.assertEqual(medir.buscar("abc1").name, "abc1.jsonl")
            with self.assertRaises(SystemExit):
                medir.buscar("abc")
            with self.assertRaises(SystemExit):
                medir.buscar("zzz")


class PreciosTest(unittest.TestCase):
    def test_tabla_real_con_fecha_y_modelos_en_uso(self):
        p = medir.cargar_precios()
        self.assertRegex(p["fecha"], r"^\d{4}-\d{2}-\d{2}$")
        for m in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-haiku-5-5"):
            self.assertEqual(set(p["modelos"][m]), {"entrada", "cache_5m", "cache_1h", "cache_lectura", "salida"})


if __name__ == "__main__":
    unittest.main()
