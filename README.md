# agent_voice · plugin «narrador»

**Ío**, tu asistente personal por voz sobre Claude Code, al estilo de Jarvis. Vive en su propia terminal, te escucha siempre (le hablas empezando por «Ío») y te ayuda con tus sesiones de Claude Code y tus proyectos, el escritorio, la agenda y el correo. También hace de mentor: observa la sesión en la que trabajas y te la comenta en voz alta.

- **Asistente (uso principal):** Alt + Shift derecho abre Ío. Ver [Ío, asistente](#ío-asistente).
- **Mentor:** Ío lo hace cuando se lo pides, y también hay `/narrador:mentor` para una sesión aparte. Un visor resume cada turno de la sesión observada.
- **Oído:** un daemon escucha el micrófono, detecta cuándo hablas (Silero VAD) y lo transcribe en local (faster-whisper). Solo le llega a Ío lo que va dirigido a él.
- **Voz:** un hook `MessageDisplay` recoge las líneas que empiezan por `🎙️` y un daemon las lee en voz alta. Por defecto con Kokoro (voz Dora), en local; Piper y spd-say son los respaldos. No usa servicios de pago. Edge TTS está disponible como opción, pero va por internet.
- **Narrador (la idea original, opcional):** el output style `Narrador` hace que la misma sesión en la que trabajas narre lo que hace.

## Instalación

```bash
cd /home/seppuq/Documentos/thereisnospoon/agent_voice
scripts/instalar.sh                 # venv + Piper + faster-whisper + voz + modelo small (~600 MB) en ~/.local/share/narrador/
bin/narrador prueba                 # deberías oír una frase
bin/narrador salida hyperx          # opcional: que la voz salga por los cascos (bin/narrador salidas las lista)

# registrar el plugin en Claude Code (si `claude` no está en el PATH, usa el binario de la extensión de VS Code)
claude plugin marketplace add /home/seppuq/Documentos/thereisnospoon/agent_voice
claude plugin install narrador@agent-voice
```

Después, en VS Code, recarga la ventana (`Developer: Reload Window`).

**Tras cambiar el código del plugin:** Claude Code no ejecuta esta carpeta, sino una copia en `~/.claude/plugins/cache/`. Para que coja los cambios, sube `version` en `.claude-plugin/plugin.json`, ejecuta `claude plugin update narrador@agent-voice` y, en cada sesión abierta, `/reload-plugins`.

## Ío, asistente

**Abrirlo:** Alt + Shift derecho. Abre una terminal «Ío» en `~/Documentos` con `bin/io`. Si ya está abierto, te lo dice por voz, porque Wayland no deja traer su ventana al frente. Para retomar la última conversación, `bin/io --continuar`. La primera vez, Claude Code te pedirá confianza para `~/Documentos`: acéptala. Esa confianza no pasa a las subcarpetas, así que para que los trabajadores de un proyecto vayan en segundo plano (`claude --bg`) hay que abrir `claude` una vez en ese proyecto y aceptar allí. Mientras tanto van sin interfaz, que también funciona.

**Qué es:** una sesión de Claude Code con el agente `narrador:io`, definido en [agents/io.md](agents/io.md):
- **Modelo:** Sonnet 5.5.
- **Permisos:** modo `auto`. El clasificador de Claude Code deja pasar lo normal; lo que necesita permiso aparece en su terminal y Ío te avisa por voz.
- **Memoria propia** entre sesiones.
- **Al arrancar** se pone a escucharte y te saluda.

**Qué le puedes pedir** (cada capacidad tiene una guía que Ío lee cuando la necesita, `bin/narrador guia TEMA`):

| Guía | Ejemplos |
|---|---|
| `sesiones` | «¿Qué sesiones tengo abiertas?», «dile a la de buscasa que lance los tests», «lanza un trabajador en holo-ui que revise por qué fallan los tests» |
| `proyectos` | «¿En qué proyectos he estado esta semana?», «¿cómo está de git el dashboard?» |
| `escritorio` | «Abre el repo en VS Code», «recuérdame en 20 minutos llamar a Leo», «baja el volumen» |
| `personal` | «¿Qué tengo hoy?», «¿algún correo importante?», «prepárame un borrador para…». Necesita los conectores de claude.ai conectados |
| `mentor` | «Vigila la sesión de holo-ui y coméntamela» |

**Trabajadores:** para trabajo largo en un proyecto, Ío lanza `claude --bg` en esa carpeta, con su `CLAUDE.md` y sus skills. Si esa carpeta concreta no es de confianza, usa `claude -p`, sin interfaz: lo que necesite permiso se le deniega y lo cuenta en su resultado. Sigue el avance y te avisa al terminar. `bin/narrador trabajador lista` y `bin/narrador trabajador abrir NOMBRE` los muestran.

**Envíos y `git push`:** Ío no los hace por iniciativa propia. Antes de algo que salga en tu nombre te dice qué va a hacer y espera tu «sí». Es una norma de su persona, reforzada por un hook `PreToolUse` ([scripts/pretool.py](scripts/pretool.py), que usa [scripts/riesgo.py](scripts/riesgo.py)): ante un correo, un cambio de calendario o un `git push`, Ío te lo dice en voz alta y la aprobación se da en la pantalla. Solo actúa en la sesión de Ío. La confirmación hablada con «confirmo» ([scripts/riesgo.py](scripts/riesgo.py) ya la interpreta) queda sin conectar.

**Ío o `/narrador:mentor`, no los dos a la vez:** el oído entrega tus frases a una sola sesión. La segunda que lo intente recibe «ya te escucha Ío».

## Mentor por voz en una sesión aparte

1. Trabaja en tu sesión de siempre, la **ejecutora**, sin estilo de voz.
2. Abre otra sesión de Claude Code **en el mismo proyecto** (otra pestaña de VS Code u otra terminal) y escribe `/narrador:mentor`. Si tienes varias sesiones abiertas, te preguntará cuál observar; `/narrador:mentor sesiones` las lista y `/narrador:mentor ID` elige una.
3. **Para hablarle, empieza la frase por «Ío»**: «Ío, ¿por qué ha cambiado eso?». Mientras dura la conversación puedes seguir sin nombrarle: mientras Ío habla o trabaja, y hasta 90 s después. Pasado ese tiempo, si le hablas sin nombrarle, suena un tono suave y descendente: es que tienes que empezar por «Ío».
4. **Para interrumpirle, háblale**: a los ~250 ms de oírte se calla. Solo tiene sentido con cascos; con altavoces, pon `escucha.interrumpir` a `false`, o se cortaría a sí mismo.
5. **Super+I** pausa o reanuda la escucha (cierra el micrófono). Lo confirma en voz alta.

Lo que conviene saber:

- **Latencia:** entre que te callas y empieza a contestar pasan unos 5–8 s: 0,8 s para saber que has terminado, ~1,5 s de transcripción y el resto es el modelo pensando. Es una conversación por turnos, no una llamada.
- **Coste:** Ío despierta una vez por turno de la ejecutora y una vez por cada frase que le diriges; nunca por tiempo, ni por herramienta, ni por lo que hablas con otros (eso se descarta en local sin llegar al modelo). Lee resúmenes de pocas líneas, no el transcript. Para gastar menos, pon Sonnet o Haiku en su sesión (`/model`), y usa `/compact` o reinícialo en sesiones largas.
- **Privacidad:** el audio no sale del equipo. El micrófono solo está abierto mientras hay un mentor escuchando (se cierra a los 2 min de cerrarlo) y nunca en pausa. El log guarda lo que le dijiste a Ío, no lo demás.
- **Si no te entiende «Ío»:** di el nombre al principio y con una pausa breve. Whisper a veces lo escribe mal; dentro de la conversación da igual.
- **No toca el proyecto:** puede leer código para fundamentar lo que dice, pero no edita ni ejecuta nada que cambie algo.
- **Una sola voz:** no actives el estilo Narrador en la ejecutora, o las dos sesiones hablarán por la misma cola.
- **Escribir en la ejecutora no corta al mentor:** cada sesión solo calla lo que dijo ella misma.
- **Con `/clear` en la ejecutora**, el visor salta solo a la sesión nueva, salvo que lo hayas fijado con un ID.

El visor y el oído también se pueden usar a mano: `bin/narrador sesiones`, `bin/narrador seguir [ID]`, `bin/narrador escuchar` y `bin/narrador escucha [estado|pausa|activar|alternar|parar]`.

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

**Desde la terminal**, la misma CLI: `bin/narrador estado | silencio | activar | saltar | vaciar | prueba | parar | voces | decir TEXTO | motor M | voz V | velocidad N | salidas | salida TEXTO|defecto | sesiones | seguir [ID] | escuchar | escucha …`.

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
| `escucha.ventana` | Segundos de conversación sin tener que nombrarle, contados desde lo último que Ío dijo o hizo (90) |
| `escucha.aviso_descarte` | `true` para oír un tono cuando descarta una frase por no oír su nombre |
| `escucha.interrumpir` | `true` para cortarle hablando; solo con cascos |
| `escucha.pausa` | Micrófono cerrado (Super+I lo alterna) |
| `escucha.modelo` | Modelo de faster-whisper: `small` (~1,5 s por frase); `base` es 3 veces más rápido pero entiende bastante peor |
| `escucha.microfono` | Entrada de pw-record (`node.name`); `null` = la del sistema |

La CLI edita este archivo y avisa al daemon.

## Cómo funciona

```
sesión ejecutora ──escribe──▶ ~/.claude/projects/<proyecto>/<sesión>.jsonl
                                      │  visor (scripts/visor.py): un resumen por turno
                                      ▼
micrófono ─▶ oído (scripts/oido.py): Silero VAD → faster-whisper → ¿«Ío» o conversación abierta?
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
- **El oído** es un daemon aparte, porque carga Whisper y tiene el micrófono abierto. Lo arranca `narrador escuchar`, que le da latido; sin latido durante 2 min se apaga. Da una frase por terminada tras 0,8 s de silencio y descarta ruido, frases cortas y las alucinaciones típicas de Whisper. Mientras Ío habla, la conversación cuenta como abierta.
- **En VS Code y con `claude -p`**, el hook recibe cada mensaje completo cuando termina. En la terminal interactiva lo recibe por grupos de líneas, mientras Claude escribe.
- **El daemon** arranca solo con la primera frase y no puede haber dos a la vez (lo impide `~/.local/share/narrador/narrador.lock`, común al repo y a la copia del plugin). Recuerda de qué sesión es cada frase. Se apaga tras 45 min sin actividad, o con `bin/narrador parar`.
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
scripts/           comun.py, hook.py, daemon.py, motores.py, visor.py, oido.py, escucha.py, asistente.py,
                   riesgo.py, pretool.py, instalar.sh
tests/             pruebas de riesgo.py y pretool.py (python3 -m unittest discover -s tests)
bin/narrador       CLI (en el PATH de Bash mientras el plugin esté activo)
bin/io             lanzador de Ío (una sola instancia, en ~/Documentos)
bin/io-ventana     lo que ejecuta Alt + Shift derecho
```

El estado vive fuera del repo, en `${XDG_DATA_HOME:-~/.local/share}/narrador/`: venv, voces, modelo de Whisper, `config.json`, log, locks, posición del visor y del oído y WAV temporales. Así el repo y la copia instalada del plugin comparten el mismo.

Los atajos son atajos propios de GNOME, en Configuración → Teclado → Atajos personalizados:
- **Super+I** («Ío: pausar o reanudar la escucha») ejecuta `bin/narrador escucha alternar`.
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
# y borra los atajos «Ío: pausar o reanudar la escucha» e «Ío: abrir» en Configuración → Teclado
```
