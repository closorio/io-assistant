# io-cabina

Mod de Claude Code que pinta la cabina de Ío: paneles de sesiones, puertas, roadmap y tablero, la
franja sobre el prompt, tonos cortos y herramientas propias para Ío. Solo lee y escribe a través de
la orden `narrador` del mismo checkout (`../../bin/narrador`), que localiza al arrancar.

## Carga

`bin/io` lo carga con `--plugin-dir ~/.local/share/narrador/mods/io-cabina`, que es un enlace
simbólico a esta carpeta. Tras cambiarlo: `/reload-plugins` en la sesión de Ío, o relanzarla.

## Cómo funciona cada parte

- **Puertas** (`narrador puerta …`, en `~/.local/share/narrador/puertas.json`): la sección de la
  cabina y la pestaña `/puertas` las listan con botones Sí y No. Un botón llama a
  `narrador puerta responder ID si|no --origen cabina`, que solo anota; después el mod se lo hace
  llegar a Ío con `$.prompt.submit` (un mensaje del mod que entra como turno nuevo en cuanto Ío está
  libre). **Nunca se ejecuta el comando de la puerta**: eso lo hace Ío. Fuera de la sesión de Ío no
  se manda nada; ahí sirve `narrador puerta esperar ID` en un Monitor.
- **Franja** (`AbovePrompt`): trabajadores en marcha por id corto y tarea, esperas de permiso,
  puertas abiertas, lo que ya enseñaba (bloqueadas, alertas, parte, roadmap, hallazgos) y el gasto
  de esta sesión si el motor lo lleva (`$.session.usage`). El gasto de todo el día no se puede
  saber sin coste: haría falta medir cada sesión. Si no hay nada, no sale.
- **Tonos** (`assets/tonos/*.wav`): «terminado», «puerta» y «error», uno por vuelta del sondeo y
  nunca en la primera (arranque o recarga). Suenan con `narrador tono`, que calla con el narrador en
  silencio o la escucha en pausa y espera a que Ío termine de hablar. `$.audio.play` no se usa
  porque en una terminal de Linux no suena.
- **Herramientas** (`mcp__io-cabina__…`): `trabajador_lanzar`, `trabajador_lista`, `permisos`,
  `sesiones_vivas` y `puerta_anadir` (sin «ñ»: el nombre solo admite ASCII). Se registran solo si la
  sesión es la de `io.json`. No hay `trabajador_esperar`: bloquearía el turno de Ío hasta 30 min;
  sigue con Monitor sobre `narrador trabajador esperar`.

## Comprobar

    claude plugin validate mods/io-cabina
    claude plugin test mods/io-cabina
    tsc -p mods/io-cabina      # TypeScript ≥ 5.4; el tsconfig deja fuera los tipos MCP (TS2589)
