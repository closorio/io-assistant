"""Pruebas de parte_matinal.py (sin red). Ejecuta: python3 -m unittest tests.test_parte_matinal"""

import json
import re
import sys
import tempfile
import unittest
import unittest.mock
import urllib.parse
from dataclasses import asdict
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
    def fuente_sin_sonda(self):
        # quita los cuerpos de peticion_sonda, cuerpo_sonda y chk_sonda_e2e (hasta el siguiente `def` o separador de sección)
        return re.sub(r"\ndef (peticion_sonda|cuerpo_sonda|chk_sonda_e2e)\(.*?(?=\ndef |\n# ---)", "\n", FUENTE, flags=re.S)

    def test_sin_post_fuera_de_la_sonda(self):
        f = self.fuente_sin_sonda()
        self.assertNotIn('"POST"', f)
        self.assertNotIn("'POST'", f)
        self.assertFalse(re.search(r"urlopen\([^)]*data=", f))
        self.assertNotRegex(f, r"/webhook/")
        self.assertIn('assert metodo in ("GET", "HEAD")', FUENTE)
        self.assertIn('readonly=True', FUENTE)
        self.assertIn('BODY.PEEK', FUENTE)
        self.assertEqual(FUENTE.count('method="POST"'), 1)  # solo peticion_sonda

    def test_peticion_sonda_rechaza_fuera_del_webhook(self):
        with self.assertRaises(AssertionError):
            pm.peticion_sonda("https://x-n8n.test/api/v1/workflows", {"attention_id": "web_demo_x", "message": "hola"})
        with self.assertRaises(AssertionError):  # sin prefijo de sesión de prueba
            pm.peticion_sonda("https://x-n8n.test/webhook/wpp", {"attention_id": "5215550000", "message": "hola"})
        for ruta in ("demo-web", "wpp/../demo-web", "webchat", "wpp_staging/x"):  # solo wpp y wpp_staging, aunque lo pida la configuración
            with self.assertRaises(AssertionError, msg=ruta):
                pm.peticion_sonda(f"https://x-n8n.test/webhook/{ruta}", {"attention_id": "web_demo_x", "message": "hola"})

    def test_peticion_rechaza_post(self):
        with self.assertRaises(AssertionError):
            pm.peticion("http://127.0.0.1:9/", metodo="POST")


if __name__ == "__main__":
    unittest.main()


class Ejecuciones(unittest.TestCase):
    """El modelo sin créditos con onError=continue: la ejecución acaba en success y el bot responde con relleno."""

    def tenant(self):
        return pm.Tenant("vindam", "vindam", Path("/nada"), {}, env={"N8N_BASE_URL": "https://n8n.test"})

    def peticion_falsa(self, con_credito_agotado):
        from datetime import timedelta, timezone
        ahora = datetime.now(timezone.utc)
        larga = {"id": "55", "status": "success", "startedAt": (ahora - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                 "stoppedAt": (ahora - timedelta(minutes=5) + timedelta(seconds=8)).isoformat().replace("+00:00", "Z")}
        corta = {"id": "56", "status": "success", "startedAt": (ahora - timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
                 "stoppedAt": (ahora - timedelta(minutes=4) + timedelta(milliseconds=300)).isoformat().replace("+00:00", "Z")}
        pedidas = []

        def falsa(url, cab=None, timeout=6, metodo="GET", max_bytes=0):
            pedidas.append(url)
            if "status=error" in url:
                return pm.Resp(200, b'{"data": []}')
            if "executions?workflowId" in url:
                return pm.Resp(200, json.dumps({"data": [corta, larga]}).encode())
            if "/executions/55?includeData" in url:
                cuerpo = {"data": {"resultData": {"runData": {"Vindam AI Model": [{"error": {"message": "OpenAI: Rate limit reached",
                          "description": "You have no credits remaining. Add credits to continue using the API"}}]}}}}
                if not con_credito_agotado:
                    cuerpo = {"data": {"resultData": {"runData": {"Vindam AI Model": [{"data": {}}]}}}}
                return pm.Resp(200, json.dumps(cuerpo).encode())
            raise AssertionError(f"petición inesperada {url}")
        return falsa, pedidas

    def test_sin_creditos_en_success_es_rojo(self):
        falsa, pedidas = self.peticion_falsa(True)
        with unittest.mock.patch.object(pm, "peticion", falsa):
            r = pm.chk_ejecuciones(self.tenant(), pm.CONFIG_DEFECTO, {}, "wf1")
        self.assertEqual(r.estado, "rojo")
        self.assertIn("sin créditos", r.valor)
        self.assertNotIn("/executions/56?", " ".join(pedidas))  # la corta no llegó al modelo: no se descarga

    def test_fallo_antiguo_con_ultima_bien_es_ambar(self):
        """Tras recargar, la conversación más reciente va bien pero una anterior de la muestra tenía relleno: ámbar, no rojo."""
        from datetime import timedelta, timezone
        ahora = datetime.now(timezone.utc)
        def ej(i, minutos):
            ini = ahora - timedelta(minutes=minutos)
            return {"id": str(i), "status": "success", "startedAt": ini.isoformat().replace("+00:00", "Z"),
                    "stoppedAt": (ini + timedelta(seconds=8)).isoformat().replace("+00:00", "Z")}
        reciente, antigua = ej(70, 3), ej(69, 30)
        def falsa(url, cab=None, timeout=6, metodo="GET", max_bytes=0):
            if "status=error" in url:
                return pm.Resp(200, b'{"data": []}')
            if "executions?workflowId" in url:
                return pm.Resp(200, json.dumps({"data": [reciente, antigua]}).encode())
            if "/executions/70?" in url:
                return pm.Resp(200, json.dumps({"data": {"resultData": {"runData": {"Vindam AI Model": [{"data": {}}]}}}}).encode())
            if "/executions/69?" in url:
                return pm.Resp(200, json.dumps({"data": {"resultData": {"runData": {"Vindam AI Model": [{"error": {"description": "You have no credits remaining"}}]}}}}).encode())
            raise AssertionError(url)
        with unittest.mock.patch.object(pm, "peticion", falsa):
            r = pm.chk_ejecuciones(self.tenant(), pm.CONFIG_DEFECTO, {}, "wf1")
        self.assertEqual(r.estado, "ambar", r.detalle)
        self.assertIn("la última conversación fue bien", r.detalle)

    def test_con_creditos_no_cambia(self):
        falsa, _ = self.peticion_falsa(False)
        with unittest.mock.patch.object(pm, "peticion", falsa):
            r = pm.chk_ejecuciones(self.tenant(), pm.CONFIG_DEFECTO, {}, "wf1")
        self.assertNotEqual(r.estado, "rojo")
        self.assertNotIn("sin créditos", r.valor)


class FalsosPositivos(unittest.TestCase):
    """Lo que no es un fallo no sube el semáforo: silencio sin tráfico, traspasos a humano, clave local de scripts."""

    def ejecuciones_viejas(self, horas, **tcfg):
        from datetime import timedelta, timezone
        ini = datetime.now(timezone.utc) - timedelta(hours=horas)
        ej = {"id": "1", "status": "success", "startedAt": ini.isoformat().replace("+00:00", "Z"),
              "stoppedAt": (ini + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")}
        def falsa(url, cab=None, timeout=6, metodo="GET", max_bytes=0):
            if "status=error" in url:
                return pm.Resp(200, b'{"data": []}')
            if "executions?workflowId" in url:
                return pm.Resp(200, json.dumps({"data": [ej]}).encode())
            return pm.Resp(200, json.dumps({"data": {"resultData": {"runData": {}}}}).encode())
        t = pm.Tenant("buscasa", "buscasa", Path("/nada"), tcfg, env={"N8N_BASE_URL": "https://n8n.test"})
        with unittest.mock.patch.object(pm, "peticion", falsa):
            return pm.chk_ejecuciones(t, pm.CONFIG_DEFECTO, {}, "wf1")

    def test_silencio_sin_trafico_no_es_ambar(self):
        r = self.ejecuciones_viejas(119)
        self.assertEqual(r.estado, "verde", r.detalle)
        self.assertIn("119 h", r.detalle)

    def test_silencio_con_alerta_sigue_siendo_ambar(self):
        self.assertEqual(self.ejecuciones_viejas(119, silencio_alerta=True).estado, "ambar")

    def test_chatwoot_ignora_traspasos_a_humano(self):
        import time
        viejo = time.time() - 10 * 3600
        conv = [{"labels": ["requiere_humano"], "last_activity_at": viejo} for _ in range(25)]
        def falsa(url, cab=None, timeout=6, metodo="GET", max_bytes=0):
            if url.endswith("/profile"):
                return pm.Resp(200, b"{}")
            return pm.Resp(200, json.dumps({"data": {"meta": {"unassigned_count": 25}, "payload": conv}}).encode())
        t = pm.Tenant("vindam", "vindam", Path("/nada"), {}, env={"CW_URL": "https://cw.test", "CW_API_KEY_ADMIN": "x"})
        with unittest.mock.patch.object(pm, "peticion", falsa):
            r = pm.chk_chatwoot(t, pm.CONFIG_DEFECTO)[0]
        self.assertEqual(r.estado, "verde", r.detalle)
        self.assertIn("25 con requiere_humano", r.detalle)
        conv.append({"labels": [], "last_activity_at": viejo})
        with unittest.mock.patch.object(pm, "peticion", falsa):
            self.assertEqual(pm.chk_chatwoot(t, pm.CONFIG_DEFECTO)[0].estado, "ambar")

    def test_clave_local_rechazada_es_ambar(self):
        t = pm.Tenant("loyal-services", "loyal", Path("/nada"), {}, env={"OPENAI_API_KEY": "sk-x"})
        with unittest.mock.patch.object(pm, "peticion", lambda *a, **k: pm.Resp(401, b"{}")):
            self.assertEqual(pm.chk_openai(t, pm.CONFIG_DEFECTO)[0].estado, "ambar")


class SaldoOpenAI(unittest.TestCase):
    """Avisar antes de quedarse sin créditos: saldo ≈ recarga − gasto (Costs API) y días al ritmo actual."""

    def costes(self, usd_por_dia, dias=10):
        from datetime import timedelta, timezone
        ahora = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        cubos = [{"start_time": int((ahora - timedelta(days=i)).timestamp()), "results": [{"amount": {"value": usd_por_dia, "currency": "usd"}}]}
                 for i in range(dias)]
        return lambda url, cab=None, timeout=6, metodo="GET", max_bytes=0: pm.Resp(200, json.dumps({"data": cubos, "has_more": False}).encode())

    def cfg(self, recarga, hace_dias):
        from datetime import timedelta, timezone
        fecha = (datetime.now(timezone.utc) - timedelta(days=hace_dias)).strftime("%Y-%m-%d")
        c = json.loads(json.dumps(pm.CONFIG_DEFECTO))
        c["openai_saldo"].update({"recarga_usd": recarga, "fecha_recarga": fecha})
        return c

    def test_sin_clave_de_administracion(self):
        r = pm.chk_openai_saldo({}, pm.CONFIG_DEFECTO)[0]
        self.assertEqual((r.estado, r.valor), ("na", "sin clave de administración"))

    def test_saldo_holgado_es_verde(self):
        with unittest.mock.patch.object(pm, "peticion", self.costes(1.0)):
            r = pm.chk_openai_saldo({"OPENAI_ADMIN_KEY": "sk-admin"}, self.cfg(recarga=50, hace_dias=5))[0]
        self.assertEqual(r.estado, "verde", r.detalle)
        self.assertIn("ritmo 1.00 $/día", r.detalle)
        self.assertNotIn("sk-admin", r.detalle + r.valor)

    def test_pocos_dias_es_ambar_y_minimo_es_rojo(self):
        with unittest.mock.patch.object(pm, "peticion", self.costes(2.0)):
            ambar = pm.chk_openai_saldo({"OPENAI_ADMIN_KEY": "k"}, self.cfg(recarga=30, hace_dias=5))[0]  # 30 − 12 = 18 $ → 9 días… no: 18/2 = 9 > 7
            rojo = pm.chk_openai_saldo({"OPENAI_ADMIN_KEY": "k"}, self.cfg(recarga=20, hace_dias=5))[0]  # 20 − 12 = 8 $ ≤ mínimo 10
        self.assertEqual(rojo.estado, "rojo", rojo.detalle)
        with unittest.mock.patch.object(pm, "peticion", self.costes(2.0)):
            ambar = pm.chk_openai_saldo({"OPENAI_ADMIN_KEY": "k"}, self.cfg(recarga=24, hace_dias=5))[0]  # 24 − 12 = 12 $ → 6 días
        self.assertEqual(ambar.estado, "ambar", ambar.detalle)

    def test_sin_recarga_configurada_informa_del_ritmo(self):
        with unittest.mock.patch.object(pm, "peticion", self.costes(0.5)):
            r = pm.chk_openai_saldo({"OPENAI_ADMIN_KEY": "k"}, pm.CONFIG_DEFECTO)[0]
        self.assertEqual((r.estado, r.valor), ("ambar", "saldo desconocido"))
        self.assertIn("recarga_usd", r.detalle)


class Sonda(unittest.TestCase):
    """Sonda de conversación: un mensaje por el canal web de pruebas y una respuesta real, no de relleno."""

    def tenant(self, nombre="vindam", formato="c3", env=None, **cfg):
        base = {"voz": nombre, "sonda_formato": formato, "sonda_webhook": "wpp"}
        base.update(cfg)
        return pm.Tenant(nombre, nombre, Path("/nada"), base, env={"N8N_BASE_URL": "https://x-n8n.test", **(env or {})})

    def cfg(self, **extra):
        c = json.loads(json.dumps(pm.CONFIG_DEFECTO))
        c["sonda_e2e"] = True
        c.update(extra)
        return c

    def sonda_falsa(self, cuerpo, status=200, ms=1200, error=""):
        llamadas = []

        def falsa(url, cuerpo_env, cabeceras=None, timeout=40):
            llamadas.append((url, cuerpo_env, cabeceras or {}))
            return pm.Resp(status, cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode(), {}, ms, error)
        return falsa, llamadas

    def test_desactivada_no_envia(self):
        falsa, llamadas = self.sonda_falsa({"message": "hola"})
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            r = pm.chk_sonda_e2e(self.tenant(), json.loads(json.dumps(pm.CONFIG_DEFECTO)))[0]
        self.assertEqual((r.estado, llamadas), ("na", []))
        self.assertIn("desactivada", r.valor)

    def test_c3_respuesta_real_es_verde(self):
        falsa, llamadas = self.sonda_falsa({"message": "¡Hola! Ofrecemos seguros de auto y hogar.", "intent": "AGENT"}, ms=9000)
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            r = pm.chk_sonda_e2e(self.tenant(), self.cfg())[0]
        self.assertEqual(r.estado, "verde")
        self.assertEqual(r.valor, "responde en 9 s")
        url, cuerpo, _ = llamadas[0]
        self.assertEqual(url, "https://x-n8n.test/webhook/wpp")
        self.assertTrue(cuerpo["attention_id"].startswith("web_demo_parte_"))
        self.assertEqual((cuerpo["channel"], cuerpo["message"]), ("WHATSAPP", "Hola, ¿qué servicios ofrecen?"))

    def test_relleno_es_rojo(self):
        for texto in ("Perdón, ¿me lo repites?", "Sorry, could you repeat that?", "Dame un momento, por favor 🙌"):
            falsa, _ = self.sonda_falsa({"message": texto})
            with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
                r = pm.chk_sonda_e2e(self.tenant(), self.cfg())[0]
            self.assertEqual(r.estado, "rojo", texto)
            self.assertIn("relleno", r.valor)

    def test_vacio_y_http_error_son_rojo(self):
        falsa, _ = self.sonda_falsa({"message": "", "intent": "FAQ"})  # loyal con clave mala
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            self.assertEqual(pm.chk_sonda_e2e(self.tenant(), self.cfg())[0].estado, "rojo")
        falsa, _ = self.sonda_falsa(b"", status=0, error="timeout")
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            r = pm.chk_sonda_e2e(self.tenant(), self.cfg())[0]
        self.assertEqual((r.estado, r.valor), ("rojo", "sin respuesta"))

    def test_lenta_dudosa_y_404_son_ambar(self):
        falsa, _ = self.sonda_falsa({"message": "Claro, te cuento…"}, ms=25000)
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            r = pm.chk_sonda_e2e(self.tenant(), self.cfg())[0]
        self.assertEqual((r.estado, r.valor), ("ambar", "lenta, 25 s"))
        falsa, _ = self.sonda_falsa({"message": "Elige una opción:", "options": ["a", "b"]})
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            self.assertEqual(pm.chk_sonda_e2e(self.tenant(), self.cfg())[0].estado, "ambar")
        falsa, _ = self.sonda_falsa({"code": 404, "message": "The requested webhook is not registered."}, status=404, error="HTTP 404")
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            r = pm.chk_sonda_e2e(self.tenant(), self.cfg())[0]
        self.assertEqual((r.estado, r.valor), ("ambar", "canal de pruebas no registrado"))

    def test_chatwoot_buscasa(self):
        falsa, llamadas = self.sonda_falsa({"status": "ok", "session_id": "x", "response": {"text": "Tenemos pisos en Monterrey.", "bubbles": []}})
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            r = pm.chk_sonda_e2e(self.tenant("buscasa", "chatwoot", sonda_webhook="wpp_staging"), self.cfg())[0]
        self.assertEqual(r.estado, "verde")
        url, c, _ = llamadas[0]
        self.assertEqual(url, "https://x-n8n.test/webhook/wpp_staging")
        self.assertEqual((c["event"], c["message_type"], c["sender"]["type"]), ("message_created", 0, "contact"))
        self.assertTrue(c["conversation"]["contact_inbox"]["source_id"].startswith("web_demo_parte_"))
        self.assertIsInstance(c["id"], int)
        self.assertIsInstance(c["conversation"]["id"], int)
        self.assertTrue(1_000_000 <= c["conversation"]["id"] < 9_000_000)
        self.assertEqual(c["content"], c["conversation"]["messages"][0]["content"])
        self.assertEqual(c["id"], c["conversation"]["messages"][0]["id"])

    def test_chatwoot_eurotalent_id_texto(self):
        falsa, llamadas = self.sonda_falsa({"status": "ok", "response": {"text": "Hola, somos Eurotalent."}})
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            pm.chk_sonda_e2e(self.tenant("eurotalent", "chatwoot", sonda_conversacion_texto=True), self.cfg())
        c = llamadas[0][1]
        self.assertIsInstance(c["conversation"]["id"], str)
        self.assertTrue(c["conversation"]["id"].startswith("web_demo_parte_"))

    def test_silencio_buscado_es_ambar(self):
        # sin `response`, o con `response.text` vacío (nodo «human agent is handling» / storm guard de buscasa y eurotalent)
        for cuerpo in ({"status": "ok", "session_id": "x"}, {"status": "ok", "session_id": "x", "response": {"text": "", "images": [], "handled_by": "human_agent"}},
                       {"status": "ok", "response": {}}):
            falsa, _ = self.sonda_falsa(cuerpo)
            with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
                r = pm.chk_sonda_e2e(self.tenant("buscasa", "chatwoot"), self.cfg())[0]
            self.assertEqual(r.estado, "ambar", cuerpo)
            self.assertIn("silencio", r.valor)

    def test_loyal_lleva_api_key_y_resource_id(self):
        falsa, llamadas = self.sonda_falsa({"message": "Con gusto, ofrecemos seguros.", "intent": "FAQ"})
        t = self.tenant("loyal-services", "c3", env={"C3_WEBHOOK_APIKEY": "clave-de-prueba-larga"}, sonda_webhook="wpp_staging", sonda_resource_id="7139247727")
        with unittest.mock.patch.object(pm, "peticion_sonda", falsa):
            r = pm.chk_sonda_e2e(t, self.cfg())[0]
        _, c, cab = llamadas[0]
        self.assertEqual((cab.get("X-Api-Key"), c["resource_id"]), ("clave-de-prueba-larga", "7139247727"))
        self.assertNotIn("clave-de-prueba-larga", r.detalle + r.valor)

    def test_sin_url_ni_formato_es_na(self):
        t = pm.Tenant("x", "x", Path("/nada"), {"voz": "x"}, env={})
        r = pm.chk_sonda_e2e(t, self.cfg())[0]
        self.assertEqual(r.estado, "na")


class SondaEnEjecutar(unittest.TestCase):
    """El parte normal nunca hace POST con sonda_e2e=false; con true, la sonda entra en el bloque tester."""

    def raiz(self, d):
        carpeta = Path(d) / "x"
        (carpeta / "channels/chatcore whatsapp/config").mkdir(parents=True)
        env = carpeta / ".env"
        env.write_text("N8N_BASE_URL=https://x-n8n.test\n", encoding="utf-8")
        env.chmod(0o600)
        (carpeta / "channels/chatcore whatsapp/config/tenant_config.json").write_text('{"observability": {}}', encoding="utf-8")
        c = json.loads(json.dumps(pm.CONFIG_DEFECTO))
        c["raiz_tenants"] = d
        c["tenants"] = {"x": {"voz": "equis", "sonda_formato": "c3", "sonda_webhook": "wpp"}}
        return c

    def test_apagada_no_llama_a_peticion_sonda(self):
        def prohibido(*a, **k):
            raise AssertionError("POST con la sonda apagada")
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(pm, "peticion_sonda", prohibido), \
                unittest.mock.patch.object(pm, "peticion", lambda *a, **k: pm.Resp(200, b"ok")):
            parte = pm.ejecutar(self.raiz(d), {"tester"}, None, {}, 0)
        sondas = [r for r in parte["resultados"] if r.check == "sonda"]
        self.assertEqual([(r.estado, r.ambito) for r in sondas], [("na", "global")])  # un solo aviso, no uno por tenant

    def test_tenant_puede_apagarla_aunque_global_este_encendida(self):
        def prohibido(*a, **k):
            raise AssertionError("POST con la sonda apagada en el tenant")
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(pm, "peticion_sonda", prohibido), \
                unittest.mock.patch.object(pm, "peticion", lambda *a, **k: pm.Resp(200, b"ok")):
            cfg = self.raiz(d)
            cfg["sonda_e2e"] = True
            cfg["tenants"]["x"]["sonda_e2e"] = False
            parte = pm.ejecutar(cfg, {"tester"}, None, {}, 0)
        self.assertEqual([(r.estado, r.ambito) for r in parte["resultados"] if r.check == "sonda"], [("na", "x")])

    def test_encendida_sale_en_tabla_y_json(self):
        def falsa(url, cuerpo, cabeceras=None, timeout=40):
            return pm.Resp(200, b'{"message": "Perd\\u00f3n, \\u00bfme lo repites?"}', {}, 8000)
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(pm, "peticion_sonda", falsa), \
                unittest.mock.patch.object(pm, "peticion", lambda *a, **k: pm.Resp(200, b"ok")):
            cfg = self.raiz(d)
            cfg["sonda_e2e"] = True
            parte = pm.ejecutar(cfg, {"tester"}, None, {}, 0)
        parte.update(fecha="2026-10-20", hora="08:00", semaforo=pm.semaforo(parte["resultados"]), ruta_md=Path("/x.md"))
        parte["resumen_voz"] = pm.resumen_voz(parte, parte["tenants"])
        self.assertEqual(parte["semaforo"], "rojo")
        self.assertIn("equis sonda de conversación relleno: bot roto", parte["resumen_voz"])
        self.assertIn("| sonda de conversación |", pm.a_markdown(parte))
        self.assertEqual(pm.a_json_compacto(parte)["tenants"]["equis"]["anomalias"], ["sonda de conversación: relleno: bot roto"])


class Simulacion(unittest.TestCase):
    def test_simular_no_toca_el_parte_real_ni_el_marcador(self):
        fixture = RAIZ / "tests" / "fixtures" / "parte_simulado.json"
        with tempfile.TemporaryDirectory() as d:
            partes, marcador = Path(d) / "partes", Path(d) / "parte.json"
            with unittest.mock.patch.object(pm, "PARTES", partes), unittest.mock.patch.object(pm, "MARCADOR", marcador), \
                    unittest.mock.patch.object(pm, "CACHE_PENDIENTES", partes / "pc.json"), unittest.mock.patch.object(pm.shutil, "which", lambda *_: None):
                parte = pm.generar(json.loads(json.dumps(pm.CONFIG_DEFECTO)), set(pm.BLOQUES), None, fixture)
            self.assertFalse(marcador.exists())
            self.assertIn("-simulado", parte["ruta_md"].name)
            self.assertEqual(sorted(p.name for p in partes.iterdir()), [parte["ruta_json"].name, parte["ruta_md"].name])


class Correo(unittest.TestCase):
    def test_clasificar(self):
        casos = [
            ("OpenAI <noreply@tm.openai.com>", "Your OpenAI API account has run out of credits", ("OpenAI", "alerta", "rojo")),
            ("OpenAI <noreply@email.openai.com>", "Introducing credits for new projects", ("OpenAI", "otro", "verde")),
            ("Meta for Business <notification@facebookmail.com>", "Quality rating of your phone number changed", ("Meta", "alerta", "ambar")),
            ("Supabase <no-reply@supabase.io>", "Your project is paused", ("Supabase", "alerta", "ambar")),
            ("Hostinger <billing@hostinger.com>", "Factura 2026-0144 disponible", ("Hostinger", "factura", "verde")),
            ("Juan <juan@marlovet.com>", "Dudas sobre el bot", ("marlovet.com", "cliente", "verde")),
            ("Soporte <soporte@desconocido.com>", "Payment failed for your account", ("desconocido.com", "alerta", "ambar")),
            ("Alguien <x@otro.com>", "Hola", ("otro.com", "otro", "verde")),
            # dominios parecidos (phishing): nunca rojo
            ("OpenAI <billing@openai.com.evil.ru>", "Your account has run out of credits", ("openai.com.evil.ru", "alerta", "ambar")),
            ("OpenAI <billing@notopenai.com>", "Your account has run out of credits", ("notopenai.com", "alerta", "ambar")),
            # avisos benignos de proveedores: ni rojo ni ámbar
            ("OpenAI <noreply@tm.openai.com>", "Your usage limit has been updated", ("OpenAI", "otro", "verde")),
            ("Hostinger <noreply@hostinger.com>", "Auto-renewal successful", ("Hostinger", "otro", "verde")),
            ("n8n <hello@n8n.io>", "Unlimited workflows: new pricing", ("n8n", "otro", "verde")),
            # suspensión: alerta, pero no «facturación»
            ("Meta <notification@facebookmail.com>", "Your WhatsApp Business account has been suspended", ("Meta", "alerta", "ambar")),
            # seguridad
            ("OpenAI <noreply@tm.openai.com>", "Your API key was exposed on GitHub", ("OpenAI", "alerta", "ambar")),
            # un aviso desde el propio dominio no se traga como «cliente»
            ("n8n <n8n@vindam.com>", "Workflow vindam_whatsapp failed", ("vindam.com", "alerta", "ambar")),
        ]
        for de, asunto, esperado in casos:
            c = pm.clasificar_correo(de, asunto, ["marlovet", "vindam"])
            self.assertEqual((c["fuente"], c["categoria"], c["nivel"]), esperado, (de, asunto))
        self.assertNotEqual(pm.clasificar_correo("notification@facebookmail.com", "Your account has been suspended")["motivo"], "facturación")

    def test_resumen(self):
        correos = [{"de": "a", "asunto": "x", "fecha": "", **pm.clasificar_correo("noreply@tm.openai.com", "You have run out of credits")},
                   {"de": "b", "asunto": "y", "fecha": "", **pm.clasificar_correo("x@otro.com", "Hola")}]
        r = pm.resumen_correos(correos)
        self.assertEqual(r.estado, "rojo")
        self.assertEqual(r.valor, "1 alerta de facturación: OpenAI")
        self.assertEqual(pm.resumen_correos([]).estado, "verde")

    def test_chk_correo_imap_falso(self):
        cab = (b"From: OpenAI <noreply@tm.openai.com>\r\nSubject: Your account has run out of credits\r\nDate: Tue, 20 Oct 2026 15:05:00 +0200\r\n\r\n",
               b"From: Ana <ana@buscasa.com>\r\nSubject: Pregunta\r\nDate: Tue, 20 Oct 2026 09:00:00 +0200\r\n\r\n")

        class ImapFalso:
            selecciones = []  # de clase: la instancia la crea chk_correo y no la vemos

            def __init__(self, host, timeout=None):
                pass

            def login(self, u, p):
                pass

            def select(self, buzon, readonly=False):
                ImapFalso.selecciones.append(readonly)
                return "OK", [b"2"]

            def search(self, cs, q):
                return "OK", [b"1 2"]

            def fetch(self, uid, partes):
                assert "BODY.PEEK" in partes
                return "OK", [(b"x", cab[int(uid) - 1])]

            def logout(self):
                pass
        with unittest.mock.patch.object(pm.imaplib, "IMAP4_SSL", ImapFalso):
            res, correos = pm.chk_correo({"TECH_IMAP_USER": "tech@vindam.com", "TECH_IMAP_PASS": "clave-aplicacion-xx"}, pm.CONFIG_DEFECTO)
        self.assertEqual(res[0].estado, "rojo")
        self.assertEqual(ImapFalso.selecciones, [True])  # readonly=True
        self.assertEqual([c["categoria"] for c in correos], ["alerta", "cliente"])  # alertas primero
        self.assertNotIn("clave-aplicacion-xx", json.dumps([asdict(r) for r in res]) + json.dumps(correos))


class RespuestasFallo(unittest.TestCase):
    """Fallos silenciosos: la ejecución consta como «success», pero el bot contestó con la frase de emergencia."""

    ES = "Perdón, ¿me lo repites?"
    EN = "Sorry, could you repeat that?"

    def setUp(self):
        import time
        self.ahora = time.time()
        self.urls = []
        self.metodos = []

    def msg(self, id_, conv, horas=1, tipo=1, privado=False, contenido=None, inbox=1):
        return {"id": id_, "conversation_id": conv, "message_type": tipo, "private": privado, "inbox_id": inbox,
                "content": self.ES if contenido is None else contenido, "created_at": int(self.ahora - horas * 3600)}

    def tenant(self, nombre="buscasa", carpeta="/nada", **env):
        env = env or {"CW_URL": "https://cw.test", "CW_API_KEY_ADMIN": "clave-secreta-cw"}
        return pm.Tenant(nombre, nombre, Path(carpeta), {}, env=env)

    def correr(self, paginas=None, conversaciones=None, t=None):
        """paginas: {frase: [página, ...]}, y una página puede ser un Resp ya hecho (fallo de lectura)."""
        paginas = paginas or {}
        conversaciones = conversaciones or {}

        def falsa(url, cab=None, timeout=6, metodo="GET", max_bytes=0):
            self.urls.append(url)
            self.metodos.append(metodo)
            ruta = urllib.parse.urlsplit(url)
            if ruta.path.endswith("/search/messages"):
                q = urllib.parse.parse_qs(ruta.query)
                lista = paginas.get(q["q"][0], [])
                num = int(q.get("page", ["1"])[0])
                pagina = lista[num - 1] if num <= len(lista) else []
                if isinstance(pagina, pm.Resp):
                    return pagina
                return pm.Resp(200, json.dumps({"payload": {"messages": pagina}}).encode())
            conv = conversaciones.get(int(ruta.path.rsplit("/", 1)[1]), {"labels": [], "meta": {"sender": {"name": "Ana", "identifier": None}}})
            return conv if isinstance(conv, pm.Resp) else pm.Resp(200, json.dumps(conv).encode())
        with unittest.mock.patch.object(pm, "peticion", falsa):
            return pm.chk_respuestas_fallo(t or self.tenant(), pm.CONFIG_DEFECTO)[0]

    def test_nombre_legible_registrado(self):
        self.assertEqual(pm.NOMBRE_CHECK["respuestas_fallo"], "respuestas de emergencia")

    def test_cliente_sin_frase_fiable_es_na_y_no_consulta(self):
        r = self.correr(t=self.tenant("loyal-services"))
        self.assertEqual((r.check, r.ambito, r.estado), ("respuestas_fallo", "loyal-services", "na"))
        self.assertEqual(self.urls, [])

    def test_loyal_no_tiene_frase_porque_su_repregunta_es_legitima(self):
        self.assertNotIn("loyal-services", pm.FRASES_FALLO)

    def test_dame_un_momento_no_cuenta_porque_tambien_es_derivacion_normal(self):
        self.assertNotIn("Dame un momento", [f for c in pm.FRASES_FALLO.values() for f in c["frases"]])

    def test_sin_credencial_es_na_y_no_consulta(self):
        r = self.correr(t=self.tenant("eurotalent", CW_URL="https://cw.test", CW_API_KEY_ADMIN=""))
        self.assertEqual(r.estado, "na")
        self.assertIn("credencial", r.valor)
        self.assertEqual(self.urls, [])

    def test_cero_es_verde_y_avisa_de_la_cobertura_parcial(self):
        r = self.correr()
        self.assertEqual(r.estado, "verde")
        self.assertIn("cobertura parcial", r.valor)
        self.assertIn("inmueble", r.detalle)  # en buscasa, el punto ciego concreto

    def test_una_conversacion_es_ambar_aunque_tenga_varios_mensajes(self):
        r = self.correr({self.ES: [[self.msg(1, 10), self.msg(2, 10)]]})
        self.assertEqual(r.estado, "ambar")
        self.assertTrue(r.valor.startswith("2 en 1 conversación en 24 h"), r.valor)
        self.assertEqual(r.detalle.count("24 h"), 1, r.detalle)
        self.assertIn("cobertura parcial", r.valor)

    def test_dos_conversaciones_es_rojo(self):
        r = self.correr({self.ES: [[self.msg(1, 10), self.msg(2, 11)]]})
        self.assertEqual(r.estado, "rojo")
        self.assertTrue(r.valor.startswith("2 en 2 conversaciones"), r.valor)

    def test_cuenta_las_frases_de_todos_los_idiomas_sin_duplicar(self):
        en = self.msg(2, 11, contenido=self.EN)
        r = self.correr({self.ES: [[self.msg(1, 10)]], self.EN: [[en, en]]})
        self.assertEqual(r.estado, "rojo")
        self.assertTrue(r.valor.startswith("2 en 2 conversaciones"), r.valor)

    def test_solo_salientes_publicos_recientes_y_con_la_frase(self):
        r = self.correr({self.ES: [[self.msg(1, 10, tipo=0), self.msg(2, 11, privado=True), self.msg(3, 12, contenido="otra cosa"), self.msg(4, 13, horas=25)]]})
        self.assertEqual(r.estado, "verde", r.valor)

    def test_excluye_bandeja_de_prueba_sin_pedir_la_conversacion(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "channels/chatcore whatsapp/config"
            ruta.mkdir(parents=True)
            (ruta / "tenant_config.json").write_text(json.dumps({"transport": {"chatwoot": {"inboxes_prueba": {"qa": 2}}}}), encoding="utf-8")
            r = self.correr({self.ES: [[self.msg(1, 10, inbox=2)]]}, t=self.tenant(carpeta=d))
        self.assertEqual(r.estado, "verde", r.valor)
        self.assertIn("1 de prueba", r.detalle)
        self.assertFalse([u for u in self.urls if "/conversations/" in u])

    def test_excluye_etiqueta_de_prueba_y_contacto_sintetico(self):
        convs = {10: {"labels": ["prueba"], "meta": {"sender": {}}},
                 11: {"labels": [], "meta": {"sender": {"identifier": "audit_123", "name": "x"}}},
                 12: {"labels": [], "meta": {"sender": {"identifier": None, "name": "QA Simulación"}}}}
        r = self.correr({self.ES: [[self.msg(1, 10), self.msg(2, 11), self.msg(3, 12)]]}, convs)
        self.assertEqual(r.estado, "verde", r.valor)
        self.assertIn("3 de prueba", r.detalle)

    def test_nombre_que_empieza_por_qa_sin_ser_prueba_cuenta(self):
        convs = {10: {"labels": [], "meta": {"sender": {"identifier": None, "name": "Qasim"}}}}
        self.assertEqual(self.correr({self.ES: [[self.msg(1, 10)]]}, convs).estado, "ambar")

    def test_conversacion_que_no_se_puede_verificar_cuenta_y_se_dice(self):
        r = self.correr({self.ES: [[self.msg(1, 10)]]}, {10: pm.Resp(500)})
        self.assertEqual(r.estado, "ambar")
        self.assertIn("1 sin verificar", r.detalle)

    def test_lectura_fallida_es_error_no_verde(self):
        for resp in (pm.Resp(500), pm.Resp(401), pm.Resp(0, error="timeout"), pm.Resp(200, b"<html>"), pm.Resp(200, b'{"payload": []}'), pm.Resp(200, b'{"payload": {"messages": {}}}')):
            with self.subTest(resp=resp):
                self.assertEqual(self.correr({self.ES: [resp]}).estado, "error")

    def test_mensaje_sin_fecha_valida_es_error_no_verde(self):
        malo = {**self.msg(1, 10), "created_at": "ayer"}
        self.assertEqual(self.correr({self.ES: [[malo]]}).estado, "error")

    def test_fallo_en_una_pagina_posterior_es_error_y_conserva_la_cifra(self):
        r = self.correr({self.ES: [[self.msg(1, 10)], pm.Resp(500)]})
        self.assertEqual(r.estado, "error")
        self.assertIn("al menos 1", r.valor)

    def test_solo_get_a_search_messages_con_la_frase_codificada(self):
        self.correr()
        self.assertEqual(set(self.metodos), {"GET"})
        self.assertIn("https://cw.test/api/v1/accounts/1/search/messages?q=Perd%C3%B3n%2C%20%C2%BFme%20lo%20repites%3F", self.urls[0])
        self.assertEqual(len(self.urls), 2)  # una por frase de buscasa

    def test_deja_de_paginar_al_salir_de_la_ventana(self):
        self.correr({self.ES: [[self.msg(1, 10), self.msg(2, 11, horas=30)], [self.msg(3, 12)]]})
        self.assertEqual(len([u for u in self.urls if "q=Perd" in u]), 1)

    def test_tope_de_paginas_avisa_de_que_es_un_minimo(self):
        paginas = [[self.msg(n * 100 + i, 10) for i in range(15)] for n in range(pm.MAX_PAGINAS_FALLO + 2)]
        r = self.correr({self.ES: paginas})
        self.assertEqual(len([u for u in self.urls if "q=Perd" in u]), pm.MAX_PAGINAS_FALLO)
        self.assertTrue(r.valor.startswith("al menos "), r.valor)
        self.assertEqual(r.estado, "ambar")

    def test_tope_de_conversaciones_cuenta_el_resto_sin_verificar(self):
        n = pm.MAX_CONV_FALLO + 3
        r = self.correr({self.ES: [[self.msg(i, 1000 + i) for i in range(n)]]})
        self.assertEqual(len([u for u in self.urls if "/conversations/" in u]), pm.MAX_CONV_FALLO)
        self.assertEqual(r.estado, "rojo")
        self.assertTrue(r.valor.startswith(f"{n} en {n} conversaciones"), r.valor)
        self.assertIn("3 sin verificar", r.detalle)

    def test_tiempo_agotado_es_error(self):
        relojes = iter([0, pm.TIEMPO_MAX_FALLO_S + 1])
        with unittest.mock.patch.object(pm.time, "monotonic", lambda: next(relojes, pm.TIEMPO_MAX_FALLO_S + 1)):
            r = self.correr({self.ES: [[self.msg(1, 10)]]})
        self.assertEqual(r.estado, "error")
        self.assertEqual(self.urls, [])

    def test_no_saca_contenido_ni_contactos_ni_la_clave(self):
        contenido = self.ES + " Ana +573001112233"
        convs = {10: {"labels": [], "meta": {"sender": {"name": "Ana Pérez", "identifier": "+573001112233"}}}}
        r = self.correr({self.ES: [[self.msg(1, 10, contenido=contenido)]]}, convs)
        salida = json.dumps(asdict(r), ensure_ascii=False)
        self.assertEqual(r.estado, "ambar")
        for prohibido in ("Ana", "573001112233", "clave-secreta-cw"):
            self.assertNotIn(prohibido, salida)

    def raiz(self, d):
        carpeta = Path(d) / "loyal-services"
        (carpeta / "channels/chatcore whatsapp/config").mkdir(parents=True)
        ruta = carpeta / ".env"
        ruta.write_text("N8N_BASE_URL=https://x-n8n.test\n", encoding="utf-8")
        ruta.chmod(0o600)
        (carpeta / "channels/chatcore whatsapp/config/tenant_config.json").write_text('{"observability": {}}', encoding="utf-8")
        c = json.loads(json.dumps(pm.CONFIG_DEFECTO))
        c["raiz_tenants"] = d
        c["tenants"] = {"loyal-services": {"voz": "loyal"}}
        return c

    def test_entra_en_el_bloque_tenants(self):
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(pm, "peticion", lambda *a, **k: pm.Resp(200, b"{}")):
            parte = pm.ejecutar(self.raiz(d), {"tenants"}, None, {}, 0)
        self.assertEqual([(r.ambito, r.estado) for r in parte["resultados"] if r.check == "respuestas_fallo"], [("loyal-services", "na")])

    def test_no_entra_en_otros_bloques(self):
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(pm, "peticion", lambda *a, **k: pm.Resp(200, b"{}")):
            parte = pm.ejecutar(self.raiz(d), {"supabase"}, None, {}, 0)
        self.assertEqual([r for r in parte["resultados"] if r.check == "respuestas_fallo"], [])

    def test_columna_en_la_tabla_del_informe(self):
        res = [Resultado("respuestas_fallo", "buscasa", "ambar", "1 en 1 conversación", "d")]
        parte = {"resultados": res, "tenants": {"buscasa": "buscasa"}, "fecha": "2026-11-03", "hora": "08:00", "semaforo": "ambar", "resumen_voz": "x",
                 "pendientes": [], "trabajadores": [], "correos": [], "ruta_md": Path("/x.md")}
        lineas = pm.a_markdown(parte).split("\n")
        self.assertIn("| respuestas de emergencia |", next(ln for ln in lineas if ln.startswith("| tenant |")))
        self.assertIn("⚠️", next(ln for ln in lineas if ln.startswith("| buscasa |")))

    def test_tablero_crea_tarjeta_con_anomalia_y_no_con_na(self):
        import tablero
        parte = {"compacto": {"fecha": "2026-11-03"}, "tenants": {"buscasa": "buscasa", "loyal-services": "loyal"}, "resultados": [
            asdict(Resultado("respuestas_fallo", "buscasa", "rojo", "3 en 2 conversaciones; cobertura parcial", "d")),
            asdict(Resultado("respuestas_fallo", "loyal-services", "na", "sin frase de fallo identificable", "d")),
        ]}
        plan = tablero.planificar(parte, [])
        escrituras = plan["cambios"]
        self.assertEqual([e["id"] for e in escrituras], ["buscasa--respuestas_fallo"])
        tarjeta = escrituras[0]["data"]
        self.assertEqual((tarjeta["titulo"], tarjeta["nivel"], tarjeta["cliente"], tarjeta["columna"]), ("respuestas de emergencia", "rojo", "buscasa", "nuevos"))
        self.assertEqual(tarjeta["detalle"], ["3 en 2 conversaciones; cobertura parcial"])
        self.assertEqual(plan["sin_comprobar"], ["loyal: respuestas de emergencia: sin frase de fallo identificable"])
