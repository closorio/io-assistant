"""Pruebas de parte_matinal.py (sin red). Ejecuta: python3 -m unittest tests.test_parte_matinal"""

import json
import re
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import parte_matinal as pm  # noqa: E402
from parte_matinal import Redactor, Resultado, a_json_compacto, extraer_pendientes, fecha_operativa, leer_env, semaforo, toca_parte  # noqa: E402

FUENTE = (RAIZ / "scripts" / "parte_matinal.py").read_text(encoding="utf-8")


class LeerEnv(unittest.TestCase):
    def test_formatos(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# comentario\nA=1\nexport B="dos tres"\nC=\'x\'\nD=valor # nota\n\nE=\n1MAL=z\nF=a=b\n', encoding="utf-8")
            env = leer_env(p)
        self.assertEqual(env, {"A": "1", "B": "dos tres", "C": "x", "D": "valor", "E": "", "F": "a=b"})


class DiaOperativo(unittest.TestCase):
    def test_corte_a_las_cinco(self):
        self.assertEqual(fecha_operativa(datetime(2026, 10, 17, 0, 10)), date(2026, 10, 16))
        self.assertEqual(fecha_operativa(datetime(2026, 10, 17, 5, 1)), date(2026, 10, 17))
        self.assertEqual(fecha_operativa(datetime(2026, 10, 16, 23, 50)), date(2026, 10, 16))

    def test_toca_parte(self):
        ahora = datetime(2026, 10, 17, 8, 0)
        hoy = "2026-10-17"
        self.assertEqual(toca_parte(ahora, {}), "nuevo")
        self.assertEqual(toca_parte(ahora, {"fecha": "2026-10-16", "estado": "hecho", "entregado": True}), "nuevo")
        self.assertEqual(toca_parte(ahora, {"fecha": hoy, "estado": "hecho", "entregado": True}), "no")
        self.assertEqual(toca_parte(ahora, {"fecha": hoy, "estado": "hecho", "entregado": False}), "pendiente_entrega")
        self.assertEqual(toca_parte(ahora, {"fecha": hoy, "estado": "fallido"}), "nuevo")
        reciente = {"fecha": hoy, "estado": "en_curso", "inicio_ts": ahora.timestamp() - 60}
        self.assertEqual(toca_parte(ahora, reciente), "en_curso")
        viejo = {"fecha": hoy, "estado": "en_curso", "inicio_ts": ahora.timestamp() - 20 * 60}
        self.assertEqual(toca_parte(ahora, viejo), "nuevo")
        # a las 00:10 el parte de «ayer» sigue valiendo
        self.assertEqual(toca_parte(datetime(2026, 10, 18, 0, 10), {"fecha": hoy, "estado": "hecho", "entregado": True}), "no")


class Pendientes(unittest.TestCase):
    CLAUDE = """# Tenant
## Otra sección
- esto no es pendiente
## Estado actual y pendientes — actualizado
> bitácora: - pendiente que NO debe salir
Texto suelto.
- ✅ Hecho ya
- ⛔ Falta la credencial OAuth de **Google Calendar**
1. Confirmar `bilingüe` con el [cliente](docs/x.md)
- [x] cerrado
- [ ] Anexo E
| Estación | Estado |
|---|---|
| **7 — REVISAR** | ⏳ post-go-live |
| **6 — DOC** | ✅ cerrada |
### Hecho (ayer)
- esto está hecho y no sale
### 🔴 Lo que bloquea
```
- dentro de código no sale
```
- Otro ítem de lista
## Siguiente sección
- no debe salir
### ⛔ Pendiente: citas reales
- Falta la credencial OAuth
"""

    def test_claude_md(self):
        items = extraer_pendientes(self.CLAUDE, "CLAUDE.md")
        self.assertEqual(items, ["⛔ Falta la credencial OAuth de Google Calendar", "[ ] Anexo E", "7 — REVISAR · ⏳ post-go-live",
                                 "Falta la credencial OAuth", "Confirmar bilingüe con el cliente", "Otro ítem de lista"])

    def test_otros(self):
        self.assertEqual(extraer_pendientes("- [x] hecho\n- [ ] abierto\n### 🔴 Bloqueante X\n", "PASO.md"), ["- [ ] abierto", "### 🔴 Bloqueante X"])
        self.assertEqual(extraer_pendientes("\nuno\n\ndos\n", "pendiente_.txt"), ["uno", "dos"])
        self.assertEqual(extraer_pendientes("# Sin seccion\n- x\n", "CLAUDE.md"), [])


class Salida(unittest.TestCase):
    def parte(self):
        res = [Resultado("n8n", "a", "verde", "100 ms"), Resultado("n8n", "b", "rojo", "no responde", "healthz: timeout"),
               Resultado("tls", "a", "ambar", "a-n8n vence en 10 días"), Resultado("vps", "global", "na", "desactivado")]
        return {"resultados": res, "tenants": {"a": "a", "b": "be"}, "pendientes": [], "trabajadores": [], "correos": [],
                "fecha": "2026-10-17", "hora": "08:00", "semaforo": semaforo(res), "resumen_voz": "", "ruta_md": Path("/x.md")}

    def test_semaforo_y_json(self):
        p = self.parte()
        self.assertEqual(p["semaforo"], "rojo")
        p["resumen_voz"] = pm.resumen_voz(p, p["tenants"])
        self.assertTrue(p["resumen_voz"].startswith("Parte en rojo. En rojo: be n8n no responde."))
        c = a_json_compacto(p)
        self.assertEqual(c["tenants"]["be"]["semaforo"], "rojo")
        self.assertEqual(c["tenants"]["a"]["anomalias"], ["certificado: a-n8n vence en 10 días"])
        self.assertEqual(c["global"]["no_comprobado"], ["global: servidor: desactivado"])
        self.assertEqual(c["contadores"]["verde"], 1)
        self.assertNotIn("100 ms", json.dumps(c))  # los verdes no viajan a Ío

    def test_verde(self):
        res = [Resultado("n8n", "a", "verde", "100 ms")]
        self.assertEqual(semaforo(res), "verde")
        self.assertEqual(semaforo([Resultado("x", "a", "na")]), "verde")


class Redaccion(unittest.TestCase):
    def test_no_fuga(self):
        r = Redactor()
        r.aprender({"N8N_API_KEY": "clave-secreta-larga-123", "N8N_BASE_URL": "https://x-n8n.vindam.com", "CORTA": "abc"})
        self.assertEqual(r.limpiar("token clave-secreta-larga-123 en https://x-n8n.vindam.com"), "token *** en https://x-n8n.vindam.com")


class SoloLectura(unittest.TestCase):
    def test_sin_post(self):
        self.assertNotIn('"POST"', FUENTE)
        self.assertNotIn("'POST'", FUENTE)
        self.assertFalse(re.search(r"urlopen\([^)]*data=", FUENTE))
        self.assertIn('assert metodo in ("GET", "HEAD")', FUENTE)
        self.assertIn('readonly=True', FUENTE)
        self.assertIn('BODY.PEEK', FUENTE)
        self.assertNotRegex(FUENTE, r"/webhook/")

    def test_peticion_rechaza_post(self):
        with self.assertRaises(AssertionError):
            pm.peticion("http://127.0.0.1:9/", metodo="POST")


if __name__ == "__main__":
    unittest.main()
