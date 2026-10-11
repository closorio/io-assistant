# Guía: sesiones de Claude Code

## Ver qué hay

- `narrador sesiones --vivas`: las sesiones abiertas ahora (nombre, si está ocupada o libre, carpeta, título).
- `narrador sesiones --todas`: las más recientes de todos los proyectos, abiertas o no.
- La herramienta `ListAgents` da las sesiones a las que puedes mandar mensajes.

## Observar una sesión

Arranca Monitor con `narrador seguir ID`, la descripción «turnos de <proyecto>» y `timeout_ms` 1800000. Cada evento `[visor]` resume un turno: lo que pidió el usuario, las herramientas, los errores y la respuesta. Coméntalo como mentor, siguiendo la guía `mentor`. Si caduca, rearma la misma orden. Para dejar de observar, usa TaskStop sobre ese Monitor.

## Hablar con una sesión abierta

- `SendMessage` con el nombre que da `ListAgents`, cuando el usuario te pida que le digas algo a esa sesión: «dile a la de buscasa que lance los tests». La primera línea tiene que entenderse sola.
- Esa sesión actúa con sus propios permisos; los permisos que le pida al usuario aparecen en su ventana.
- `notify_when_idle: true` te avisa una vez, cuando termina lo que está haciendo. No preguntes en bucle.

## Trabajadores (tareas largas en otro proyecto)

- `narrador trabajador lanzar PROYECTO "TAREA" [--modelo opus]` arranca una sesión en segundo plano en ese proyecto, con su `CLAUDE.md` y sus skills. Usa Opus para tareas difíciles y el modelo por defecto para las rutinarias.
- Escribe la tarea completa y autosuficiente: qué hacer, qué no tocar, y que termine con un resumen de lo hecho y de lo que queda pendiente.
- `narrador trabajador lista` muestra su estado y el resultado. Para seguirlo turno a turno, `narrador seguir SESIÓN` en un Monitor.
- `narrador trabajador abrir NOMBRE` abre una terminal con esa sesión, para que el usuario la vea o la continúe.
- Si la carpeta no es de confianza, el trabajador va sin interfaz: lo que necesite permiso se le deniega y lo dirá en su resultado. Cuéntaselo al usuario y ofrécele abrirlo.

## Cuándo delegar

- **Pregunta rápida o un cambio pequeño:** hazlo tú.
- **Trabajo de varios pasos dentro de un proyecto:** lanza un trabajador y avisa al terminar.
- **El usuario ya tiene abierta una sesión en ese proyecto:** propón mandársela a esa sesión en vez de lanzar otra.
