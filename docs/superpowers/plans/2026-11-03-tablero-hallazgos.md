# Tablero de hallazgos: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir los hallazgos del parte matinal en tarjetas persistentes de un Kanban que el usuario mueve por voz o en una página web.

**Architecture:** `scripts/tablero.py` es lógica pura que compara el JSON del parte con las tarjetas y devuelve lotes de escritura. Ío lee y escribe esas tarjetas con `ArtifactData` en la `db` de una página Artifact. `parte_matinal.py` no se toca.

**Tech Stack:** Python 3 con biblioteca estándar, pytest, HTML y JS en un Artifact con capacidades `db` y `user`.

**Spec:** `docs/superpowers/specs/2026-11-03-tablero-hallazgos-design.md`

## Global Constraints

- Pruebas: `.runtime/venv-tests/bin/python -m pytest -q tests`.
- `tablero.py` no usa red ni lee `.env`. Solo importa de `parte_matinal` las constantes `PARTES` y `NOMBRE_CHECK`.
- Columnas exactas: `nuevos`, `en_curso`, `dejados`, `resueltos`. Marcas exactas: `null`, `automatica`, `reabierta`, `empeorada`. Orígenes exactos: `parte`, `voz`, `pagina`.
- `historial`: como mucho 20 movimientos. Lote: como mucho 50 escrituras.
- **Commits:** autorizados por el usuario el 2026-11-03 en la rama local `feat/tablero-hallazgos`, sin `push`. Cada uno añade únicamente los archivos citados. Nunca `git add -A`: `parte_matinal.py` y su prueba tienen cambios ajenos.
- Fechas: siempre la del parte (`compacto.fecha`), nunca el reloj.

## Review Focus

1. Parte antiguo (su fecha es anterior a alguna `ultima_vez`): no debe mover nada, porque resolvería tarjetas con datos viejos.
2. Documento de la `db` con columna desconocida o sin campos: se ignora con aviso y no tumba el parte.
3. Parte parcial con rojo sobre una tarjeta dejada de lado, seguido de un parte completo con rojo: la tarjeta debe volver como `empeorada`.
4. Más de 50 escrituras: se dividen en lotes, sin perder ninguna.
5. Carpeta de tarjetas inexistente: es un fallo (salida 3), no «no hay tarjetas», o se recrearía todo el tablero.

---

### Task 1: Reglas del tablero

**Files:**
- Create: `scripts/tablero.py`
- Test: `tests/test_tablero.py`

**Interfaces:**
- Produces:
  - `id_tarjeta(ambito: str, check: str) -> str`: devuelve `f"{ambito}--{check}"`, sustituyendo por `-` lo que no case con `[A-Za-z0-9_.~:@+-]`.
  - `ocultar(texto: str) -> str`: `[oculto]` en lugar de lo que parezca token; después trunca a 200 caracteres.
  - `agrupar(resultados: list[dict]) -> dict[tuple[str, str], dict]`: cada grupo es `{"ambito", "check", "situacion", "nivel", "valores"}`. `situacion` es `anomalia` (algún rojo o ámbar), `sin_comprobar` (si no, algún `na` o `error`) o `verde`. `nivel` es el peor, `rojo` o `ambar`, o `None`. `valores` usa `valor`, o si está vacío `detalle`, o si no `estado`, cada uno pasado por `ocultar`, solo de los resultados con anomalía.
  - `decidir(grupo: dict, tarjeta: dict | None, *, parcial: bool, hoy: str, modo: str = "plan", cliente: str = "global") -> dict | None`: campos que cambian, o `None`. Con `tarjeta=None`, el documento completo.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_id_sanea_caracteres(): assert id_tarjeta("a b", "tls") == "a-b--tls"
def test_oculta_token(): assert "sk-abc" not in ocultar("clave sk-abcdefghijklmnop123456")
def test_trunca_a_200(): assert len(ocultar("x " * 500)) <= 200
def test_agrupa_con_peor_nivel():  # dos resultados del mismo grupo: ambar + rojo -> nivel rojo, 2 valores
def test_valor_vacio_usa_detalle():  # valor "" y detalle "d" -> valores == ["d"]
def test_na_y_verde_es_sin_comprobar():  # situacion == "sin_comprobar"
```

Una prueba por cada fila de la tabla de transiciones de la especificación, con `parcial=False`:

```python
def test_crea_en_nuevos():  # columna nuevos, marca None, primera_vez == hoy, historial con de None y a nuevos
def test_en_curso_actualiza_sin_mover():  # "columna" not in cambios; detalle y ultima_vez cambian
def test_dejada_empeora_a_nuevos():  # nivel ambar + grupo rojo -> nuevos, marca empeorada
def test_dejada_ya_roja_no_empeora():  # nivel rojo + grupo rojo -> sin "columna"
def test_resuelta_reabre():  # columna nuevos, marca reabierta
def test_verde_resuelve_abierta():  # para nuevos, en_curso y dejados: resueltos, marca automatica
def test_verde_en_resueltos_no_cambia():  # None
def test_sin_comprobar_no_cambia():  # None en cualquier columna
```

Y además:

```python
def test_parcial_no_crea():  # tarjeta None -> None
def test_parcial_no_mueve_ni_toca_nivel():  # solo detalle y ultima_vez, aun con grupo rojo sobre dejada ámbar
def test_parcial_verde_no_resuelve():  # None
def test_parcial_y_completo_detecta_empeorar():  # aplicar parcial, luego completo: columna nuevos, marca empeorada
def test_idempotente():  # aplicar el resultado y decidir otra vez -> None
def test_historial_max_20():  # con 20 previos y un movimiento: 20, conserva el último
def test_semilla_env_en_dejados():  # modo="semilla", check env_permisos, tarjeta None -> columna dejados
def test_semilla_otro_en_nuevos():  # check chatwoot -> nuevos
def test_saldo_es_estimado():  # openai_saldo -> fiabilidad estimado; otro -> comprobado
```

- [ ] **Step 2: Ejecutar y comprobar que fallan**

Run: `.runtime/venv-tests/bin/python -m pytest -q tests/test_tablero.py`
Expected: FAIL por `ModuleNotFoundError: tablero`

- [ ] **Step 3: Implementar las cuatro funciones en `scripts/tablero.py`**

`titulo` sale de `NOMBRE_CHECK.get(check, check)`. Patrones de `ocultar`: `sk-`, `EAA` y cadenas de 32 o más caracteres alfanuméricos. Solo los cambios de `columna` añaden línea a `historial`, con origen `parte`.

- [ ] **Step 4: Ejecutar y comprobar que pasan**

Run: `.runtime/venv-tests/bin/python -m pytest -q tests/test_tablero.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/tablero.py tests/test_tablero.py
git commit -m "feat(tablero): reglas de transición de las tarjetas"
```

### Task 2: Plan de cambios y orden `narrador tablero`

**Files:**
- Modify: `scripts/tablero.py`, `bin/narrador` (rama `elif cmd == "tablero"` e import diferido, como `memoria`; línea de ayuda)
- Create: `tests/fixtures/parte_tablero.json`
- Test: `tests/test_tablero.py`

**Interfaces:**
- Consumes: `agrupar`, `decidir`, `id_tarjeta` de la Task 1.
- Produces:
  - `leer_tarjetas(directorio: Path) -> tuple[list[dict], list[str]]`: tarjetas válidas y avisos. Lanza `FileNotFoundError` si la carpeta no existe.
  - `planificar(parte: dict, tarjetas: list[dict], *, modo: str = "plan") -> dict`: devuelve `{"lotes", "semaforo", "voz", "sin_comprobar", "avisos"}`.
    - Cada escritura: `{"op": "set"|"update", "collection": "tarjetas", "doc_id", "data", "if_version"}`. `op` es `set` sin `if_version` al crear, y `update` con él al cambiar.
    - `voz`: `{"activas": [...], "dejadas": int}`. Cada activa lleva `id`, `cliente`, `titulo`, `nivel`, `valores`, `fiabilidad`, `marca`, `dias`, ordenadas de rojo a ámbar y de más a menos antigua.
    - `semaforo`: solo con `nuevos` y `en_curso` tras aplicar los cambios.
  - `main(args: list[str]) -> int`: subcomandos `plan` y `semilla`, `--tarjetas DIR`, `--parte ARCHIVO`. Salida 0, o 3 si falla. Por defecto, el parte es `PARTES / f"{fecha_de_hoy}.json"`.

- [ ] **Step 1: Crear la fixture**

`parte_tablero.json` copia la forma del parte real del 2026-11-03: `compacto.fecha`, `parcial`, `tenants` y `resultados`, con sus 13 anomalías, los 3 `na` y algunos verdes. Nombres de tenant ficticios (`cliente-a` a `cliente-e`, con `cliente-b-services` y su voz `cliente-b` para el caso de `loyal-services`), y `valor` inventados y sin IP: el repositorio puede subirse a GitHub.

- [ ] **Step 2: Escribir las pruebas que fallan**

```python
def test_semilla_real_da_7_y_5():  # sin tarjetas, modo semilla: 7 nuevos, 5 dejados, 12 escrituras
def test_semaforo_ignora_dejados():  # tarjetas rojas solo en dejados -> "verde"
def test_voz_activas_ordenadas_y_cifra_dejadas():
def test_sin_comprobar_lista_na_y_error():  # incluye chatwoot de eurotalent, correo y sonda
def test_cliente_usa_nombre_de_voz():  # loyal-services -> loyal; sin tenant -> global
def test_update_lleva_version_y_set_no():
def test_parte_antiguo_no_mueve():  # fecha anterior a una ultima_vez -> lotes vacíos y aviso
def test_tarjeta_invalida_se_ignora_con_aviso():  # columna "x" y JSON sin id
def test_mas_de_50_escrituras_en_lotes():  # 120 cambios -> lotes de 50, 50, 20
def test_grupo_ausente_no_cambia():
def test_main_sin_carpeta_sale_3(): 
def test_main_parte_ilegible_sale_3():
def test_main_imprime_json_valido():
```

- [ ] **Step 3: Ejecutar y comprobar que fallan**

Run: `.runtime/venv-tests/bin/python -m pytest -q tests/test_tablero.py`
Expected: FAIL por `planificar` no definido

- [ ] **Step 4: Implementar `leer_tarjetas`, `planificar`, `main` y la rama de `bin/narrador`**

Si la Task 3 demuestra que los archivos de `out_dir` guardan la versión en otro campo, solo cambia `leer_tarjetas`.

- [ ] **Step 5: Ejecutar toda la suite**

Run: `.runtime/venv-tests/bin/python -m pytest -q tests`
Expected: PASS, sin fallos nuevos

- [ ] **Step 6: Commit**

```bash
git add scripts/tablero.py tests/test_tablero.py tests/fixtures/parte_tablero.json bin/narrador
git commit -m "feat(tablero): plan de cambios y orden narrador tablero"
```

### Task 3: Página y carga inicial

**Files:**
- Create: `web/tablero.html`
- Memoria: nueva nota `referencias/tablero-hallazgos.md` con la URL, y su línea en `MEMORY.md`

**Interfaces:**
- Consumes: `narrador tablero semilla` y el modelo de datos de la especificación.
- Produces: la URL del Artifact.

- [ ] **Step 1: Preparar el diseño**

`Artifact` con `action: "quickstart"` e `intent: "other"`, y seguir lo que indique.

- [ ] **Step 2: Escribir la página**

Según las secciones «Página» y «Modelo de datos» de la especificación. Escribe `columna`, `marca: null` e `historial` con origen `pagina`, un documento cada vez. `onSnapshot` una sola vez. Aviso a los 10 s sin datos, y estado vacío explícito. El menú «Mover a…» debe funcionar con teclado y táctil. Los textos de las tarjetas se insertan con `textContent`.

- [ ] **Step 3: Publicar**

`capabilities: {db: {rules: [{path: "tarjetas", read: "view", write: "owner"}]}, user: {}}`. Guardar la URL en la nota de memoria.

- [ ] **Step 4: Comprobar la lectura real**

`ArtifactData list` de `tarjetas` con `out_dir` en el scratchpad. Si los archivos no incluyen `version`, ajustar `leer_tarjetas` con su prueba antes de seguir.

- [ ] **Step 5: Carga inicial con el parte del día**

`narrador tablero semilla --tarjetas <carpeta>` y `ArtifactData batch` con cada lote. **Si aparece una aprobación en pantalla:** decírselo al usuario y proponerle una regla de permisos, sin añadirla sin su visto bueno.

- [ ] **Step 6: Verificar**

`ArtifactData list` debe coincidir con el `semilla` del paso anterior. Repetir la lectura con `as_level: "view"` y comprobar que una escritura a ese nivel es rechazada. Mover una tarjeta con una escritura `update` y devolverla a su sitio. Decirle al usuario qué se ha probado y pedirle que pruebe el arrastre y el menú si no se pudieron ejercitar.

- [ ] **Step 7: Retirar la nota antigua**

Mover `decisiones/2026-11-03-env-permisos-644-archivado.md` a `_archivo/`, quitar su línea de `MEMORY.md` y ejecutar `narrador memoria indices`.

- [ ] **Step 8: Commit**

```bash
git add web/tablero.html
git commit -m "feat(tablero): página Kanban"
```

### Task 4: Voz y flujo del parte

**Files:**
- Create: `skills/io-tablero/SKILL.md`
- Modify: `skills/io-parte-matinal/SKILL.md` (Flujo, Formato de voz), `agents/io.md` (lista de skills y tabla de guías), `README.md` (línea del árbol y una frase)
- Test: `tests/test_tablero.py`

**Interfaces:**
- Consumes: `narrador tablero plan`, la URL de la nota `referencias/tablero-hallazgos.md`.

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_skill_tablero_cubre_limites():  # el texto contiene "[voz-equipo]", "if_version", "deshaz" y "producción"
def test_parte_matinal_usa_tablero():  # el texto contiene "narrador tablero plan" y "resumen_voz"
```

- [ ] **Step 2: Ejecutar y comprobar que falla**

Run: `.runtime/venv-tests/bin/python -m pytest -q tests/test_tablero.py -k skill`
Expected: FAIL

- [ ] **Step 3: Escribir `io-tablero`**

La descripción debe activarse con «pon en curso», «deja de lado», «retoma», «da por resuelto», «deshaz» y «qué tengo en curso». Contenido: la tabla de la sección «Voz» de la especificación; pasos (leer, elegir tarjeta, `update` con `if_version` y origen `voz`, repetir el cambio); si encaja más de una, preguntar; los límites de seguridad; y qué hacer ante un fallo.

- [ ] **Step 4: Cambiar `io-parte-matinal`**

Sustituir el flujo por los pasos de «Flujo del parte» y la tabla de «Errores» de la especificación. El fallback sin tablero es `resumen_voz`, y `estimado` se dice como tal.

- [ ] **Step 5: Ejecutar toda la suite**

Run: `.runtime/venv-tests/bin/python -m pytest -q tests`
Expected: PASS. Además, `narrador guia tablero` imprime la guía.

- [ ] **Step 6: Commit**

```bash
git add skills/io-tablero/SKILL.md skills/io-parte-matinal/SKILL.md agents/io.md README.md tests/test_tablero.py
git commit -m "feat(tablero): órdenes por voz y flujo del parte"
```

### Task 5: Prueba real

**Files:** ninguno, salvo los arreglos que salgan, con su prueba.

- [ ] **Step 1: Parte real con el tablero**

`narrador parte --json --forzar`, seguido del flujo nuevo. Comparar a mano con `narrador parte`: todo rojo o ámbar debe estar en una tarjeta, y todo `na` o `error` en «sin comprobar».

- [ ] **Step 2: Repetir sin cambios**

Volver a aplicar el mismo parte. Los lotes deben salir vacíos.

- [ ] **Step 3: Ensayo por voz con el usuario**

Una orden de cada tipo de la tabla: mover, una ambigua, deshaz y consulta. Después, el usuario comprueba la página.

- [ ] **Step 4: Cierre**

`narrador memoria indices` y `narrador memoria guardar "cierre: tablero de hallazgos"`. Actualizar `ram.md`.
