"""Qué acciones de Ío necesitan tu confirmación por voz. Biblioteca pura, sin E/S.

Ío trabaja en el modo `auto` de Claude Code, que ya filtra lo peligroso. Aquí solo se
marcan las acciones que salen fuera en tu nombre: enviar correos, tocar el calendario y
subir cambios con `git push`. Todo lo demás es libre.
"""

import re
import shlex
import unicodedata
from dataclasses import dataclass

LIBRE, CONFIRMAR = "libre", "confirmar"


@dataclass(frozen=True)
class Veredicto:
    nivel: str = LIBRE
    alta: bool = False  # exige decir «confirmo»; no basta con «sí»
    resumen: str = ""  # lo que se pregunta en voz alta


CORREO = {"send_message": "enviar un correo", "reply": "responder un correo", "forward": "reenviar un correo"}
CALENDARIO = {"create_event": "crear el evento", "update_event": "cambiar el evento",
              "delete_event": "borrar el evento", "respond_to_event": "responder al evento"}
FORZADO = {"-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "-d"}
OPCIONES_GIT_CON_VALOR = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def git_push(comando: str) -> tuple[bool, bool]:
    """(hay un git push, es forzado). Mira el subcomando real, no el texto de los mensajes."""
    lex = shlex.shlex(comando.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        tokens = comando.split()
    hay = forzado = False
    orden: list[str] = []
    for t in tokens + [";"]:
        if t and set(t) <= set(";&|()"):
            if orden and orden[0].rsplit("/", 1)[-1] == "git":
                i = 1
                while i < len(orden) and orden[i].startswith("-"):
                    i += 2 if orden[i].split("=")[0] in OPCIONES_GIT_CON_VALOR and "=" not in orden[i] else 1
                if i < len(orden) and orden[i] == "push":
                    hay = True
                    resto = orden[i + 1:]
                    forzado = forzado or any(a.split("=")[0] in FORZADO or a.startswith("+") for a in resto)
            orden = []
        else:
            orden.append(t)
    return hay, forzado


def _lista(valor) -> str:
    return ", ".join(valor) if isinstance(valor, list) else str(valor or "")


def clasificar(herramienta: str, entrada: dict, proyecto: str = "") -> Veredicto:
    entrada = entrada if isinstance(entrada, dict) else {}
    accion = herramienta.split("__")[-1]
    servidor = herramienta.lower()  # el nombre del conector varía: claude_ai_Gmail, plugin_legal_gmail…
    if herramienta.startswith("mcp__") and "gmail" in servidor and accion in CORREO:
        para = _lista(entrada.get("to") or entrada.get("recipients")) or "alguien"
        asunto = entrada.get("subject") or ""
        palabras = len(str(entrada.get("body") or entrada.get("text") or "").split())
        adjuntos = entrada.get("attachments") or []
        resumen = (f"{CORREO[accion]} a {para}" + (f" con asunto «{asunto}»" if asunto else "")
                   + (f" y {len(adjuntos)} adjuntos" if adjuntos else "") + f", de unas {palabras} palabras")
        return Veredicto(CONFIRMAR, alta=True, resumen=resumen)
    if herramienta.startswith("mcp__") and "calendar" in servidor and accion in CALENDARIO:
        titulo = entrada.get("summary") or entrada.get("title") or ""
        inicio = entrada.get("start") or ""
        if isinstance(inicio, dict):
            inicio = inicio.get("dateTime") or inicio.get("date") or ""
        invitados = entrada.get("attendees") or []
        resumen = (f"{CALENDARIO[accion]} «{titulo}»" + (f" del {inicio}" if inicio else "")
                   + (f" con {len(invitados)} invitados" if invitados else ""))
        return Veredicto(CONFIRMAR, alta=bool(invitados), resumen=resumen)
    if herramienta == "Bash":
        hay, forzado = git_push(str(entrada.get("command") or ""))
        if hay:
            donde = f" desde {proyecto}" if proyecto else ""
            return Veredicto(CONFIRMAR, alta=forzado, resumen=f"subir cambios con git push{' forzado' if forzado else ''}{donde}")
    return Veredicto()


# --- respuestas a una confirmación -----------------------------------------------

AFIRMACIONES = re.compile(
    r"^(io[, ]+)?(si|sip|vale|confirmo|lo confirmo|confirmado|adelante|hazlo|dale|ok|okay|de acuerdo|claro|"
    r"venga|correcto|afirmativo|por supuesto|procede|sigue|sin problema|perfecto)\b")
NEGACIONES = re.compile(r"\b(no|nunca|cancela|cancelar|cancelalo|espera|para|alto|detente|quieto|ni hablar|"
                        r"mejor no|todavia|aun no|olvidalo|dejalo|pero)\b")


def interpretar(texto: str, alta: bool) -> str:
    """«si», «no» o «duda». Ante cualquier duda, no se confirma."""
    if "?" in texto or "¿" in texto:
        return "duda"
    t = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    t = " ".join(re.sub(r"[^\w\s]", " ", t).split())
    if not t:
        return "duda"
    if NEGACIONES.search(t):
        return "no"
    if alta:
        return "si" if re.search(r"(^|\s)(io\s+)?(lo\s+)?confirmo(\s|$)", t) else "duda"
    # «si» sin tilde seguido de más palabras suele ser condicional («si quieres…»)
    original = texto.strip().lower()
    if re.match(r"^(ío[,\s]+)?si\b", original) and len(re.sub(r"^io\s+", "", t).split()) > 1:
        return "duda"
    return "si" if AFIRMACIONES.match(t) else "duda"
