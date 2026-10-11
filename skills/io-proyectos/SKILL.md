---
name: io-proyectos
description: Encontrar un proyecto del usuario (thereisnospoon, greedisgood) y ver su estado, rama y cambios. Úsala cuando mencione «el proyecto de X» o pida abrir o revisar uno.
---

# Guía: proyectos

- `narrador proyectos` lista los proyectos de `~/Documentos/thereisnospoon` y `~/Documentos/greedisgood`, del más reciente al más antiguo, con su rama y su última sesión. `--git` añade los cambios sin confirmar y `--todos` quita el límite de 25.
- Para resolver «el proyecto de X», usa esta lista. Si hay varias coincidencias, pregunta cuál en una línea de voz.
- **Antes de opinar sobre un proyecto**, lee su `CLAUDE.md` y su `README` si existen. No inventes cómo está montado.
- **Abrirlo en VS Code**: `code RUTA`.
- **Estado de git**: `git -C RUTA status` y `git -C RUTA log --oneline -5`.
- Trabajo de verdad dentro de un proyecto: delégalo en un trabajador (guía `sesiones`).
- **Subir cambios**: solo si el usuario lo pide expresamente en ese momento, nunca por iniciativa propia.
