#!/usr/bin/env python3
"""Parte matinal de Ío: chequeos de SOLO LECTURA sobre los servicios en producción, pendientes y marcador del día.

  narrador parte                 genera el parte (o reutiliza el de hace menos de `cache_horas`) e imprime un resumen
  narrador parte --json          salida JSON compacta: solo anomalías, contadores y pendientes (lo que lee Ío)
  narrador parte --md            imprime el informe completo en Markdown del día
  narrador parte --forzar        ignora la caché y vuelve a comprobar
  narrador parte --solo A,B      solo esos bloques: tenants, supabase, meta, tls, tester, openai, vps, pendientes, trabajadores, correo
  narrador parte --tenant T      solo ese tenant
  narrador parte --entregado     marca el parte de hoy como entregado (lo hace Ío al terminar de locutarlo)
  narrador parte --simular [F]   resultados falsos de un fixture, sin red (pruebas)
  narrador parte --si-toca       solo genera si aún no hay parte del día operativo (para un timer)
  narrador parte --estado        imprime qué toca (nuevo | pendiente_entrega | en_curso | no) y la frase de arranque

Configuración no secreta en ~/.config/narrador/parte.json. Las credenciales se leen de los .env de cada tenant
(nunca se copian ni se imprimen); lo que no existe en ningún tenant va en ~/.config/narrador/parte.env (permisos 600).
Garantía: la única salida a la red es `peticion()`, que solo admite GET y HEAD. Nunca se llama a un webhook de producción.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import email.header
import email.utils
import hashlib
import imaplib
import json
import os
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import IO_JSON, RUNTIME, TRABAJADORES  # noqa: E402

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "narrador"
CONFIG_PARTE = CONFIG_DIR / "parte.json"
SECRETOS_PARTE = CONFIG_DIR / "parte.env"
MARCADOR = RUNTIME / "parte.json"
PARTES = RUNTIME / "partes"
CACHE_PENDIENTES = PARTES / "pendientes_cache.json"
REVISION_MEMORIA = RUNTIME / "memoria-revision.json"  # la escribe el timer semanal io-memoria-revisar
TTL_EN_CURSO_MIN = 10
DIAS_HISTORIAL = 30

CONFIG_DEFECTO: dict = {
    "hora_corte": 5,  # el día operativo empieza a esta hora: un arranque a las 00:30 no es «nuevo día»
    "cache_horas": 2,
    "ssh": False,  # chequeo de los VPS por SSH (uptime, disco, memoria, contenedores)
    "imap_tech": False,  # correo de tech@ por IMAP solo lectura (credenciales en parte.env)
    "raiz_tenants": "~/Documentos/greedisgood/vindam/chatcore-n8n/tenants",
    "env": ".env",
    "config": "channels/chatcore whatsapp/config/tenant_config.json",
    "cw_account": 1,
    "silencio_horas": {"laborable": 12, "finde": 48},  # «finde» se aplica sábado, domingo y lunes por la mañana
    "umbrales": {"latencia_ms": 1500, "errores_ambar": 1, "errores_rojo": 4, "tls_ambar": 21, "tls_rojo": 7,
                 "cw_sin_asignar_h": 4, "meta_token_ambar_d": 14, "meta_token_rojo_d": 3,
                 "disco_ambar": 80, "disco_rojo": 90, "ram_libre_min": 10},
    "tenants": {
        "buscasa": {"voz": "buscasa", "supabase_tablas": ["propiedades"],
                    "workflows_extra": {"web": "5mdlzf3COOxEQDAw"},
                    "tester": "https://buscasa-demo.vindam.com",
                    "pendientes": ["CLAUDE.md", "pendiente_.txt"]},
        "eurotalent": {"voz": "eurotalent", "supabase_tablas": ["eurotalent_catalogo"],
                       "workflows_extra": {"cierre diferido": "4iemJ6X3vRWYd2x2"},
                       "tester": "https://eurotalent-demo.vindam.com",
                       "pendientes": ["CLAUDE.md", "docs/PASO_A_PASO_pendientes.md"]},
        "loyal-services": {"voz": "loyal", "chatwoot": False, "meta": False,
                           "env_extra": ["channels/chatcore whatsapp/openai_key4testing.env"],
                           "supabase_tablas": ["catalogo_loyalsvc"],
                           "workflows_extra": {"seguimiento": "$N8N_FOLLOWUP_WF_ID", "lista blanca": "$N8N_WHITELIST_WF_ID"},
                           "tester": "https://loyalsvc-demo.vindam.com",
                           "pendientes": ["CLAUDE.md", "PREPARACION_PRODUCCION_lsllc.md"]},
        "marlovet": {"voz": "marlovet", "supabase_tablas": ["marlovet_catalogo"],
                     "tester": "https://marlovet-demo.vindam.com", "pendientes": ["CLAUDE.md"]},
        "vindam": {"voz": "vindam", "supabase_tablas": ["vindam_catalogo"],
                   "workflows_extra": {"web": "MQQQYpKbxBrNv5kE"}, "pendientes": ["CLAUDE.md"]},
    },
}

BLOQUES = ("tenants", "supabase", "meta", "tls", "tester", "openai", "vps", "pendientes", "trabajadores", "correo")
NOMBRE_CHECK = {
    "n8n": "n8n", "wf_activo": "workflow", "ejecuciones": "ejecuciones", "chatwoot": "Chatwoot",
    "supabase": "Supabase", "meta_numero": "número de WhatsApp", "meta_token": "token de Meta", "tls": "certificado",
    "tester": "chat de pruebas", "openai_clave": "clave de OpenAI", "env_permisos": "permisos del .env",
    "vps": "servidor", "trabajadores": "trabajadores", "correo": "correo técnico", "config": "configuración",
}
ORDEN = {"rojo": 0, "ambar": 1, "error": 2, "na": 3, "verde": 4}
ICONO = {"verde": "✅", "ambar": "⚠️", "rojo": "❌", "na": "–", "error": "❓"}
PATRON_CUOTA = re.compile(r"insufficient_quota|exceeded your current quota|rate limit|\b429\b", re.I)


# --- modelo ---------------------------------------------------------------------------------

@dataclass
class Resultado:
    check: str
    ambito: str  # nombre del tenant o «global»
    estado: str  # verde | ambar | rojo | na | error
    valor: str = ""  # cifra o texto corto para voz y tabla (sin secretos, sin ids)
    detalle: str = ""  # una línea para el informe
    ms: int = 0

    def humano(self) -> str:
        return f"{NOMBRE_CHECK.get(self.check, self.check)}: {self.valor or self.detalle or self.estado}"


@dataclass
class Tenant:
    nombre: str
    voz: str
    carpeta: Path
    cfg: dict
    env: dict = field(default_factory=dict)
    obs: dict = field(default_factory=dict)
    envs: list = field(default_factory=list)  # rutas de .env leídas

    def __getitem__(self, clave: str) -> str:
        return (self.env.get(clave) or "").strip()

    @property
    def n8n(self) -> str:
        return self["N8N_BASE_URL"].rstrip("/")

    @property
    def host_vps(self) -> str:
        return self.obs.get("ssh_host") or self["SSH_HOST"]

    def workflow_principal(self) -> str:
        return (self.obs.get("workflow_ids") or {}).get("prod") or self.obs.get("main_workflow_id") or ""

    def workflows_extra(self) -> dict[str, str]:
        salida = {}
        for nombre, wid in (self.cfg.get("workflows_extra") or {}).items():
            if isinstance(wid, str) and wid.startswith("$"):
                wid = self[wid[1:]]
            if wid:
                salida[nombre] = wid
        return salida


@dataclass
class Resp:
    status: int = 0
    cuerpo: bytes = b""
    cabeceras: dict = field(default_factory=dict)
    ms: int = 0
    error: str = ""

    def json(self):
        try:
            return json.loads(self.cuerpo.decode("utf-8", "replace"))
        except ValueError:
            return None


class Redactor:
    """Red de seguridad: ningún valor cargado de un .env llega a la salida."""

    def __init__(self) -> None:
        self.valores: set[str] = set()

    def aprender(self, env: dict) -> None:
        for clave, valor in env.items():
            if len(valor) >= 12 and not re.search(r"(_URL|_HOST|_ID|_E164)$", clave) and not clave.startswith("N8N_STAGING_TOOL"):
                self.valores.add(valor)

    def limpiar(self, texto: str) -> str:
        for v in sorted(self.valores, key=len, reverse=True):
            texto = texto.replace(v, "***")
        return texto


REDACTOR = Redactor()


# --- configuración y credenciales -----------------------------------------------------------

def cargar_config() -> dict:
    cfg = json.loads(json.dumps(CONFIG_DEFECTO))
    try:
        usuario = json.loads(CONFIG_PARTE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return cfg
    except (OSError, ValueError) as e:
        raise SystemExit(f"parte.json inválido: {e}")
    for k, v in usuario.items():
        if k == "tenants" and isinstance(v, dict):
            for t, tv in v.items():
                if tv is None:
                    cfg["tenants"].pop(t, None)
                else:
                    cfg["tenants"].setdefault(t, {}).update(tv)
        elif isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def leer_env(ruta: Path) -> dict[str, str]:
    """KEY=VALUE con comentarios, `export`, comillas y líneas vacías. Nunca imprime nada."""
    env: dict[str, str] = {}
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        if linea.startswith("export "):
            linea = linea[7:].lstrip()
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip()
        if valor[:1] in ("'", '"') and valor[-1:] == valor[:1] and len(valor) >= 2:
            valor = valor[1:-1]
        elif " #" in valor:
            valor = valor.split(" #", 1)[0].rstrip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", clave):
            env[clave] = valor
    return env


def permisos_laxos(ruta: Path) -> bool:
    return bool(ruta.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))


def cargar_secretos_parte() -> dict[str, str]:
    """~/.config/narrador/parte.env: solo si existe y tiene permisos 600."""
    if not SECRETOS_PARTE.exists():
        return {}
    if permisos_laxos(SECRETOS_PARTE):
        return {"_error": "parte.env tiene permisos laxos (debe ser 600); no se usa"}
    env = leer_env(SECRETOS_PARTE)
    REDACTOR.aprender(env)
    return env


def cargar_tenant(nombre: str, cfg: dict) -> tuple[Tenant | None, list[Resultado]]:
    tcfg = cfg["tenants"][nombre]
    carpeta = Path(os.path.expanduser(tcfg.get("carpeta") or Path(cfg["raiz_tenants"]).expanduser() / nombre))
    t = Tenant(nombre=nombre, voz=tcfg.get("voz", nombre), carpeta=carpeta, cfg=tcfg)
    res: list[Resultado] = []
    rutas = [carpeta / tcfg.get("env", cfg["env"])] + [carpeta / r for r in tcfg.get("env_extra", [])]
    for ruta in rutas:
        try:
            env = leer_env(ruta)
        except FileNotFoundError:
            if ruta == rutas[0]:
                res.append(Resultado("config", nombre, "na", "sin .env", f"no existe {ruta.name} en la carpeta del tenant"))
                return None, res
            continue
        except OSError as e:
            res.append(Resultado("config", nombre, "error", "no se pudo leer el .env", str(e)))
            return None, res
        REDACTOR.aprender(env)
        for k, v in env.items():
            t.env.setdefault(k, v)
        t.envs.append(ruta)
        if permisos_laxos(ruta):
            res.append(Resultado("env_permisos", nombre, "ambar", f"{ruta.name} con permisos laxos ({oct(ruta.stat().st_mode & 0o777)[2:]})",
                                 f"{ruta.name} debería tener permisos 600 (chmod 600)"))
    try:
        t.obs = json.loads((carpeta / tcfg.get("config", cfg["config"])).read_text(encoding="utf-8")).get("observability") or {}
    except (OSError, ValueError):
        res.append(Resultado("config", nombre, "ambar", "sin tenant_config", "no se pudo leer tenant_config.json; sin ids de workflow"))
    return t, res


# --- red: ÚNICO punto de salida ---------------------------------------------------------------

def peticion(url: str, cabeceras: dict | None = None, timeout: float = 6, metodo: str = "GET", max_bytes: int = 3_000_000) -> Resp:
    assert metodo in ("GET", "HEAD"), "el parte es solo lectura"
    req = urllib.request.Request(url, headers=cabeceras or {}, method=metodo)
    req.add_header("User-Agent", "io-parte-matinal/1 (solo lectura)")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cuerpo = r.read(max_bytes)
            return Resp(r.status, cuerpo, {k.lower(): v for k, v in r.headers.items()}, int((time.monotonic() - t0) * 1000))
    except urllib.error.HTTPError as e:
        try:
            cuerpo = e.read(4000)
        except Exception:
            cuerpo = b""
        return Resp(e.code, cuerpo, {k.lower(): v for k, v in e.headers.items()} if e.headers else {},
                    int((time.monotonic() - t0) * 1000), f"HTTP {e.code}")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, ConnectionError, OSError) as e:
        motivo = getattr(e, "reason", None) or e
        return Resp(0, b"", {}, int((time.monotonic() - t0) * 1000), f"{type(e).__name__}: {str(motivo)[:80]}")


def tls_dias(host: str, puerto: int = 443, timeout: float = 6) -> int | str:
    """Días que quedan al certificado, o un texto de error."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, puerto), timeout=timeout) as s, ctx.wrap_socket(s, server_hostname=host) as ss:
            cert = ss.getpeercert()
    except (OSError, ssl.SSLError) as e:
        return f"{type(e).__name__}: {str(e)[:80]}"
    try:
        vence = ssl.cert_time_to_seconds(cert["notAfter"])
    except (KeyError, ValueError):
        return "certificado sin fecha"
    return int((vence - time.time()) // 86400)


def ssh_lectura(host: str, orden: str, timeout: float = 15) -> tuple[int, str]:
    if not shutil.which("ssh"):
        return 127, "ssh no instalado"
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new",
                            host, orden], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    return r.returncode, (r.stdout or r.stderr)[:4000]


def latencia(ms: int, umbral: int) -> str:
    return "verde" if ms < umbral else "ambar"


# --- chequeos: cada uno devuelve una lista y nunca lanza ----------------------------------------

def chk_n8n(t: Tenant, cfg: dict) -> list[Resultado]:
    """healthz, workflow principal activo (+ extras), errores y silencio en las ejecuciones."""
    u = cfg["umbrales"]
    if not t.n8n:
        return [Resultado("n8n", t.nombre, "na", "sin URL", "falta N8N_BASE_URL")]
    r = peticion(f"{t.n8n}/healthz")
    if r.status != 200:
        return [Resultado("n8n", t.nombre, "rojo", "no responde", f"healthz: {r.error or r.status} ({r.ms} ms)", r.ms)]
    res = [Resultado("n8n", t.nombre, latencia(r.ms, u["latencia_ms"]), f"{r.ms} ms", f"healthz OK en {r.ms} ms", r.ms)]
    clave = t["N8N_API_KEY"]
    if not clave:
        return res + [Resultado("wf_activo", t.nombre, "na", "sin clave", "falta N8N_API_KEY")]
    cab = {"X-N8N-API-KEY": clave, "Accept": "application/json"}
    principal = t.workflow_principal()
    flujos = ([("principal", principal)] if principal else []) + list(t.workflows_extra().items())
    if not principal:
        res.append(Resultado("wf_activo", t.nombre, "na", "sin id", "no hay main_workflow_id en tenant_config"))
    inactivos, sin_permiso = [], False
    for nombre, wid in flujos:
        rw = peticion(f"{t.n8n}/api/v1/workflows/{urllib.parse.quote(wid)}", cab, timeout=8)
        if rw.status in (401, 403):
            sin_permiso = True
            break
        datos = rw.json() if rw.status == 200 else None
        if rw.status == 404 or not isinstance(datos, dict):
            inactivos.append((nombre, "no existe" if rw.status == 404 else f"error {rw.error or rw.status}"))
        elif not datos.get("active"):
            inactivos.append((nombre, "inactivo"))
    if sin_permiso:
        res.append(Resultado("wf_activo", t.nombre, "ambar", "clave sin permiso", "la API de n8n rechaza la clave (401/403); revisar N8N_API_KEY"))
        return res
    if principal:
        grave = [n for n, _ in inactivos if n == "principal"]
        if grave:
            res.append(Resultado("wf_activo", t.nombre, "rojo", "workflow principal " + dict(inactivos)["principal"],
                                 "el workflow de producción no está activo o no existe"))
        elif inactivos:
            res.append(Resultado("wf_activo", t.nombre, "ambar", "secundario " + ", ".join(f"{n} {e}" for n, e in inactivos),
                                 "workflow secundario inactivo: " + ", ".join(n for n, _ in inactivos)))
        else:
            res.append(Resultado("wf_activo", t.nombre, "verde", "activo", f"{len(flujos)} workflow(s) activos"))
        res.append(chk_ejecuciones(t, cfg, cab, principal))
    return res


def _fecha_iso(texto: str) -> datetime | None:
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def umbral_silencio(cfg: dict, ahora: datetime | None = None) -> int:
    ahora = ahora or datetime.now()
    s = cfg["silencio_horas"]
    return int(s["finde"] if ahora.weekday() in (5, 6, 0) else s["laborable"])


def chk_ejecuciones(t: Tenant, cfg: dict, cab: dict, wid: str) -> Resultado:
    u = cfg["umbrales"]
    base = f"{t.n8n}/api/v1/executions?workflowId={urllib.parse.quote(wid)}"
    re_err = peticion(f"{base}&status=error&limit=20", cab, timeout=8)
    re_ult = peticion(f"{base}&limit=1", cab, timeout=8)
    if re_err.status != 200 or re_ult.status != 200:
        return Resultado("ejecuciones", t.nombre, "error", "no consultadas", f"API de ejecuciones: {re_err.error or re_ult.error or 'respuesta rara'}")
    ahora = datetime.now(timezone.utc)
    errores = [e for e in (re_err.json() or {}).get("data", []) if (_fecha_iso(e.get("startedAt") or "") or ahora - timedelta(days=9)) > ahora - timedelta(hours=24)]
    ultimas = (re_ult.json() or {}).get("data", [])
    silencio_h = None
    if ultimas and _fecha_iso(ultimas[0].get("startedAt") or ""):
        silencio_h = (ahora - _fecha_iso(ultimas[0]["startedAt"])).total_seconds() / 3600
    cuota = False
    if errores:
        rd = peticion(f"{t.n8n}/api/v1/executions/{errores[0]['id']}?includeData=true", cab, timeout=10)
        cuota = rd.status == 200 and bool(PATRON_CUOTA.search(rd.cuerpo.decode("utf-8", "replace")))
    limite = umbral_silencio(cfg)
    partes, estado = [], "verde"
    if cuota:
        estado = "rojo"
        partes.append("errores de cuota de OpenAI")
    if len(errores) >= u["errores_rojo"]:
        estado = "rojo"
    elif len(errores) >= u["errores_ambar"]:
        estado = max(estado, "ambar", key=lambda s: -ORDEN[s])
    partes.append(f"{len(errores)} error(es) en 24 h" if errores else "sin errores en 24 h")
    if silencio_h is None:
        partes.append("sin ejecuciones registradas")
        estado = max(estado, "ambar", key=lambda s: -ORDEN[s])
    elif silencio_h > limite:
        partes.append(f"última ejecución hace {silencio_h:.0f} h")
        estado = max(estado, "ambar", key=lambda s: -ORDEN[s])
    else:
        partes.append(f"última hace {silencio_h:.1f} h")
    detalle = "; ".join(partes) + f" (umbral de silencio {limite} h; un «success» con onError=continue puede ocultar fallos)"
    return Resultado("ejecuciones", t.nombre, estado, "; ".join(partes[:2]), detalle)


def chk_chatwoot(t: Tenant, cfg: dict) -> list[Resultado]:
    if t.cfg.get("chatwoot") is False:
        return []
    url, clave = t["CW_URL"].rstrip("/"), t["CW_API_KEY_ADMIN"]
    if not url or not clave:
        return [Resultado("chatwoot", t.nombre, "na", "sin credencial", "faltan CW_URL o CW_API_KEY_ADMIN")]
    cab = {"api_access_token": clave, "Accept": "application/json"}
    r = peticion(f"{url}/api/v1/profile", cab)
    if r.status != 200:
        estado = "ambar" if r.status in (401, 403) else "rojo"
        return [Resultado("chatwoot", t.nombre, estado, "sin permiso" if estado == "ambar" else "no responde",
                          f"profile: {r.error or r.status} ({r.ms} ms)", r.ms)]
    cuenta = t.cfg.get("cw_account", cfg["cw_account"])
    rc = peticion(f"{url}/api/v1/accounts/{cuenta}/conversations?status=open&assignee_type=unassigned", cab, timeout=8)
    datos = (rc.json() or {}).get("data") if rc.status == 200 else None
    if not isinstance(datos, dict):
        return [Resultado("chatwoot", t.nombre, "ambar", "conversaciones no consultadas", f"profile OK; conversaciones: {rc.error or rc.status}", r.ms)]
    ahora = time.time()
    viejas = [c for c in datos.get("payload", []) if ahora - float(c.get("last_activity_at") or c.get("created_at") or ahora) > cfg["umbrales"]["cw_sin_asignar_h"] * 3600]
    total = (datos.get("meta") or {}).get("unassigned_count", len(datos.get("payload", [])))
    if viejas:
        return [Resultado("chatwoot", t.nombre, "ambar", f"{len(viejas)} sin asignar más de {cfg['umbrales']['cw_sin_asignar_h']} h",
                          f"{total} conversaciones abiertas sin asignar, {len(viejas)} con más de {cfg['umbrales']['cw_sin_asignar_h']} h sin actividad", r.ms)]
    return [Resultado("chatwoot", t.nombre, latencia(r.ms, cfg["umbrales"]["latencia_ms"]), f"{r.ms} ms; {total} sin asignar",
                      f"profile OK en {r.ms} ms; {total} abiertas sin asignar", r.ms)]


def chk_supabase(t: Tenant, cfg: dict) -> list[Resultado]:
    url, clave = t["SUPABASE_URL"].rstrip("/"), t["SUPABASE_SERVICE_ROLE_KEY"]
    if not url or not clave:
        return [Resultado("supabase", t.nombre, "na", "sin credencial", "faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")]
    cab = {"apikey": clave, "Authorization": f"Bearer {clave}", "Prefer": "count=exact", "Range": "0-0"}
    res = []
    for tabla in t.cfg.get("supabase_tablas") or []:
        r = peticion(f"{url}/rest/v1/{urllib.parse.quote(tabla)}?select=*&limit=1", cab)
        if r.status not in (200, 206):
            res.append(Resultado("supabase", t.nombre, "rojo", f"{tabla} no responde", f"tabla {tabla}: {r.error or r.status} ({r.ms} ms)", r.ms))
            continue
        m = re.search(r"/(\d+|\*)$", r.cabeceras.get("content-range", ""))
        filas = int(m.group(1)) if m and m.group(1).isdigit() else None
        if filas == 0:
            res.append(Resultado("supabase", t.nombre, "ambar", f"{tabla} vacía", f"tabla {tabla} responde pero tiene 0 filas", r.ms))
        else:
            res.append(Resultado("supabase", t.nombre, latencia(r.ms, cfg["umbrales"]["latencia_ms"]), f"{r.ms} ms",
                                 f"tabla {tabla}: {filas if filas is not None else '?'} filas en {r.ms} ms", r.ms))
    return res or [Resultado("supabase", t.nombre, "na", "sin tablas", "no hay supabase_tablas en la configuración")]


def chk_meta(t: Tenant, cfg: dict) -> list[Resultado]:
    if t.cfg.get("meta") is False:
        return []
    token, numero = t["WA_GRAPH_TOKEN"], t["WA_PHONE_NUMBER_ID"]
    if not token or not numero:
        return [Resultado("meta_numero", t.nombre, "na", "sin credencial", "faltan WA_GRAPH_TOKEN o WA_PHONE_NUMBER_ID")]
    cab = {"Authorization": f"Bearer {token}"}
    r = peticion(f"https://graph.facebook.com/v21.0/{urllib.parse.quote(numero)}?fields=status,quality_rating", cab, timeout=8)
    d = r.json() if r.status == 200 else None
    res = []
    if not isinstance(d, dict):
        err = ((r.json() or {}).get("error") or {}) if r.cuerpo else {}
        if err.get("code") == 190 or r.status == 401:
            res.append(Resultado("meta_numero", t.nombre, "rojo", "token inválido", "Meta rechaza el token (error 190)", r.ms))
        else:
            res.append(Resultado("meta_numero", t.nombre, "error", "no consultado", f"Graph: {r.error or r.status}", r.ms))
    else:
        estado_n, calidad = str(d.get("status", "?")), str(d.get("quality_rating", "?"))
        if estado_n not in ("CONNECTED",) or calidad in ("RED",):
            est = "rojo"
        elif calidad == "YELLOW":
            est = "ambar"
        else:
            est = "verde"
        res.append(Resultado("meta_numero", t.nombre, est, f"{estado_n.lower()}, calidad {calidad.lower()}",
                             f"número {estado_n}, calidad {calidad}", r.ms))
    rd = peticion(f"https://graph.facebook.com/debug_token?{urllib.parse.urlencode({'input_token': token, 'access_token': token})}", timeout=8)
    dd = ((rd.json() or {}).get("data") or {}) if rd.status == 200 else {}
    if not dd:
        res.append(Resultado("meta_token", t.nombre, "na", "caducidad no consultada", f"debug_token: {rd.error or rd.status}"))
        return res
    if dd.get("is_valid") is False:
        res.append(Resultado("meta_token", t.nombre, "rojo", "token no válido", "debug_token dice is_valid=false"))
        return res
    expira = int(dd.get("expires_at") or 0)
    if expira == 0:
        res.append(Resultado("meta_token", t.nombre, "verde", "permanente", "token sin caducidad"))
    else:
        dias = int((expira - time.time()) // 86400)
        u = cfg["umbrales"]
        est = "rojo" if dias < u["meta_token_rojo_d"] else "ambar" if dias < u["meta_token_ambar_d"] else "verde"
        res.append(Resultado("meta_token", t.nombre, est, f"caduca en {dias} días", f"token caduca en {dias} días"))
    return res


def hosts_tls(t: Tenant) -> list[str]:
    hosts = []
    for url in (t["N8N_BASE_URL"], t["CW_URL"] if t.cfg.get("chatwoot") is not False else "", t.cfg.get("tester") or t.obs.get("chat_tester_url") or ""):
        h = urllib.parse.urlparse(url).hostname if url else None
        if h and h not in hosts:
            hosts.append(h)
    return hosts


def chk_tls(host: str, ambito: str, cfg: dict) -> Resultado:
    d = tls_dias(host)
    if isinstance(d, str):
        return Resultado("tls", ambito, "rojo", f"{host.split('.')[0]}: error TLS", f"{host}: {d}")
    u = cfg["umbrales"]
    est = "rojo" if d < u["tls_rojo"] else "ambar" if d < u["tls_ambar"] else "verde"
    return Resultado("tls", ambito, est, f"{host.split('.')[0]} vence en {d} días", f"{host}: vence en {d} días")


def chk_tester(t: Tenant, cfg: dict) -> list[Resultado]:
    url = (t.cfg.get("tester") or t.obs.get("chat_tester_url") or "").rstrip("/")
    if not url:
        return []
    r = peticion(f"{url}/login", timeout=8)
    if r.status != 200:
        return [Resultado("tester", t.nombre, "rojo", "no responde", f"{url.split('//')[-1]}/login: {r.error or r.status}", r.ms)]
    return [Resultado("tester", t.nombre, latencia(r.ms, cfg["umbrales"]["latencia_ms"]), f"{r.ms} ms", f"login OK en {r.ms} ms", r.ms)]


def chk_openai(t: Tenant, cfg: dict) -> list[Resultado]:
    clave = t["OPENAI_API_KEY"]
    if not clave:
        return []
    r = peticion("https://api.openai.com/v1/models", {"Authorization": f"Bearer {clave}"}, timeout=8)
    nota = "clave local del tenant (scripts y juez); la de los bots vive dentro de n8n"
    if r.status == 200:
        return [Resultado("openai_clave", t.nombre, "verde", "clave válida", f"clave válida; {nota}", r.ms)]
    if r.status == 401:
        return [Resultado("openai_clave", t.nombre, "rojo", "clave rechazada", f"OpenAI responde 401; {nota}", r.ms)]
    if r.status == 429:
        return [Resultado("openai_clave", t.nombre, "rojo", "sin cuota", f"OpenAI responde 429 (cuota o límite); {nota}", r.ms)]
    return [Resultado("openai_clave", t.nombre, "error", "no consultada", f"OpenAI: {r.error or r.status}", r.ms)]


def chk_vps(host: str, contenedores: list[str], cfg: dict) -> Resultado:
    u = cfg["umbrales"]
    rc, salida = ssh_lectura(host, "uptime; df -P / | tail -1; free -m | sed -n 2p; docker ps --format '{{.Names}} {{.Status}}'")
    nombre = host.split("@")[-1]
    if rc != 0:
        return Resultado("vps", nombre, "error", "sin acceso", f"ssh {nombre}: {salida.strip()[:120] or rc}")
    lineas = salida.strip().splitlines()
    problemas, estado = [], "verde"
    try:
        disco = int(lineas[1].split()[4].rstrip("%"))
        if disco >= u["disco_rojo"]:
            estado, problemas = "rojo", problemas + [f"disco al {disco} %"]
        elif disco >= u["disco_ambar"]:
            estado, problemas = "ambar", problemas + [f"disco al {disco} %"]
        mem = lineas[2].split()
        libre_pct = int(mem[6]) * 100 // max(1, int(mem[1]))
        if libre_pct < u["ram_libre_min"]:
            estado = max(estado, "ambar", key=lambda s: -ORDEN[s])
            problemas.append(f"memoria disponible {libre_pct} %")
    except (IndexError, ValueError):
        return Resultado("vps", nombre, "error", "salida inesperada", f"no entiendo la salida de {nombre}")
    vivos = {l.split()[0]: " ".join(l.split()[1:]) for l in lineas[3:] if l.strip()}
    for c in contenedores:
        est = vivos.get(c)
        if est is None or not est.startswith("Up"):
            estado = "rojo"
            problemas.append(f"contenedor {c} {est or 'ausente'}")
        elif "Restarting" in est or "unhealthy" in est:
            estado = max(estado, "ambar", key=lambda s: -ORDEN[s])
            problemas.append(f"contenedor {c} {est}")
    carga = lineas[0].split("load average:")[-1].strip() if "load average" in lineas[0] else ""
    return Resultado("vps", nombre, estado, "; ".join(problemas) or f"disco {disco} %, memoria libre {libre_pct} %",
                     f"disco {disco} %, memoria disponible {libre_pct} %, carga {carga}, {len(vivos)} contenedores" + ("; " + "; ".join(problemas) if problemas else ""))


def chk_trabajadores(desde: float) -> tuple[list[Resultado], list[dict]]:
    """Trabajadores con informe nuevo desde el último parte y los parados sin resultado."""
    try:
        lista = json.loads(TRABAJADORES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    nuevos, parados = [], []
    for t in lista[-20:]:
        informe = RUNTIME / "trabajadores" / f"{t.get('nombre')}.md"
        try:
            if informe.stat().st_mtime > desde:
                primera = " ".join(informe.read_text(encoding="utf-8").split())[:160]
                nuevos.append({"nombre": t.get("nombre"), "resumen": primera})
                continue
        except OSError:
            pass
        if t.get("tipo") != "bg" and t.get("inicio", 0) > desde and not informe.exists():
            try:
                os.kill(int(t.get("pid", 0)), 0)
            except (OSError, ValueError):
                parados.append(t.get("nombre"))
    res = []
    if nuevos:
        res.append(Resultado("trabajadores", "global", "verde", f"{len(nuevos)} informe(s) nuevo(s)", "informes: " + ", ".join(n["nombre"] for n in nuevos)))
    if parados:
        res.append(Resultado("trabajadores", "global", "ambar", f"{len(parados)} parado(s) sin resultado", "sin informe: " + ", ".join(parados)))
    return res, nuevos


def chk_correo(secretos: dict, cfg: dict) -> tuple[list[Resultado], list[dict]]:
    """IMAP de solo lectura: cabeceras de las últimas 24 h, nunca marca como leído ni descarga cuerpos."""
    usuario, clave = secretos.get("TECH_IMAP_USER"), secretos.get("TECH_IMAP_PASS")
    host = secretos.get("TECH_IMAP_HOST", "imap.gmail.com")
    if not usuario or not clave:
        return [Resultado("correo", "global", "na", "sin credencial", "faltan TECH_IMAP_USER/TECH_IMAP_PASS en parte.env")], []
    try:
        m = imaplib.IMAP4_SSL(host, timeout=10)
        m.login(usuario, clave)
        m.select("INBOX", readonly=True)
        desde = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
        ok, ids = m.search(None, f"(SINCE {desde})")
        uids = ids[0].split()[-15:] if ok == "OK" else []
        correos = []
        for uid in reversed(uids):
            ok, datos = m.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if ok != "OK" or not datos or not isinstance(datos[0], tuple):
                continue
            msg = email.message_from_bytes(datos[0][1])
            correos.append({"de": _decodificar(msg.get("From", "")), "asunto": _decodificar(msg.get("Subject", ""))[:120],
                            "fecha": msg.get("Date", "")[:31]})
        m.logout()
    except (imaplib.IMAP4.error, OSError, socket.timeout) as e:
        return [Resultado("correo", "global", "error", "no leído", f"IMAP: {type(e).__name__}: {str(e)[:80]}")], []
    return [Resultado("correo", "global", "verde", f"{len(correos)} en 24 h", f"{len(correos)} correos en las últimas 24 h")], correos


def _decodificar(texto: str) -> str:
    try:
        return str(email.header.make_header(email.header.decode_header(texto)))
    except Exception:
        return texto


# --- pendientes -------------------------------------------------------------------------------

PATRON_SECCION = re.compile(r"pendiente|bloquea", re.I)
PATRON_CERRADO = re.compile(r"✅|RESUELTO|\bHECHO\b|CERRAD|DONE", re.I)
PATRON_SENAL = re.compile(r"⛔|🔴|⏳|🟡|\[ \]|TODO|pendiente|bloquea|falta", re.I)


def extraer_pendientes(texto: str, nombre_archivo: str, max_lineas: int = 120, max_items: int = 10) -> list[str]:
    """Ítems abiertos de un archivo de un tenant, sin leerlo entero en Ío.

    CLAUDE.md: todas las secciones cuyo encabezado dice «pendiente» o «bloquea» (y no está cerrado), hasta el
    siguiente encabezado de igual o mayor nivel. Dentro se ignoran las citas (`>`: bitácoras), los bloques de
    código, las subsecciones cerradas (✅, Hecho, Resuelto) y los ítems marcados como hechos; se toman los ítems
    de lista o numerados y las filas de tabla con señal (🔴 ⏳ 🟡 ⛔). Primero los que llevan señal de abierto.
    Otros .md: solo `[ ]` y encabezados con ⛔/🔴. .txt: líneas no vacías."""
    lineas = texto.splitlines()
    if nombre_archivo.endswith(".txt"):
        return [l.strip()[:100] for l in lineas if l.strip()][:max_items]
    if nombre_archivo != "CLAUDE.md":
        return [l.strip()[:100] for l in lineas if "[ ]" in l or re.search(r"^#{1,4} .*(⛔|🔴)", l)][:max_items]
    con_senal, sin_senal, vistos = [], [], set()
    i = 0
    while i < len(lineas):
        m = re.match(r"^(#{1,4})\s+(.*)", lineas[i])
        if not (m and PATRON_SECCION.search(m.group(2)) and not PATRON_CERRADO.search(m.group(2))):
            i += 1
            continue
        nivel, i = len(m.group(1)), i + 1
        omitir = en_codigo = False
        leidas = 0
        while i < len(lineas) and leidas < max_lineas:
            l = lineas[i]
            i += 1
            leidas += 1
            sub = re.match(r"^(#{1,4})\s+(.*)", l)
            if sub and len(sub.group(1)) <= nivel:
                i -= 1
                break
            if sub:
                omitir = bool(PATRON_CERRADO.search(sub.group(2)))
                continue
            if l.strip().startswith("```"):
                en_codigo = not en_codigo
                continue
            s_ = l.strip()
            if omitir or en_codigo or not s_ or s_.startswith(">"):
                continue
            es_lista = re.match(r"^(?:[-*•]|\d+[.)])\s+", s_)
            es_fila = s_.startswith("|") and bool(re.search(r"🔴|⏳|🟡|⛔", s_)) and "---" not in s_
            if not (es_lista or es_fila) or PATRON_CERRADO.search(s_):
                continue
            s_ = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", s_)
            s_ = re.sub(r"\s*\|\s*", " · ", s_).strip(" ·")
            s_ = re.sub(r"\*\*|`", "", s_)
            s_ = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s_)[:100]
            if s_ in vistos:
                continue
            vistos.add(s_)
            (con_senal if PATRON_SENAL.search(s_) else sin_senal).append(s_)
    return (con_senal + sin_senal)[:max_items]


def chk_pendientes(tenants: list[Tenant], hoy: date) -> list[dict]:
    try:
        cache = json.loads(CACHE_PENDIENTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    vistos, salida = {}, []
    for t in tenants:
        for rel in t.cfg.get("pendientes") or []:
            ruta = t.carpeta / rel
            try:
                items = extraer_pendientes(ruta.read_text(encoding="utf-8", errors="replace"), ruta.name)
            except OSError:
                continue
            for texto in items:
                clave = hashlib.sha1(f"{t.nombre}|{re.sub(r'\W+', ' ', texto.lower()).strip()}".encode()).hexdigest()[:16]
                primera = cache.get(clave, {}).get("primera_vez") or hoy.isoformat()
                vistos[clave] = {"primera_vez": primera, "tenant": t.nombre, "texto": texto}
                try:
                    dias = (hoy - date.fromisoformat(primera)).days
                except ValueError:
                    dias = 0
                salida.append({"tenant": t.voz, "texto": texto, "dias": dias, "archivo": rel, "senal": bool(PATRON_SENAL.search(texto))})
    try:
        PARTES.mkdir(parents=True, exist_ok=True)
        _escribir_atomico(CACHE_PENDIENTES, json.dumps(vistos, ensure_ascii=False, indent=0))
    except OSError:
        pass
    salida.sort(key=lambda p: (-p["dias"], not p["senal"]))  # más arrastrados primero; a igual arrastre, los que llevan señal de abierto
    return salida


# --- marcador y día operativo ----------------------------------------------------------------

def chk_memoria() -> str | None:
    """La línea de la memoria de Ío: solo lee la última revisión semanal (`narrador memoria revisar --json`)."""
    try:
        d = json.loads(REVISION_MEMORIA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fecha = str(d.get("fecha") or "")[:10]
    return f"{d.get('resumen') or 'memoria: revisión sin resumen'}" + (f" (revisión del {fecha})" if fecha else "")


def _escribir_atomico(ruta: Path, texto: str) -> None:
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(ruta)


def fecha_operativa(ahora: datetime | None = None, hora_corte: int = 5) -> date:
    return ((ahora or datetime.now()) - timedelta(hours=hora_corte)).date()


def leer_marcador() -> dict:
    try:
        d = json.loads(MARCADOR.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_marcador(d: dict) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    _escribir_atomico(MARCADOR, json.dumps(d, ensure_ascii=False, indent=1))


def toca_parte(ahora: datetime | None = None, marcador: dict | None = None, hora_corte: int = 5) -> str:
    ahora = ahora or datetime.now()
    m = leer_marcador() if marcador is None else marcador
    if not m or m.get("fecha") != fecha_operativa(ahora, hora_corte).isoformat():
        return "nuevo"
    estado = m.get("estado")
    if estado == "en_curso":
        return "nuevo" if ahora.timestamp() - float(m.get("inicio_ts") or 0) > TTL_EN_CURSO_MIN * 60 else "en_curso"
    if estado != "hecho":
        return "nuevo"
    return "no" if m.get("entregado") else "pendiente_entrega"


def frase_arranque() -> str:
    """Punto (4) del mensaje de arranque de Ío, o «» si hoy ya se dio el parte. Nunca lanza."""
    try:
        cfg = cargar_config()
        que = toca_parte(hora_corte=int(cfg.get("hora_corte", 5)))
        m = leer_marcador()
        if que == "nuevo":
            return (" (4) Es tu primer arranque del día: tras saludar, da el parte matinal siguiendo la guía "
                    "`narrador guia parte-matinal` (lanza `narrador parte --json` en segundo plano y locútalo cuando termine).")
        if que == "pendiente_entrega":
            return (f" (4) El parte matinal de hoy ya está generado (a las {m.get('hora', '?')}) pero no se entregó: "
                    "léelo con `narrador parte --json` y locútalo siguiendo la guía `narrador guia parte-matinal`.")
        if que == "en_curso":
            return (" (4) Hay un parte matinal generándose ahora mismo: en un minuto ejecuta `narrador parte --json` "
                    "y locútalo siguiendo la guía `narrador guia parte-matinal`.")
        return ""
    except Exception:
        return ""


def sesion_io() -> str:
    try:
        return json.loads(IO_JSON.read_text(encoding="utf-8")).get("session_id") or ""
    except (OSError, ValueError):
        return ""


# --- orquestación -----------------------------------------------------------------------------

def peor(estados) -> str:
    return min(estados, key=lambda s: ORDEN.get(s, 9), default="verde")


def semaforo(resultados: list[Resultado]) -> str:
    estados = [r.estado for r in resultados if r.estado in ("rojo", "ambar", "verde")]
    return "rojo" if "rojo" in estados else "ambar" if "ambar" in estados else "verde"


def ejecutar(cfg: dict, solo: set[str], solo_tenant: str | None, secretos: dict, desde: float) -> dict:
    resultados: list[Resultado] = []
    tenants: list[Tenant] = []
    for nombre in cfg["tenants"]:
        if solo_tenant and nombre != solo_tenant:
            continue
        t, res = cargar_tenant(nombre, cfg)
        resultados += res
        if t:
            tenants.append(t)
    if "_error" in secretos:
        resultados.append(Resultado("config", "global", "ambar", "parte.env ignorado", secretos["_error"]))
    tareas: list[tuple[str, callable]] = []
    limites: dict[str, threading.Semaphore] = {}

    def con_limite(host: str, fn, *a):
        sem = limites.setdefault(host or "-", threading.Semaphore(2))
        with sem:
            return fn(*a)

    for t in tenants:
        if "tenants" in solo:
            tareas.append((f"n8n {t.nombre}", lambda t=t: con_limite(t.host_vps, chk_n8n, t, cfg)))
            tareas.append((f"chatwoot {t.nombre}", lambda t=t: con_limite(t.host_vps, chk_chatwoot, t, cfg)))
        if "supabase" in solo:
            tareas.append((f"supabase {t.nombre}", lambda t=t: chk_supabase(t, cfg)))
        if "meta" in solo:
            tareas.append((f"meta {t.nombre}", lambda t=t: chk_meta(t, cfg)))
        if "tester" in solo:
            tareas.append((f"tester {t.nombre}", lambda t=t: con_limite(t.host_vps, chk_tester, t, cfg)))
        if "openai" in solo:
            tareas.append((f"openai {t.nombre}", lambda t=t: chk_openai(t, cfg)))
        if "tls" in solo:
            for h in hosts_tls(t):
                tareas.append((f"tls {h}", lambda h=h, t=t: [chk_tls(h, t.nombre, cfg)]))
    if "vps" in solo and cfg.get("ssh"):
        por_host: dict[str, list[str]] = {}
        for t in tenants:
            if t.host_vps:
                por_host.setdefault(t.host_vps, []).append(t.obs.get("n8n_container") or "")
        for host, conts in por_host.items():
            tareas.append((f"vps {host}", lambda host=host, conts=conts: [chk_vps(host, [c for c in conts if c], cfg)]))
    elif "vps" in solo:
        resultados.append(Resultado("vps", "global", "na", "desactivado", "activa \"ssh\": true en parte.json para comprobar disco, memoria y contenedores"))
    correos: list[dict] = []
    if "correo" in solo and cfg.get("imap_tech"):
        tareas.append(("correo", lambda: chk_correo(secretos, cfg)))
    elif "correo" in solo:
        resultados.append(Resultado("correo", "global", "na", "por conector", "imap_tech=false: el correo de tech@ lo mira Ío con el conector de Gmail"))

    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        futuros = {pool.submit(fn): nombre for nombre, fn in tareas}
        try:
            for f in cf.as_completed(futuros, timeout=45):
                nombre = futuros[f]
                try:
                    salida = f.result()
                except Exception as e:  # ningún chequeo tumba el parte
                    resultados.append(Resultado(nombre.split()[0], nombre.split()[-1], "error", "fallo interno", f"{type(e).__name__}: {str(e)[:100]}"))
                    continue
                if isinstance(salida, tuple):
                    salida, correos = salida
                resultados += salida
        except cf.TimeoutError:
            for f, nombre in futuros.items():
                if not f.done():
                    resultados.append(Resultado(nombre.split()[0], nombre.split()[-1], "error", "tiempo agotado", "no respondió en 45 s"))
        pool.shutdown(wait=False, cancel_futures=True)

    pendientes = chk_pendientes(tenants, fecha_operativa(hora_corte=int(cfg["hora_corte"]))) if "pendientes" in solo else []
    trabajadores: list[dict] = []
    if "trabajadores" in solo:
        res_t, trabajadores = chk_trabajadores(desde)
        resultados += res_t
    resultados.sort(key=lambda r: (r.ambito, ORDEN.get(r.estado, 9), r.check))
    return {"resultados": resultados, "pendientes": pendientes, "trabajadores": trabajadores, "correos": correos,
            "tenants": {t.nombre: t.voz for t in tenants}}


# --- salida ---------------------------------------------------------------------------------

def anomalias_por_ambito(resultados: list[Resultado]) -> dict[str, list[Resultado]]:
    salida: dict[str, list[Resultado]] = {}
    for r in resultados:
        if r.estado != "verde":
            salida.setdefault(r.ambito, []).append(r)
    return salida


def resumen_voz(parte: dict, voces: dict[str, str]) -> str:
    """Una frase corta (≤ ~200 caracteres), sin ids, rutas ni URLs."""
    sem = parte["semaforo"]
    res: list[Resultado] = parte["resultados"]
    rojos = [r for r in res if r.estado == "rojo"]
    ambar = [r for r in res if r.estado == "ambar"]

    def describir(lista: list[Resultado]) -> str:
        vistos, piezas = set(), []
        for r in lista:
            clave = (r.ambito, r.check)
            if clave in vistos:
                continue
            vistos.add(clave)
            piezas.append(f"{voces.get(r.ambito, r.ambito)} {NOMBRE_CHECK.get(r.check, r.check)} {r.valor.split(';')[0]}".strip())
            if len(piezas) == 2:
                break
        return "; ".join(piezas) + (" y más" if len({(r.ambito, r.check) for r in lista}) > 2 else "")

    frase = f"Parte en {'ámbar' if sem == 'ambar' else sem}. "
    if rojos:
        frase += f"En rojo: {describir(rojos)}. "
    if ambar and len(frase) < 150:
        frase += f"En ámbar: {describir(ambar)}. "
    if not rojos and not ambar:
        frase += "Todos los servicios responden. "
    return frase.strip()[:220]


def repartir_pendientes(pendientes: list[dict], maximo: int) -> list[dict]:
    """Hasta `maximo` pendientes sin que un tenant acapare la lista: ronda por tenant respetando el orden."""
    colas: dict[str, list[dict]] = {}
    for p in pendientes:
        colas.setdefault(p["tenant"], []).append(p)
    salida: list[dict] = []
    while len(salida) < maximo and any(colas.values()):
        for cola in colas.values():
            if cola and len(salida) < maximo:
                salida.append(cola.pop(0))
    return salida


def a_json_compacto(parte: dict) -> dict:
    res: list[Resultado] = parte["resultados"]
    voces = parte["tenants"]
    por_ambito = anomalias_por_ambito(res)
    tenants = {}
    for nombre, voz in voces.items():
        propios = [r for r in res if r.ambito == nombre]
        tenants[voz] = {"semaforo": semaforo(propios),
                        "anomalias": [r.humano() for r in por_ambito.get(nombre, []) if r.estado in ("rojo", "ambar")],
                        "no_comprobado": [r.humano() for r in por_ambito.get(nombre, []) if r.estado in ("na", "error")]}
    globales = [r for r in res if r.ambito not in voces]
    contadores = {e: sum(1 for r in res if r.estado == e) for e in ("verde", "ambar", "rojo", "na", "error")}
    return {
        "fecha": parte["fecha"], "hora": parte["hora"], "semaforo": parte["semaforo"], "resumen_voz": parte["resumen_voz"],
        "tenants": tenants,
        "global": {"anomalias": [f"{r.ambito}: {r.humano()}" for r in globales if r.estado in ("rojo", "ambar")],
                   "no_comprobado": [f"{r.ambito}: {r.humano()}" for r in globales if r.estado in ("na", "error")]},
        "pendientes": repartir_pendientes(parte["pendientes"], 12),
        "trabajadores": parte["trabajadores"][:5],
        "memoria": parte.get("memoria"),
        "correo": parte["correos"][:10],
        "contadores": contadores,
        "informe_md": str(parte["ruta_md"]),
    }


def a_markdown(parte: dict) -> str:
    res: list[Resultado] = parte["resultados"]
    voces = parte["tenants"]
    L = [f"# Parte matinal — {parte['fecha']} {parte['hora']}", "", f"**Semáforo: {parte['semaforo'].upper()}** — {parte['resumen_voz']}", ""]
    columnas = ["n8n", "wf_activo", "ejecuciones", "chatwoot", "supabase", "meta_numero", "meta_token", "tls", "tester", "openai_clave"]
    L.append("| tenant | " + " | ".join(NOMBRE_CHECK[c] for c in columnas) + " |")
    L.append("|---|" + "---|" * len(columnas))
    for nombre, voz in voces.items():
        celdas = []
        for c in columnas:
            rs = [r for r in res if r.ambito == nombre and r.check == c]
            celdas.append(ICONO[peor([r.estado for r in rs])] if rs else "–")
        L.append(f"| {voz} | " + " | ".join(celdas) + " |")
    L += ["", "## Anomalías", ""]
    anom = [r for r in res if r.estado in ("rojo", "ambar")]
    L += [f"- {ICONO[r.estado]} **{voces.get(r.ambito, r.ambito)}** · {NOMBRE_CHECK.get(r.check, r.check)}: {r.detalle or r.valor}" for r in anom] or ["- ninguna"]
    vps = [r for r in res if r.check == "vps"]
    if vps:
        L += ["", "## Servidores", ""] + [f"- {ICONO[r.estado]} {r.ambito}: {r.detalle or r.valor}" for r in vps]
    L += ["", "## Pendientes (por días de arrastre)", ""]
    L += [f"- [{p['tenant']}] {p['texto']} — {p['dias']} día(s)" for p in parte["pendientes"]] or ["- nada extraído"]
    if parte["trabajadores"]:
        L += ["", "## Trabajadores con informe nuevo", ""] + [f"- {t['nombre']}: {t['resumen']}" for t in parte["trabajadores"]]
    if parte.get("memoria"):
        L += ["", "## Memoria de Ío", "", f"- {parte['memoria']}"]
    if parte["correos"]:
        L += ["", "## Correo técnico (últimas 24 h, solo cabeceras)", ""] + [f"- {c['fecha']} · {c['de']} · {c['asunto']}" for c in parte["correos"]]
    nc = [r for r in res if r.estado in ("na", "error")]
    if nc:
        L += ["", "## No comprobado", ""] + [f"- {voces.get(r.ambito, r.ambito)} · {NOMBRE_CHECK.get(r.check, r.check)}: {r.detalle or r.valor}" for r in nc]
    L += ["", "## Todo lo comprobado", ""]
    L += [f"- {ICONO[r.estado]} {voces.get(r.ambito, r.ambito)} · {NOMBRE_CHECK.get(r.check, r.check)}: {r.detalle or r.valor}" for r in res]
    L += ["", "## Advertencias de método", "",
          "- Un «success» de n8n con `onError: continue` puede ocultar fallos de nodos; las ejecuciones con error se cuentan por su estado.",
          "- La clave de OpenAI comprobada es la local del tenant (scripts, juez); la de los bots vive como credencial dentro de n8n. "
          "La señal real de cuota son los errores 429/insufficient_quota en las ejecuciones.",
          "- Festivos no se contemplan en el umbral de silencio; sábado, domingo y lunes usan el umbral de fin de semana.",
          "- Nunca se envía nada: solo GET/HEAD, lectura por SSH e IMAP en modo solo lectura. Webhooks de producción, QVET y la bandeja QA no se tocan."]
    return "\n".join(L) + "\n"


def podar_historial() -> None:
    try:
        limite = time.time() - DIAS_HISTORIAL * 86400
        for p in PARTES.glob("20??-??-??.*"):
            if p.stat().st_mtime < limite:
                p.unlink()
    except OSError:
        pass


def cargar_simulacion(ruta: Path) -> dict:
    d = json.loads(ruta.read_text(encoding="utf-8"))
    return {"resultados": [Resultado(**r) for r in d.get("resultados", [])], "pendientes": d.get("pendientes", []),
            "trabajadores": d.get("trabajadores", []), "correos": d.get("correos", []), "tenants": d.get("tenants", {})}


def generar(cfg: dict, solo: set[str], solo_tenant: str | None, simular: Path | None) -> dict:
    ahora = datetime.now()
    hoy = fecha_operativa(ahora, int(cfg["hora_corte"]))
    anterior = leer_marcador()
    desde = float(anterior.get("inicio_ts") or 0) if anterior.get("fecha") != hoy.isoformat() else float(anterior.get("desde_ts") or 0)
    desde = desde or ahora.timestamp() - 86400
    PARTES.mkdir(parents=True, exist_ok=True)
    parcial = bool(solo_tenant or solo != set(BLOQUES))
    if not parcial:
        guardar_marcador({"fecha": hoy.isoformat(), "hora": ahora.strftime("%H:%M"), "estado": "en_curso", "inicio_ts": ahora.timestamp(),
                          "desde_ts": desde, "session_id": sesion_io(), "pid": os.getpid(), "entregado": False})
    estado_final = "fallido"
    sufijo = "" if not parcial else "-parcial" + (f"-{solo_tenant}" if solo_tenant else "")
    try:
        secretos = cargar_secretos_parte()
        parte = cargar_simulacion(simular) if simular else ejecutar(cfg, solo, solo_tenant, secretos, desde)
        parte["fecha"], parte["hora"] = hoy.isoformat(), ahora.strftime("%H:%M")
        parte["semaforo"] = semaforo(parte["resultados"])
        parte["resumen_voz"] = resumen_voz(parte, parte["tenants"])
        parte["memoria"] = chk_memoria()
        parte["ruta_md"] = PARTES / f"{hoy.isoformat()}{sufijo}.md"
        parte["ruta_json"] = PARTES / f"{hoy.isoformat()}{sufijo}.json"
        md = REDACTOR.limpiar(a_markdown(parte))
        compacto = json.loads(REDACTOR.limpiar(json.dumps(a_json_compacto(parte), ensure_ascii=False)))
        completo = {"compacto": compacto, "resultados": [asdict(r) for r in parte["resultados"]], "pendientes": parte["pendientes"],
                    "trabajadores": parte["trabajadores"], "correos": parte["correos"], "tenants": parte["tenants"], "parcial": parcial}
        _escribir_atomico(parte["ruta_md"], md)
        _escribir_atomico(parte["ruta_json"], REDACTOR.limpiar(json.dumps(completo, ensure_ascii=False, indent=1)))
        estado_final = "hecho"
        parte["compacto"] = compacto
        if parte["semaforo"] == "rojo" and not simular and shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "Ío", "-u", "critical", "Parte matinal en rojo", parte["resumen_voz"]], check=False)
        podar_historial()
        return parte
    finally:
        if not parcial:
            guardar_marcador({"fecha": hoy.isoformat(), "hora": ahora.strftime("%H:%M"), "estado": estado_final, "inicio_ts": ahora.timestamp(),
                              "desde_ts": desde, "fin_ts": time.time(), "session_id": sesion_io(), "pid": os.getpid(), "entregado": False,
                              **({"semaforo": parte["semaforo"], "resumen_voz": parte["resumen_voz"], "archivo": str(parte["ruta_json"])} if estado_final == "hecho" else {})})


def cache_valida(cfg: dict) -> dict | None:
    m = leer_marcador()
    if m.get("estado") != "hecho" or m.get("fecha") != fecha_operativa(hora_corte=int(cfg["hora_corte"])).isoformat():
        return None
    if time.time() - float(m.get("fin_ts") or 0) > float(cfg["cache_horas"]) * 3600:
        return None
    try:
        return json.loads(Path(m["archivo"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        return None


def imprimir_resumen(compacto: dict) -> None:
    print(f"Parte {compacto['fecha']} {compacto['hora']} — {compacto['semaforo'].upper()}")
    print(compacto["resumen_voz"])
    for voz, t in compacto["tenants"].items():
        print(f"  {ICONO[t['semaforo']]} {voz}: " + ("; ".join(t["anomalias"]) or "todo bien") + (f" · sin comprobar: {'; '.join(t['no_comprobado'])}" if t["no_comprobado"] else ""))
    for a in compacto["global"]["anomalias"]:
        print(f"  ⚠️ {a}")
    if compacto["pendientes"]:
        print("  pendientes: " + " · ".join(f"[{p['tenant']}] {p['texto'][:60]} ({p['dias']} d)" for p in compacto["pendientes"][:5]))
    if compacto.get("memoria"):
        print(f"  {compacto['memoria']}")
    print(f"  informe: {compacto['informe_md']}")


def main(args: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="narrador parte", add_help=False)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--solo", default="")
    ap.add_argument("--tenant", default=None)
    ap.add_argument("--entregado", action="store_true")
    ap.add_argument("--simular", nargs="?", const=str(Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "parte_simulado.json"))
    ap.add_argument("--si-toca", dest="si_toca", action="store_true")
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    try:
        o = ap.parse_args(args)
    except SystemExit:
        return 3
    if o.help:
        print(__doc__.strip())
        return 0
    cfg = cargar_config()
    hora_corte = int(cfg["hora_corte"])
    if o.estado:
        print(toca_parte(hora_corte=hora_corte), json.dumps(leer_marcador(), ensure_ascii=False), repr(frase_arranque()), sep="\n")
        return 0
    if o.entregado:
        m = leer_marcador()
        if m.get("fecha") != fecha_operativa(hora_corte=hora_corte).isoformat() or m.get("estado") != "hecho":
            print("no hay parte de hoy que marcar")
            return 3
        m["entregado"], m["entregado_ts"] = True, time.time()
        guardar_marcador(m)
        print("parte marcado como entregado")
        return 0
    if o.si_toca and toca_parte(hora_corte=hora_corte) != "nuevo":
        return 0
    if o.md and not o.forzar:
        m = leer_marcador()
        try:
            print(Path(m["archivo"]).with_suffix(".md").read_text(encoding="utf-8"), end="")
            return 0
        except (KeyError, OSError):
            pass
    solo = set(BLOQUES)
    if o.solo:
        pedidos = {s.strip() for s in o.solo.split(",") if s.strip()}
        raros = pedidos - set(BLOQUES)
        if raros:
            print(f"bloques desconocidos: {', '.join(sorted(raros))}; hay: {', '.join(BLOQUES)}", file=sys.stderr)
            return 3
        solo = pedidos
    if o.tenant and o.tenant not in cfg["tenants"]:
        print(f"tenant desconocido: {o.tenant}; hay: {', '.join(cfg['tenants'])}", file=sys.stderr)
        return 3
    completo = None if (o.forzar or o.solo or o.tenant or o.simular) else cache_valida(cfg)
    if completo:
        compacto = completo["compacto"]
        compacto.setdefault("memoria", chk_memoria())  # partes de caché anteriores a la línea de memoria
    else:
        try:
            parte = generar(cfg, solo, o.tenant, Path(o.simular) if o.simular else None)
        except Exception as e:
            print(f"el parte falló: {type(e).__name__}: {REDACTOR.limpiar(str(e))[:200]}", file=sys.stderr)
            return 3
        compacto = parte["compacto"]
    if o.json:
        print(json.dumps(compacto, ensure_ascii=False, indent=1))
    elif o.md:
        print(Path(compacto["informe_md"]).read_text(encoding="utf-8"), end="")
    else:
        imprimir_resumen(compacto)
    return {"verde": 0, "ambar": 1, "rojo": 2}.get(compacto["semaforo"], 3)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
