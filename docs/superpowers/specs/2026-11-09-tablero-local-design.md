# Tablero de hallazgos en un archivo local y en el mod io-cabina: diseño

Fecha: 2026-11-09. Estado: aprobado por el usuario e implementado. Sustituye, solo en el almacenamiento y en la interfaz, a [2026-11-03-tablero-hallazgos-design.md](2026-11-03-tablero-hallazgos-design.md); el modelo de la tarjeta y las reglas de transición de aquel documento siguen vigentes.

## Por qué

El usuario no quiere abrir la página del tablero cada vez que arranca su asistente: quiere verlo en una pestaña del mod io-cabina, como `/roadmap`, y mover y cerrar tarjetas desde ahí. Además, con las tarjetas en la base de datos de la página solo podía escribirlas el asistente, en cinco pasos con aprobaciones, y el tablero llevaba sin cruzarse con el parte desde el 2026-11-03.

Decisión: la fuente de verdad es un archivo local de este equipo que leen y escriben el parte, el mod y la voz.

## El archivo

`~/.local/share/narrador/tablero.json`:

```json
{"v": 1, "rev": 37, "parte_fecha": "2026-11-09",
 "ultimo_movimiento": {"id": "…", "de": "nuevos", "a": "en_curso", "marca": null, "origen": "mod"},
 "tarjetas": {"<ambito>--<check>": {"…las doce claves de la tarjeta…"}}}
```

- Un solo archivo: cada lectura es una foto coherente.
- `rev` sube en cada escritura. `parte_fecha` es la fecha del último parte completo cruzado sin avisos. `ultimo_movimiento` es lo único que hace falta para deshacer.
- **Escritura atómica**: temporal en la misma carpeta, `fsync`, `os.replace`. La versión anterior queda en `tablero.json.bak`.
- **Un escritor a la vez**: quien escribe toma `flock` exclusivo sobre `tablero.lock` y hace leer → modificar → guardar dentro. Espera hasta 5 segundos; si no, sale con 5. Quien solo lee no bloquea.
- **Nadie edita el archivo a mano.** El mod y el asistente pasan siempre por `narrador tablero`.
- **Nunca un verde falso**: un archivo ilegible es un error (código 3), no un tablero vacío, y no se reescribe. Una tarjeta suelta con el esquema roto se conserva tal cual, no se toca, se avisa y hace que el plan no sea fiable.

## Órdenes

| Orden | Hace |
|---|---|
| `narrador tablero ver [--json]` | Enseña el tablero. Sin archivo, vacío con `existe: false` |
| `narrador tablero plan [--fecha F] [--parte A]` | Simula el cruce con el parte. No escribe |
| `narrador tablero aplicar [--fecha F] [--parte A] [--crear]` | Cruza y guarda. Devuelve el plan (`semaforo`, `voz`, `sin_comprobar`, `fiable`, `avisos`) y `aplicados` |
| `narrador tablero mover ID COLUMNA --origen mod\|voz [--desde COLUMNA]` | Mueve una tarjeta, apunta el historial y `ultimo_movimiento`. Devuelve el tablero |
| `narrador tablero deshacer --origen mod\|voz` | Devuelve el último movimiento manual a su columna y a su marca anteriores, si la tarjeta sigue donde se dejó |
| `narrador tablero importar CARPETA` | Migración desde la carpeta exportada de la página. No pisa un tablero existente |

Códigos de salida: 0 bien · 1 no hay tal tarjeta, ya está ahí o no hay nada que deshacer · 3 archivo o parte ilegible · 4 la tarjeta ya no está en la columna de `--desde` · 5 cerrojo ocupado.

`--desde` es la protección contra mover sobre datos viejos (sustituye a `if_version`): si el parte resolvió la tarjeta mientras el mod la mostraba en «nuevos», el movimiento no se hace y el mod refresca.

Orígenes del historial: `parte` (el cruce), `mod` y `voz` (movimientos manuales) y `pagina` (solo en historiales anteriores a la migración). La fecha de un movimiento manual es la del día; la del cruce, la del parte.

`CIERRE_MANUAL` se mantiene: las tarjetas de `respuestas_fallo` no pasan solas a resueltos.

## La pestaña del mod

En `~/.local/share/narrador/mods/io-cabina` (la copia que carga `bin/io`):

- Se abre sola al arrancar, junto a la cabina, y con `/tablero`.
- Lee `narrador tablero ver --json` al arrancar y cada 20 segundos.
- Cuatro secciones, una debajo de otra porque el panel es estrecho: nuevos, en curso, dejados de lado y resueltos. Cada tarjeta enseña el nivel (rojo o ámbar), el cliente, el título y el detalle.
- Pulsar una tarjeta la despliega y enseña los botones de mover, con atajo: `n` nuevos, `c` en curso, `d` dejar de lado, `r` resolver. El botón `u` deshace.
- Cada botón ejecuta `narrador tablero mover … --origen mod --desde …` y repinta con su salida.

## La página web

Se deja de usar, sin convertirla en copia de solo lectura: una copia exigiría empujar los datos a la página en cada parte, que es justo el paso que estaba parado; la página deja mover tarjetas a su dueño, así que divergiría en silencio; y una copia caducada que parece viva es peor que ninguna. No se borra la página ni su base de datos; `web/tablero.html` queda en el repositorio como referencia.

## Migración

Las doce tarjetas exportadas el 2026-11-09 (`~/.local/share/narrador/tablero-export-20261109/`, un JSON por tarjeta, id = nombre del archivo) se cargan con `narrador tablero importar`. El detalle vuelve a pasar por `ocultar()`.

## Pruebas

`tests/test_tablero_archivo.py` (almacén), `tests/test_tablero.py` (reglas y órdenes) y `tests/tablero.test.tsx` en el mod.
