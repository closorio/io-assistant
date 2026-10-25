# agent_voice · plugin «narrador»

**Ío**, tu asistente personal por voz sobre Claude Code, al estilo de Jarvis. Vive en su propia terminal, te escucha siempre (le hablas empezando por «Ío») y te ayuda con tus sesiones de Claude Code y tus proyectos, el escritorio, la agenda y el correo. También hace de mentor: observa la sesión en la que trabajas y te la comenta en voz alta.

- **Asistente (uso principal):** Alt + Shift derecho abre Ío. Ver [Ío, asistente](#ío-asistente).
- **Mentor:** Ío lo hace cuando se lo pides, y también hay `/narrador:mentor` para una sesión aparte. Un visor resume cada turno de la sesión observada.
- **Oído:** un daemon escucha el micrófono, detecta cuándo hablas (Silero VAD) y lo transcribe en local (faster-whisper). Solo le llega a Ío lo que va dirigido a él, y con la huella de voz, solo lo que dices tú. Con la escucha interna oye también lo que suena en el equipo (una reunión), marcado aparte.
- **Voz:** un hook `MessageDisplay` recoge las líneas que empiezan por `🎙️` y un daemon las lee en voz alta. Por defecto con Kokoro (voz Dora), en local; Piper y spd-say son los respaldos. No usa servicios de pago. Edge TTS está disponible como opción, pero va por internet.
- **Narrador (la idea original, opcional):** el output style `Narrador` hace que la misma sesión en la que trabajas narre lo que hace.

## Instalación

```bash
cd /home/seppuq/Documentos/thereisnospoon/io-assistant
scripts/instalar.sh                 # venv + Piper + faster-whisper + voz + modelo small (~600 MB) en ~/.local/share/narrador/
bin/narrador prueba                 # deberías oír una frase
bin/narrador salida hyperx          # opcional: que la voz salga por los cascos (bin/narrador salidas las lista)

# registrar el plugin en Claude Code (si `claude` no está en el PATH, usa el binario de la extensión de VS Code)
claude plugin marketplace add /home/seppuq/Documentos/thereisnospoon/io-assistant
claude plugin install narrador@agent-voice
```

Después, en VS Code, recarga la ventana (`Developer: Reload Window`).

**Tras cambiar el código del plugin:** Claude Code no ejecuta esta carpeta, sino una copia en `~/.claude/plugins/cache/`. Para que coja los cambios, sube `version` en `.claude-plugin/plugin.json`, ejecuta `claude plugin update narrador@agent-voice` y, en cada sesión abierta, `/reload-plugins`.

## Ío, asistente

**Abrirlo:** Alt + Shift derecho. Abre una terminal «Ío» en `~/Documentos` con `bin/io`. Si ya está abierto, te lo dice por voz, porque Wayland no deja traer su ventana al frente. Para retomar la última conversación, `bin/io --continuar`. La primera vez, Claude Code te pedirá confianza para `~/Documentos`: acéptala. Esa confianza no pasa a las subcarpetas, así que para que los trabajadores de un proyecto vayan en segundo plano (`claude --bg`) hay que abrir `claude` una vez en ese proyecto y aceptar allí. Mientras tanto van sin interfaz, que también funciona.

**Qué es:** una sesión de Claude Code con el agente `narrador:io`, definido en [agents/io.md](agents/io.md):
- **Modelo:** Sonnet 5.5.
- **Permisos:** modo `auto`. El clasificador de Claude Code deja pasar lo normal; lo que necesita permiso aparece en su terminal y Ío te avisa por voz.
- **Memoria propia** entre sesiones: un vault de notas (ver «Memoria de Ío» más abajo).
- **Al arrancar** se pone a escucharte y te saluda.

**Qué le puedes pedir** (cada capacidad tiene una guía que Ío lee cuando la necesita, `bin/narrador guia TEMA`):

| Guía | Ejemplos |
|---|---|
| `sesiones` | «¿Qué sesiones tengo abiertas?», «dile a la de buscasa que lance los tests», «lanza un trabajador en holo-ui que revise por qué fallan los tests» |
| `proyectos` | «¿En qué proyectos he estado esta semana?», «¿cómo está de git el dashboard?» |
| `escritorio` | «Abre el repo en VS Code», «recuérdame en 20 minutos llamar a Leo», «baja el volumen» |
| `personal` | «¿Qué tengo hoy?», «¿algún correo importante?», «prepárame un borrador para…». Necesita los conectores de claude.ai conectados |
| `mentor` | «Vigila la sesión de holo-ui y coméntamela» |
| `memoria` | «Recuerda que prefiero…», «¿qué decidimos sobre…?», «revisa tu memoria» |

**Trabajadores:** para trabajo largo en un proyecto, Ío lanza `claude --bg` en esa carpeta, con su `CLAUDE.md` y sus skills. Si esa carpeta concreta no es de confianza, usa `claude -p`, sin interfaz: lo que necesite permiso se le deniega y lo cuenta en su resultado. Para avisarte al terminar usa un Monitor con `narrador trabajador esperar NOMBRE`, que bloquea hasta que acaba e imprime de una vez su estado y el resumen del informe. `bin/narrador trabajador lista` y `bin/narrador trabajador abrir NOMBRE` los muestran. Los trabajadores y las terminales que abre Ío arrancan sin las variables `CLAUDE_CODE_*` de su sesión: si las heredan, Claude Code los trata como sesión hija y no guarda su conversación en el historial.

**Envíos y `git push`:** Ío no los hace por iniciativa propia. Antes de algo que salga en tu nombre te dice qué va a hacer y espera tu «sí». Es una norma de su persona, reforzada por un hook `PreToolUse` ([scripts/pretool.py](scripts/pretool.py), que usa [scripts/riesgo.py](scripts/riesgo.py)): ante un correo, un cambio de calendario o un `git push`, Ío te lo dice en voz alta y la aprobación se da en la pantalla. Solo actúa en la sesión de Ío. La confirmación hablada con «confirmo» ([scripts/riesgo.py](scripts/riesgo.py) ya la interpreta) queda sin conectar.

**Ío o `/narrador:mentor`, no los dos a la vez:** el oído entrega tus frases a una sola sesión. La segunda que lo intente recibe «ya te escucha Ío».

### Memoria de Ío

La memoria de Ío (`memory: user` en `agents/io.md`) vive donde Claude Code la fija, `~/.claude/agent-memory/narrador-io/`, y `~/Documentos/io-memoria` es un enlace para abrirla en Obsidian («Abrir carpeta como vault», solo con plugins del núcleo). Es un vault de notas en carpetas (`usuario/`, `reglas/`, `proyectos/`, `decisiones/`, `personas/`, `trabajadores/`, `aprendizaje/`, `referencias/`, `_archivo/`), cada una con frontmatter fijo y un `_indice.md` generado; `MEMORY.md` es el índice que Claude Code inyecta al arrancar y `ram.md` la memoria de trabajo. Es un repo git local sin remoto (la etiqueta `pre-vault` guarda el estado anterior a la migración del 2026-10-17). Reglas y formato: el `README.md` del vault y la skill [io-memoria](skills/io-memoria/SKILL.md). Herramientas: `narrador memoria revisar | indices | buscar | informes | guardar | evaluar` ([scripts/memoria.py](scripts/memoria.py)). Los informes de los trabajadores no entran en el vault: Ío destila de ellos un digest de hechos en `trabajadores/`.

### Parte matinal

En el primer arranque del día Ío da el parte: salud de producción de los tenants de chatcore (n8n, workflows, ejecuciones, Chatwoot, Supabase, Meta, certificados, chat de pruebas y sonda de conversación), saldo de OpenAI, servidores, pendientes de los `CLAUDE.md` de cada tenant, trabajadores y correo técnico, en tres o cuatro frases de voz con semáforo. Lo calcula `bin/narrador parte` ([scripts/parte_matinal.py](scripts/parte_matinal.py)), que es de solo lectura: GET, SSH de lectura e IMAP en modo lectura. La única excepción, apagada por defecto, es la **sonda de conversación**: un mensaje de prueba con sesión `web_demo_` al canal web de pruebas de cada tenant para comprobar que el bot contesta de verdad y no con relleno (así se habría visto el 2026-10-20 que OpenAI se había quedado sin créditos). Guía de Ío: [skills/io-parte-matinal/SKILL.md](skills/io-parte-matinal/SKILL.md). Pruebas: `.runtime/venv-tests/bin/python -m pytest -q tests`.

Configuración no secreta en `~/.config/narrador/parte.json` (todo opcional; los valores por defecto están en `CONFIG_DEFECTO`):

| Clave | Para qué sirve |
|---|---|
| `hora_corte`, `cache_horas` | Hora a la que empieza el día operativo (5) y horas que se reutiliza un parte (2) |
| `ssh` | `true` para comprobar disco, memoria y contenedores de los VPS por SSH |
| `imap_tech` | `true` para leer el correo de tech@ por IMAP y clasificarlo (alertas de facturación → rojo, otros avisos → ámbar) |
| `correo.clientes` | Regex extra (dominios, nombres) que cuentan como correo de cliente |
| `openai_saldo` | `recarga_usd` y `fecha_recarga` de la última recarga, para estimar saldo y días restantes con la Costs API |
| `sonda_e2e`, `sonda_mensaje` | Activa la sonda de conversación (por defecto `false`) y la pregunta que hace |
| `umbrales` | Latencias, errores, días de certificado, `sonda_ms` (20000) y `sonda_timeout_s` (40) |
| `raiz_tenants`, `tenants.<t>` | Carpeta de los tenants y, por tenant: `voz`, `tester`, `supabase_tablas`, `pendientes`, `sonda_e2e`, `sonda_formato` (`c3` o `chatwoot`), `sonda_webhook` (`wpp_staging` o `wpp`), `sonda_mensaje`, `sonda_resource_id` |

Credenciales que no están en ningún `.env` de tenant, en `~/.config/narrador/parte.env` (permisos 600, si no se ignora): `OPENAI_ADMIN_KEY` (clave de administración, solo costes), `TECH_IMAP_USER`, `TECH_IMAP_PASS` (contraseña de aplicación de Google) y `TECH_IMAP_HOST` (por defecto `imap.gmail.com`). Nada de eso sale en informes ni en el JSON.

## Mentor por voz en una sesión aparte

1. Trabaja en tu sesión de siempre, la **ejecutora**, sin estilo de voz.
2. Abre otra sesión de Claude Code **en el mismo proyecto** (otra pestaña de VS Code u otra terminal) y escribe `/narrador:mentor`. Si tienes varias sesiones abiertas, te preguntará cuál observar; `/narrador:mentor sesiones` las lista y `/narrador:mentor ID` elige una.
3. **Para hablarle, empieza la frase por «Ío»**: «Ío, ¿por qué ha cambiado eso?». Mientras dura la conversación puedes seguir sin nombrarle: mientras Ío habla o trabaja, y hasta `escucha.ventana` segundos después de la última actividad de cualquiera de los dos; cada frase tuya que la huella confirma vuelve a poner el plazo entero, y una frase que empieza dentro del plazo vale aunque acabe fuera. Pasado ese tiempo, si le hablas sin nombrarle, suena un tono suave y descendente: es que tienes que empezar por «Ío».
4. **Para interrumpirle, háblale**: a los ~250 ms de oírte (`escucha.corte`) comprueba con la huella de voz que eres tú y se calla. Sin huella, o si la voz no es la tuya (su propio eco, un vídeo), no se corta; tu frase le llega igual. Funciona mejor con cascos; si no quieres que te corte nunca a media frase, pon `escucha.interrumpir` a `false`. Escribir en su terminal también le calla; los avisos que le llegan solos (Monitor, tareas que terminan) no.
5. **Super+I** pausa o reanuda la escucha (cierra el micrófono). Lo confirma en voz alta.
6. **Avisos sonoros** (tonos cortos y suaves):
   - Dos notas que suben: Ío ya tiene lo que le has dicho.
   - Dos notas que bajan: te ha oído, pero no le has nombrado.
   - Tres notas que bajan: se ha cerrado la conversación; para seguir, vuelve a empezar por «Ío».
   - Tres notas que suben o bajan justo después de decir «escucha interna…»: activada o desactivada.

### Huella de voz

Con la huella, el oído solo deja pasar lo que suena a tu voz: un vídeo, una reunión por altavoces o alguien que habla a tu lado no se cuelan como órdenes. Todo es local. La huella es un vector de números, no tu audio, y se guarda en `huella.npy`, legible solo por ti. Sale de un modelo ONNX pequeño. Necesita `sherpa-onnx` en el venv y el modelo en `~/.local/share/narrador/modelos/wespeaker_resnet34.onnx`, que es `wespeaker_en_voxceleb_resnet34.onnx` de las versiones de sherpa-onnx en GitHub. `scripts/instalar.sh` todavía no instala ninguno de los dos.

- `bin/narrador huella grabar [SEGUNDOS]`: lee algo en voz alta durante 75 s, sin nada sonando. Mientras graba, el oído se pone en pausa.
- `bin/narrador huella probar`: di algo o pon un vídeo, y muestra el parecido con tu huella (1 = igual).
- `bin/narrador huella estado` / `borrar`.

`escucha.huella_umbral` fija el parecido mínimo (0,5). Las frases tuyas largas suelen dar 0,7–0,9; las muy cortas, menos.

### Escucha interna

Para que Ío oiga también una reunión o lo que suena en el equipo, activa la escucha interna. Hay tres formas:
- Pulsar **Mayús+Super+I**, que lo confirma en voz alta.
- Decir «escucha interna activada» o «escucha interna desactivada», sin nombrar a Ío.
- `bin/narrador escucha interna activar|desactivar|alternar|estado`.

- **Activada:** además del micrófono, el oído graba el monitor de la salida de audio (lo que suena, sin pasar por el aire) y lo transcribe. Le llega a Ío como `[voz-equipo] …`, que **nunca cuenta como orden**: no despierta a Ío aunque le nombren, no abre la conversación, no le corta y no cambia la escucha. Lo que coincide con la voz de Ío se descarta, para que no se oiga a sí mismo. Tu voz sigue llegando por el micrófono como siempre, con la huella.
- **Desactivada** (por defecto): solo el micrófono, y con la huella, solo tu voz.
- **Coste:** cada línea `[voz-equipo]` es un turno de Ío. En una reunión larga, actívala solo cuando quieras que Ío la siga.

Lo que conviene saber:

- **Latencia:** entre que te callas y empieza a contestar pasan unos 5–8 s. Son `escucha.silencio_fin` (0,8 s por defecto) para saber que has terminado, ~1,5 s de transcripción y `escucha.agrupar` (1,5 s) por si sigues hablando. El resto es el modelo pensando. Es una conversación por turnos, no una llamada.
- **Párrafos:** si haces pausas mientras piensas, las frases seguidas se juntan y le llegan a Ío como un solo mensaje cuando llevas `agrupar` s sin hablar. Con `silencio_fin` 1,8 y `agrupar` 1,5 aguanta pausas de unos 4–5 s. Si hablas más de 30 s seguidos, corta en la pausa más clara de los últimos 3 s, no a mitad de palabra.
- **Coste:** Ío despierta una vez por turno de la ejecutora y una vez por cada frase que le diriges; nunca por tiempo, ni por herramienta, ni por lo que hablas con otros (eso se descarta en local sin llegar al modelo). Lee resúmenes de pocas líneas, no el transcript. Para gastar menos, pon Sonnet o Haiku en su sesión (`/model`), y usa `/compact` o reinícialo en sesiones largas.
- **Privacidad:** el audio no sale del equipo. El micrófono solo está abierto mientras hay un mentor escuchando (se cierra a los 2 min de cerrarlo) y nunca en pausa. El monitor de la salida, solo con la escucha interna activada. El log guarda lo que le dijiste a Ío, no lo demás; de lo que suena en el equipo solo apunta cuántas palabras eran. El texto sí llega a la sesión de Ío.
- **Si no te entiende «Ío»:** di el nombre al principio y con una pausa breve. Whisper a veces lo escribe mal; dentro de la conversación da igual.
- **No toca el proyecto:** puede leer código para fundamentar lo que dice, pero no edita ni ejecuta nada que cambie algo.
- **Una sola voz:** no actives el estilo Narrador en la ejecutora, o las dos sesiones hablarán por la misma cola.
- **Escribir en la ejecutora no corta al mentor:** cada sesión solo calla lo que dijo ella misma.
- **Con `/clear` en la ejecutora**, el visor salta solo a la sesión nueva, salvo que lo hayas fijado con un ID.

El visor y el oído también se pueden usar a mano: `bin/narrador sesiones`, `bin/narrador seguir [ID]`, `bin/narrador escuchar`, `bin/narrador escucha [estado|pausa|activar|alternar|parar]`, `bin/narrador escucha interna [activar|desactivar|alternar|estado]` y `bin/narrador huella …`.

## Captura de decisiones

Antes de una decisión de calado, Claude tiene que decir por qué, y la razón queda apuntada. Lo hace un hook `PreToolUse` ([scripts/decisiones.py](scripts/decisiones.py)) que vigila:

- **Planes:** `Write` o `Edit` sobre `~/.claude/plans/*.md`, y `ExitPlanMode`.
- **Trabajadores:** un `Bash` con `narrador trabajador lanzar`, `claude --bg` o `claude -p`.
- **Lo que añadas** en `~/.local/share/narrador/decisiones/config.json` (opcional): `herramientas` (regex de nombres, p. ej. `"Agent"`), `bash` (regex de comandos; sustituye la lista por defecto), `editar_plan` (`false` para no pedir razón en cada `Edit` del plan), `razon_min` (15 caracteres), `plan_reciente_min` (60) y `activo`. Si añades herramientas, añádelas también al `matcher` del hook.

Si la llamada no trae la razón, el hook la bloquea y le pide a Claude que la repita con una línea `Por qué: …` (o `Porque: …`):
- en el plan o en el `new_string` del `Edit`, también como comentario `<!-- Por qué: … -->`;
- en el texto de `ExitPlanMode` (si llega sin texto, vale la línea `Por qué:` del plan escrito en la última hora);
- como comentario al final del comando: `narrador trabajador lanzar holo-ui "…"  # Por qué: …`;
- o en un archivo `<plan>.md.porque` junto al plan, que se borra al usarlo.

Con la razón, la deja pasar y añade una línea a `~/.local/share/narrador/decisiones/decisiones.jsonl`. El registro es append-only, con permisos 600, y cada línea es un objeto JSON:

```json
{"v": 1, "fecha": "2026-10-24T13:27:03-05:00", "sesion": "abc12345-…", "proyecto": "io-assistant", "cwd": "/home/…/io-assistant",
 "herramienta": "Write", "tipo": "plan_escribir", "objetivo": "/home/…/.claude/plans/p.md",
 "accion": "escribir el plan p.md «Plan X»", "razon": "…", "fuente": "marcador"}
```

`tipo` es `plan_escribir`, `plan_editar`, `plan_aprobar`, `trabajador`, `comando` u `otra`; `fuente` es `marcador`, `archivo` o `plan`; `v` es la versión del formato. Si el hook falla, la llamada pasa sin apuntar nada: nunca bloquea por un error suyo.

**Consultarlo:** `bin/narrador decisiones listar [-n N] [--sesion ID] [--proyecto P] [--desde AAAA-MM-DD] [--tipo T] [--json]` (con `--json`, una línea por decisión, para otra herramienta) y `bin/narrador decisiones ruta`. También vale `jq` sobre el archivo.

**Instalarlo (no está instalado):** va en los settings de usuario de Claude Code, no en el plugin, para que valga en todas las sesiones. Copia el bloque de [hooks/decisiones.settings.json](hooks/decisiones.settings.json) dentro de `hooks.PreToolUse` de `~/.claude/settings.json`, junto a lo que ya haya ahí, y abre una sesión nueva (o revisa `/hooks`). Apunta a `scripts/decisiones.py` de este repo, así que coge los cambios sin tocar la caché del plugin. Para quitarlo, borra ese bloque o pon `"activo": false` en el `config.json`.

## Narrador en la misma sesión (opcional)

Activa el estilo: menú `/`, luego **Output styles**, luego **Narrador**. En terminal: `/output-style`. El estilo se guarda por proyecto, así que solo narra donde lo actives. Si en una sesión no hay líneas `🎙️`, el plugin no hace nada.

## Control de la voz

**Desde Claude**, con `/narrador:voz` seguido de una de estas opciones:

| Opción | Qué hace |
|---|---|
| `estado` | Muestra cómo está la voz |
| `silencio` | La calla hasta que la actives |
| `activar` | Vuelve a hablar |
| `saltar` | Corta la frase que está sonando |
| `prueba` | Dice una frase de prueba |
| `motor piper\|spd` | Cambia el motor de voz |
| `voz NOMBRE` | Cambia la voz del motor actual |
| `velocidad N` | Cambia la velocidad |
| `tono épico\|tranquilo\|didáctico\|entusiasta` | Cambia el tono |

**Desde la terminal**, la misma CLI: `bin/narrador estado | silencio | activar | saltar | vaciar | prueba | parar | voces | decir TEXTO | motor M | voz V | velocidad N | salidas | salida TEXTO|defecto | sesiones | seguir [ID] | escuchar | escucha … | huella …`.

Cuando escribes un mensaje en una sesión, su voz se calla y descarta lo que tenía pendiente.

## Motores

| Motor | Coste | Calidad | Notas |
|---|---|---|---|
| `kokoro` (el que usa Ío) | Gratis, local | Natural | Voces en español: `ef_dora` (la elegida), `em_alex` y `em_santa`. Alrededor de 1 s por frase en CPU; la primera tras arrancar tarda 1,5 s más mientras carga el modelo |
| `piper` | Gratis, local | Correcta, algo plana | Unos 100–300 ms por frase en CPU. Es el primer respaldo |
| `edge` | Gratis, **por internet** | Natural | Voces de Microsoft (p. ej. `es-MX-DaliaNeural`). El texto que dice Ío sale hacia sus servidores. Necesita `ffmpeg` |
| `spd` | Gratis, local | Robótica | Usa `spd-say`. Es el último respaldo |

Si el motor elegido falla, habla el siguiente: Kokoro → Piper → spd, y Edge → Piper → spd. Kokoro nunca cae en Edge, para que tu texto no salga del equipo sin que lo sepas. Cada fallo queda en `~/.local/share/narrador/narrador.log`.

**Cambiar de motor o de voz:** `bin/narrador motor kokoro|piper|edge|spd`, `bin/narrador voz NOMBRE` y `bin/narrador velocidad N`, sobre el motor activo. `bin/narrador voces` las lista. También puedes pedírselo a Ío.

**Más voces de Piper:** `scripts/instalar.sh es_ES-sharvard-medium`, y después `bin/narrador voz es_ES-sharvard-medium`. Hay un catálogo en huggingface.co/rhasspy/piper-voices.

## Configuración (`~/.local/share/narrador/config.json`)

No existe hasta el primer cambio con la CLI; mientras tanto se usan los valores por defecto de `scripts/comun.py`.

| Clave | Para qué sirve |
|---|---|
| `motor` | `kokoro`, `piper`, `edge` o `spd` |
| `kokoro.voz` / `kokoro.velocidad` | Voz (`ef_dora`, `em_alex`, `em_santa`) y velocidad de Kokoro (0,5–2) |
| `edge.voz` / `edge.velocidad` | Voz de Edge y velocidad en % (-50..100) |
| `silencio` | `true` para que no hable |
| `cola_max` | Frases pendientes como máximo; si se supera, se descarta la más vieja |
| `reproductor` | `pw-play` por defecto; `aplay` si no usas PipeWire |
| `destino` | Salida de audio de la voz (`node.name` de PipeWire); `null` = la del sistema. Cámbiala con `narrador salida` |
| `piper.voz` / `piper.velocidad` / `piper.hablante` | Voz, velocidad (0,5–2) y hablante (en voces con varios, como `es_ES-sharvard-medium`) de Piper |
| `spd.idioma` / `spd.velocidad` | Idioma y velocidad de spd (-100..100). spd ignora `destino` |
| `escucha.nombre` | Palabra que despierta a Ío (`Ío`) |
| `escucha.ventana` | Segundos sin tener que nombrarle, contados desde la última actividad: lo último que Ío dijo o hizo, o tu última frase confirmada por la huella (90). Mientras sigue la conversación, la cuenta no corre; un vídeo o otra voz no la alargan |
| `escucha.aviso_descarte` | `true` para oír un tono cuando descarta una frase por no oír su nombre |
| `escucha.interrumpir` | `true` para cortarle hablando, solo si la huella confirma que eres tú; mejor con cascos |
| `escucha.pausa` | Micrófono cerrado (Super+I lo alterna) |
| `escucha.modelo` | Modelo de faster-whisper: `small` (~1,5 s por frase); `base` es 3 veces más rápido pero entiende bastante peor |
| `escucha.microfono` | Entrada de pw-record (`node.name`); `null` = la del sistema |
| `escucha.silencio_fin` | Segundos de silencio para dar una frase por terminada (0,8); más, si te corta mientras piensas |
| `escucha.agrupar` / `escucha.agrupar_max` | Segundos de calma tras tu última frase para entregarle a Ío el párrafo entero (1,5; 0 = frase a frase) y tope de segundos que se retiene un párrafo (25) |
| `escucha.corte` | Segundos de tu voz sobre la de Ío para cortarle (0,25); más, si se corta solo por eco |
| `escucha.aviso_recibido` / `escucha.avisos_sonoros` | `false` para quitar el tono de «recibido» / los de «conversación cerrada» y «no te oigo» |
| `escucha.huella` / `escucha.huella_umbral` | Filtro por tu huella de voz (lo activa `narrador huella grabar`) y parecido mínimo para dejar pasar una frase (0,5) |
| `escucha.interna` | Escucha interna: oír también lo que suena en el equipo (Mayús+Super+I lo alterna) |
| `escucha.monitor` | Salida cuyo monitor oye la escucha interna (`node.name`); `null` = la del sistema |

La CLI edita este archivo y avisa al daemon.

## Cómo funciona

```
sesión ejecutora ──escribe──▶ ~/.claude/projects/<proyecto>/<sesión>.jsonl
                                      │  visor (scripts/visor.py): un resumen por turno
                                      ▼
micrófono ─▶ oído (scripts/oido.py): Silero VAD → faster-whisper → ¿tu huella? ¿«Ío» o conversación abierta?
monitor de la salida ─▶ (solo con escucha interna) → [voz-equipo], nunca órdenes
                                      │  oido.jsonl → narrador escuchar (scripts/escucha.py)
                                      ▼
sesión mentora: dos Monitor despiertan a Ío ──▶ "🎙️ Ojo, ese test no cubre…"
                                      │  hook MessageDisplay (scripts/hook.py, ~30 ms, no altera la pantalla)
                                      ▼
socket unix $XDG_RUNTIME_DIR/narrador-<uid>.sock
                                      ▼
daemon (scripts/daemon.py): cola → motor (scripts/motores.py) → WAV → pw-play
```

- **El visor** da un turno por cerrado cuando ve `end_turn` y 2 s de calma. También avisa si la ejecutora te está preguntando algo, si la interrumpes, y cada 3 min en turnos muy largos. Guarda por dónde va en `~/.local/share/narrador/visor/`: cuando Monitor caduca (máximo 30 min) y el mentor lo vuelve a arrancar, sigue sin repetir nada.
- **El oído** es un daemon aparte, porque carga Whisper y tiene el micrófono abierto. Lo arranca `narrador escuchar`, que le da latido; sin latido durante 2 min se apaga. Da una frase por terminada tras `silencio_fin` s de silencio y descarta ruido, frases cortas y las alucinaciones típicas de Whisper. Mientras Ío habla, la conversación cuenta como abierta. Con la escucha interna abre un segundo pw-record sobre el monitor de la salida (`stream.capture.sink`), con su propio VAD. Whisper atiende primero tus frases y después las del equipo.
- **En VS Code y con `claude -p`**, el hook recibe cada mensaje completo cuando termina. En la terminal interactiva lo recibe por grupos de líneas, mientras Claude escribe.
- **El daemon** sintetiza la frase siguiente mientras suena la actual, así entre frase y frase no hay hueco (Kokoro tarda unos 2 s por frase; el audio dura 3 o 4). Arranca solo con la primera frase y no puede haber dos a la vez (lo impide `~/.local/share/narrador/narrador.lock`, común al repo y a la copia del plugin). Recuerda de qué sesión es cada frase. Se apaga tras 45 min sin actividad, o con `bin/narrador parar`.
- **El hook nunca escribe en stdout ni falla**: si algo va mal, la frase se pierde sin molestar a Claude.

## Archivos

```
.claude-plugin/    plugin.json, marketplace.json (marketplace local "agent-voice")
agents/io.md       el agente Ío: persona, modelo y memoria
skills/io-*/       guías de Ío como skills (sesiones, proyectos, escritorio, personal, mentor); `narrador guia` las lee como respaldo
skills/mentor/     /narrador:mentor (mentor en una sesión aparte)
skills/voz/        /narrador:voz
output-styles/     narrador.md (estilo opcional para narrar en la misma sesión)
hooks/hooks.json   MessageDisplay y UserPromptSubmit → scripts/hook.py
hooks/decisiones.settings.json   fragmento para ~/.claude/settings.json: captura de decisiones → scripts/decisiones.py
scripts/           comun.py, hook.py, daemon.py, motores.py, visor.py, oido.py, escucha.py, huella.py,
                   asistente.py, riesgo.py, pretool.py, parte_matinal.py, memoria.py, instalar.sh
tests/             pruebas de riesgo.py, pretool.py y parte_matinal.py (.runtime/venv-tests/bin/python -m pytest -q tests)
bin/narrador       CLI (en el PATH de Bash mientras el plugin esté activo)
bin/io             lanzador de Ío (una sola instancia, en ~/Documentos)
bin/io-ventana     lo que ejecuta Alt + Shift derecho
```

El estado vive fuera del repo, en `${XDG_DATA_HOME:-~/.local/share}/narrador/`: venv, voces, modelo de Whisper, `config.json`, log, locks, posición del visor y del oído y WAV temporales. Así el repo y la copia instalada del plugin comparten el mismo.

Los atajos son atajos propios de GNOME, en Configuración → Teclado → Atajos personalizados:
- **Super+I** («Ío: pausar o reanudar la escucha») ejecuta `bin/narrador escucha alternar`.
- **Mayús+Super+I** («Ío: escucha interna (oír también el equipo)») ejecuta `bin/narrador escucha interna alternar`.
- **Alt + Shift derecho** («Ío: abrir») ejecuta `bin/io-ventana`.

## Siguiente paso: que conteste antes

Hoy tarda 5–8 s en empezar a contestar porque cada frase es un turno completo del modelo. Bajarlo a 1–2 s, como en una llamada, pide otra arquitectura: Pipecat con SmallWebRTC, faster-whisper en streaming y el Agent SDK como cerebro con respuestas parciales (`include_partial_messages`), leyendo frase a frase mientras se generan. Supone días de trabajo.

## Desinstalar

```bash
claude plugin uninstall narrador@agent-voice
claude plugin marketplace remove agent-voice
bin/narrador escucha parar
bin/narrador parar
rm -rf ~/.local/share/narrador
# y borra los atajos «Ío: pausar o reanudar la escucha», «Ío: escucha interna» e «Ío: abrir» en Configuración → Teclado
```
