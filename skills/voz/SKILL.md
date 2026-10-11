---
name: voz
description: Controla la voz del narrador youtuber (estado, silencio, activar, saltar, prueba, motor, voz, velocidad, tono).
argument-hint: "[estado|silencio|activar|saltar|prueba|motor piper|spd|voz NOMBRE|velocidad N|tono épico|tranquilo|didáctico]"
disable-model-invocation: true
allowed-tools: Bash(narrador *)
---

# Control de la voz del narrador

Argumentos recibidos: `$ARGUMENTS`

Traduce los argumentos a una orden de la CLI `narrador` (está en el PATH mientras el plugin esté activo), ejecútala con Bash y resume el resultado en una frase.

| Argumentos | Orden |
|---|---|
| (vacío) o `estado` | `narrador estado`, y después lista brevemente las opciones de esta tabla |
| `silencio`, `calla`, `mute` | `narrador silencio` |
| `activar`, `habla`, `on` | `narrador activar` |
| `saltar` | `narrador saltar` |
| `prueba` | `narrador prueba` |
| `motor X` | `narrador motor X` (piper o spd) |
| `voz X` | `narrador voz X`; para ver las voces de Piper instaladas, `narrador voces`. Para instalar otra: `${CLAUDE_PLUGIN_ROOT}/scripts/instalar.sh NOMBRE` |
| `velocidad N` | `narrador velocidad N` |
| `parar` | `narrador parar` |

## Tono

`tono X` no ejecuta nada: desde ahora, escribe las líneas 🎙️ con ese tono y mantenlo hasta que el usuario pida otro.

- **épico**: tráiler de película, frases solemnes, cada test en verde es una victoria.
- **tranquilo**: voz pausada, como un directo nocturno; pocas exclamaciones.
- **didáctico**: profesor cercano; explica en una frase el porqué de cada paso.
- **entusiasta** (por defecto): youtuber con energía, cercano, en plural.

Confirma el cambio con una línea 🎙️ ya en el tono nuevo.

Si en esta sesión nadie escribe líneas 🎙️, recuerda que hay dos maneras de tener voz: el mentor, con `/narrador:mentor` en una sesión aparte, o el estilo «Narrador» en esta (menú `/`, luego Output styles).
