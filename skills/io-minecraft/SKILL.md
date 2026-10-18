---
name: io-minecraft
description: Mandar órdenes por voz a los personajes del Experimento A en Minecraft (Soma, Eco, Iris y Alma; antes Io y Claude) y cambiar su modo libre u órdenes. Úsala cuando el usuario diga «Eco, tala…», «que Iris vuelva», «Soma, ven», «ponlos en modo libre» o pida el estado de los bots.
---

# Guía: Minecraft (Experimento A)

Proyecto en `~/Documentos/thereisnospoon/laboratorio/mundo-simulado`. La guía completa de órdenes está en `bot/README.md`; léela si algo no cuadra.

**Nombres (desde el 2026-10-15):** Soma (puerto 3001, antes «Io»), Eco (3002), Iris (3003) y Alma (3004, femenina, antes «Claude»). Tú sigues siendo Ío: el personaje ya no se llama como tú. Si el usuario dice «Io» o «Claude» hablando de los personajes, se refiere a Soma o a Alma (los bots aún aceptan esos nombres como alias). Los diarios anteriores a esa fecha usan los nombres antiguos: **Io = Soma, Claude = Alma**.

## Antes de mandar nada
- Comprueba que el bot está en marcha: `curl -s "127.0.0.1:3001/?c=estado"`. Si no responde, el servidor o los bots están cerrados. **No los arranques por tu cuenta**: dile al usuario que no están en marcha y ofrece arrancarlos (servidor: `servidor/arrancar.sh`; bots: `cd bot && node io.js Soma Eco:3002:cooperativo Iris:3003 Alma:3004`, en segundo plano). Para pararlos usa `kill PID`, nunca `pkill -f`.
- Un hilo por trabajo: si hay un trabajador midiendo en Minecraft (`narrador trabajador lista`), no mandes órdenes sueltas que ensucien su serie; pregunta antes.

## Mandar una orden
Puertos: Soma 3001, Eco 3002, Iris 3003, Alma 3004. El texto va codificado en la URL.
```
curl -s "127.0.0.1:3002/?c=orden%20tala%203%20troncos"            # a Eco; responde al aceptarla
curl -s "127.0.0.1:3001/?c=orden%20Eco%2C%20ven"                  # por el puerto de Soma, para Eco
curl -s "127.0.0.1:3001/?c=orden%20todos%2C%20quietos"            # a todos los del proceso
curl -s "127.0.0.1:3002/?c=orden_esperar%20guarda%20en%20el%20cofre"   # responde al terminar
curl -s "127.0.0.1:3001/?c=modo"                                  # modo actual (libre u órdenes)
```
- Órdenes: ven, sígueme, quédate/quieto, tala N troncos (≤ 64), recoge [todo], guarda en el cofre, huye [de X], modo libre / modo órdenes, al terminar quieto|libre, perfil NOMBRE, estado, ayuda.
- Usa `orden` para lo que dura (tala, sígueme) y avisa por voz: «Eco empieza a talar tres troncos». Para saber cómo acabó, mira `?c=modo` (campo «última») o la línea nueva en `mente/diario.md`.
- Usa `orden_esperar` solo para cosas cortas (guardar en el cofre, estado).
- «Modo libre»: el personaje decide solo con su red y su perfil. «Modo órdenes»: quieto hasta que se le pide algo.

## Límites (no los saltes)
- Nunca talan ni pisan las zonas protegidas (GRANARBOL, ESTANQUE, HOGAR); si el usuario pide talar «el gran árbol», explícalo y no lo hagas.
- No pidas más de lo que el límite permite (tala ≤ 64). Los personajes no se dan órdenes entre ellos.
- Cualquier jugador que entre al servidor local puede dar órdenes por el chat; no es un riesgo externo, el servidor es local y offline.

## Qué decir por voz
Una frase para confirmar («Vale, Eco tala tres troncos») y otra al terminar con la cifra («Eco ha sacado tres troncos en cuarenta segundos»). Si la orden falla, di la causa que devuelve el bot, tal cual. De Alma habla en femenino («Alma está quieta», «Alma ha guardado…»).

## La mente de Alma (F6)
Alma es el cuarto personaje, femenino (puerto 3004; antes se llamaba «Claude»): la gobierna una sesión de Claude Code (la mente) con `mente/alma/mente.py`; la guía de la mente es `mente/alma/GUIA.md`. Es la que se usa en los experimentos en que un agente Claude actúa directamente en el mundo. Arranca con los demás: `node io.js Soma Eco:3002:cooperativo Iris:3003 Alma:3004` (en segundo plano, solo si el usuario lo pide).
- **Lanzar una sesión de la mente** (cuando el usuario diga «que Alma juegue», «que Alma construya una cabaña»…): un trabajador con contrato, uno cada vez sobre el servidor:
  `narrador trabajador lanzar mundo-simulado "Eres la mente de Alma: lee mente/alma/GUIA.md y síguela. Meta: TEXTO. Contrato: 45 minutos y 30 turnos (mente.py inicio --minutos 45 --turnos 30 --meta \"TEXTO\"). No arranques ni pares el servidor ni los bots." --contrato --modelo opus`
  Antes comprueba que el cuerpo responde (`curl -s "127.0.0.1:3004/?c=estado"`) y que no hay otro trabajador ocupado en el servidor.
- **Pararla**: `touch ~/Documentos/thereisnospoon/laboratorio/mundo-simulado/mente/alma/PARAR` (la mente lo ve en menos de medio minuto y cierra) o mandar por el puerto `orden Alma, quédate` (la mente lo recibe como orden externa). El cuerpo queda quieto en modo órdenes.
- **Qué contar por voz**: lo que diga `narrador trabajador lista` (resultado) y la última línea «fin» de `mente/alma/diario.md` (minutos, turnos, troncos). Si el usuario pregunta qué está haciendo Alma ahora: `curl -s "127.0.0.1:3004/?c=modo"` y la última línea de `mente/alma/diario.md`.
- **Rectángulo de obras**: Alma solo construye y mina dentro de `obras.json: permitido`. Si la mente propone uno en su informe y el usuario lo acepta de viva voz, escríbelo tú: `{"x1": …, "z1": …, "x2": …, "z2": …}` en ese campo (fuera de x 239..367 / z −32..96, de las zonas y de los cofres). Nunca toques `zonas.json`.
- Las órdenes de voz a Alma siguen valiendo (`orden Alma, …`); la mente las ve y no las pisa.
