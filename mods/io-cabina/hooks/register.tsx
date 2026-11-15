import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderChildren, ToolCallResult } from 'claude-code'

import type {
  Alerta,
  Espera,
  MetaTablero,
  Parte,
  ProyectoRoadmap,
  Puerta,
  Sesion,
  TarjetaTablero,
  Trabajo,
  TrabajadorVivo,
} from '../types'

const PANE = 'cabina'
const PANE_ROADMAP = 'roadmap'
const ROADMAP_CADA_MS = 20000
const PANE_TABLERO = 'tablero'
const TABLERO_CADA_MS = 20000
const HOME = '/home/seppuq'
const NARR = `${HOME}/.local/share/narrador`
const CAB = `${NARR}/cabina`
const RAM = `${HOME}/.claude/agent-memory/narrador-io/ram.md`
const CADA_MS = 8000
// La orden `narrador` del mismo checkout que el mod (mods/io-cabina → ../../bin/narrador): así el mod
// y sus órdenes van siempre de la mano. La fija `ubicarNarrador` al arrancar; esta es la de reserva.
const NARRADOR_DEFECTO = `${HOME}/Documentos/thereisnospoon/io-assistant/bin/narrador`
let NARRADOR = NARRADOR_DEFECTO
const IO_JSON = `${NARR}/io.json`
const TRABAJADORES = `${NARR}/trabajadores.json`
const PANE_PUERTAS = 'puertas'
// Solo la sesión de Ío (la de io.json) registra herramientas y le pasa respuestas de puertas.
let esIo = false
const ENTORNO = { PATH: `${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin`, HOME }

const sesiones = atom({ plugin: 'io-cabina', key: 'sesiones' } as const, [], {
  shape: 'sesiones-1',
})
const esperas = atom({ plugin: 'io-cabina', key: 'esperas' } as const, [], {
  shape: 'esperas-1',
})
const alertas = atom({ plugin: 'io-cabina', key: 'alertas' } as const, [], {
  shape: 'alertas-1',
})
const trabajos = atom({ plugin: 'io-cabina', key: 'trabajos' } as const, [], {
  shape: 'trabajos-1',
})
const pendientes = atom({ plugin: 'io-cabina', key: 'pendientes' } as const, [], {
  shape: 'pendientes-1',
})
const parte = atom({ plugin: 'io-cabina', key: 'parte' } as const, null, {
  shape: 'parte-1',
})
const actualizado = atom({ plugin: 'io-cabina', key: 'actualizado' } as const, 0)
const fallo = atom({ plugin: 'io-cabina', key: 'fallo' } as const, '')
const roadmap = atom({ plugin: 'io-cabina', key: 'roadmap' } as const, [], {
  shape: 'roadmap-1',
})
const roadmapCuando = atom({ plugin: 'io-cabina', key: 'roadmapCuando' } as const, 0)
const roadmapFallo = atom({ plugin: 'io-cabina', key: 'roadmapFallo' } as const, '')
// De dónde sale el proyecto: «sesión X · ruta» si sigue a la sesión activa, o el fijado a mano.
const roadmapOrigen = atom({ plugin: 'io-cabina', key: 'roadmapOrigen' } as const, '')
// Proyecto fijado con `/roadmap NOMBRE`; vacío = seguir a la sesión activa.
const roadmapFijo = atom({ plugin: 'io-cabina', key: 'roadmapFijo' } as const, '')
// Tablero de hallazgos: las tarjetas viven en ~/.local/share/narrador/tablero.json y solo se
// leen y se mueven con `narrador tablero`; el mod nunca toca el archivo.
const META_VACIA: MetaTablero = { existe: true, parteFecha: '', semaforo: '', puedeDeshacer: false, invalidas: 0 }
const tablero = atom({ plugin: 'io-cabina', key: 'tablero' } as const, [], {
  shape: 'tablero-1',
})
const tableroMeta = atom({ plugin: 'io-cabina', key: 'tableroMeta' } as const, META_VACIA, {
  shape: 'tablero-meta-1',
})
const tableroCuando = atom({ plugin: 'io-cabina', key: 'tableroCuando' } as const, 0)
const tableroFallo = atom({ plugin: 'io-cabina', key: 'tableroFallo' } as const, '')
// Id de la tarjeta desplegada (la que mueven los atajos); vacío = ninguna.
const tableroSel = atom({ plugin: 'io-cabina', key: 'tableroSel' } as const, '')

// Puertas: viven en ~/.local/share/narrador/puertas.json y solo se tocan con `narrador puerta`.
const puertas = atom({ plugin: 'io-cabina', key: 'puertas' } as const, [], { shape: 'puertas-1' })
const puertasFallo = atom({ plugin: 'io-cabina', key: 'puertasFallo' } as const, '')
// Trabajadores en marcha (para la franja) y gasto de esta sesión, si el motor lo lleva.
const vivos = atom({ plugin: 'io-cabina', key: 'vivos' } as const, [], { shape: 'vivos-2' })
const gasto = atom({ plugin: 'io-cabina', key: 'gasto' } as const, null)

// Paleta a juego con la terminal de Ío (violeta del prompt sobre fondo oscuro).
// Paleta vinotinto: fondo vino oscuro, acentos rosa pálido y dorado, estados legibles sobre vino.
const FONDO = '#140509'
const ACENTO = '#f2b8c2'
const DORADO = '#e2b86b'
const TENUE = '#a8848c'
const MARCO = '#4a1a26'
const ROJO = '#ff7a7a'
const VERDE = '#9fd4a3'
const AMBAR = '#f0c060'

// Salida de `narrador sesiones --vivas`: una línea por sesión
// («nombre  estado  tipo  ruta», el estado a veces con su motivo: «blocked (permission)») y debajo
// «sesión ID  «título»».
function leerSesiones(texto: string): Sesion[] {
  const salida: Sesion[] = []
  for (const linea of texto.split('\n')) {
    const cabecera = /^(\S.*?)\s{2,}(\w+)(?:\s+\([^)]*\))?\s{2,}(\w+)\s{2,}(.+)$/.exec(linea)
    if (cabecera) {
      salida.push({
        nombre: cabecera[1] ?? '',
        estado: cabecera[2] ?? '',
        tipo: cabecera[3] ?? '',
        cwd: (cabecera[4] ?? '').trim(),
        id: '',
      })
      continue
    }
    const detalle = /^\s+sesión\s+(\S+)/.exec(linea)
    const previa = salida[salida.length - 1]
    if (detalle && previa) {
      previa.id = detalle[1] ?? ''
    }
  }
  return salida
}

// `narrador permisos --json`: lista de sesiones que esperan un permiso.
function leerEsperas(texto: string): Espera[] {
  try {
    const datos = JSON.parse(texto)
    if (!Array.isArray(datos)) return []
    return datos.map((d: Record<string, unknown>) => ({
      nombre: String(d.nombre ?? d.sesion ?? d.session ?? d.id ?? '?'),
      detalle: String(d.herramienta ?? d.tool ?? d.detalle ?? 'espera un permiso'),
    }))
  } catch {
    return []
  }
}

// alertas.jsonl: una línea por alerta; una línea {id, hecha: true} la resuelve.
function leerAlertas(texto: string): Alerta[] {
  const porId = new Map<string, Alerta>()
  for (const linea of texto.split('\n')) {
    if (!linea.trim()) continue
    try {
      const d = JSON.parse(linea)
      if (d.hecha) {
        porId.delete(String(d.id))
      } else {
        porId.set(String(d.id), {
          id: String(d.id),
          ts: Number(d.ts ?? 0),
          nivel: String(d.nivel ?? 'info'),
          texto: String(d.texto ?? ''),
          fuente: String(d.fuente ?? ''),
        })
      }
    } catch {
      // línea rota: se ignora
    }
  }
  return [...porId.values()].sort((a, b) => b.ts - a.ts).slice(0, 12)
}

function leerTrabajos(texto: string): Trabajo[] {
  try {
    const datos = JSON.parse(texto)
    return Array.isArray(datos)
      ? datos.map((d: Record<string, unknown>) => ({
          nombre: String(d.nombre ?? '?'),
          estado: String(d.estado ?? ''),
          detalle: String(d.detalle ?? ''),
        }))
      : []
  } catch {
    return []
  }
}

// Sección «## Pendiente» de la RAM de Ío.
function leerPendientes(texto: string): string[] {
  const salida: string[] = []
  let dentro = false
  for (const linea of texto.split('\n')) {
    if (linea.startsWith('## ')) {
      dentro = linea.trim().toLowerCase() === '## pendiente'
      continue
    }
    if (dentro && linea.startsWith('- ')) salida.push(linea.slice(2).trim())
  }
  return salida.slice(0, 6)
}

// `narrador roadmap --json`: {proyectos: [{nombre, error, semaforo, deriva_texto, medido, estimado}]}.
type Dic = Record<string, unknown>
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string => (typeof v === 'string' ? v : v == null ? '' : String(v))

function leerRoadmap(texto: string): ProyectoRoadmap[] {
  const datos = JSON.parse(texto) as Dic
  const lista = Array.isArray(datos.proyectos) ? (datos.proyectos as Dic[]) : []
  return lista.map(p => {
    const m = (p.medido ?? {}) as Dic
    const e = (p.estimado ?? {}) as Dic
    return {
      nombre: str(p.nombre) || '?',
      error: str(p.error),
      semaforo: str(p.semaforo),
      deriva: str(p.deriva_texto),
      hechos: num(m.hitos_hechos) ?? 0,
      total: num(m.hitos_total) ?? 0,
      pct: num(m.avance_pct),
      prevista: str(e.fecha_prevista),
      confianza: str(e.confianza),
      ritmo: num(e.ritmo_hitos_semana),
      restantes: num(e.hitos_restantes) ?? 0,
      motivo: str(e.motivo),
      siguiente: str(m.siguiente),
      siguienteFase: str(m.siguiente_fase),
      responsable: str(m.responsable),
      ultimo: str(m.ultimo_movimiento),
      diasSinTocar: num(m.dias_sin_tocar),
      commits4s: num(m.commits_4_semanas),
      sinCommit: num(m.cambios_sin_commit),
      avisos: Array.isArray(p.avisos) ? p.avisos.length : 0,
      listaAvisos: Array.isArray(p.avisos) ? (p.avisos as unknown[]).map(str) : [],
      objetivo: str(m.fecha_objetivo),
      desfase: num(e.desfase_dias),
      ritmoHist: num(e.ritmo_historico_semana),
      semanasRest: num(e.semanas_restantes),
      commitsTotal: num(m.commits_total),
      cierres: Array.isArray(m.cierres_4_semanas)
        ? (m.cierres_4_semanas as Dic[]).map(c => `${str(c.nota)} (${str(c.cerrado)})`)
        : [],
      fases: Array.isArray(p.notas)
        ? (p.notas as Dic[]).map(n => ({
            nota: str(n.nota),
            fase: str(n.fase),
            estado: str(n.estado),
            hechos: num(n.hitos_hechos) ?? 0,
            total: num(n.hitos_total) ?? 0,
            inicio: str(n.inicio),
            objetivo: str(n.objetivo),
            cerrado: str(n.cerrado),
            responsable: str(n.responsable),
            siguiente: str(n.siguiente),
            pendientes: Array.isArray(n.pendientes) ? (n.pendientes as unknown[]).map(str) : [],
          }))
        : [],
    }
  })
}

// Las cuatro columnas del tablero, en orden; `accion` es el botón que mueve ahí y `tecla` su atajo.
const COLUMNAS_TABLERO = [
  { id: 'nuevos', titulo: 'Nuevos', nombre: 'nuevos', accion: 'a nuevos', tecla: 'n' },
  { id: 'en_curso', titulo: 'En curso', nombre: 'en curso', accion: 'en curso', tecla: 'c' },
  { id: 'dejados', titulo: 'Dejados de lado', nombre: 'dejados de lado', accion: 'dejar de lado', tecla: 'd' },
  { id: 'resueltos', titulo: 'Resueltos', nombre: 'resueltos', accion: 'resolver', tecla: 'r' },
] as const
const RESUELTOS_VISIBLES = 5
const nombreColumna = (id: string) => COLUMNAS_TABLERO.find(c => c.id === id)?.nombre ?? id

// `narrador tablero ver|mover|deshacer`: {existe, parte_fecha, semaforo, puede_deshacer, tarjetas, avisos, deshecho?}.
function leerTablero(texto: string): { tarjetas: TarjetaTablero[]; meta: MetaTablero; deshecho: string } {
  const crudo = JSON.parse(texto) as unknown
  const datos = (crudo && typeof crudo === 'object' && !Array.isArray(crudo) ? crudo : {}) as Dic
  const lista = Array.isArray(datos.tarjetas) ? (datos.tarjetas as Dic[]) : []
  const tarjetas = lista.map(t => {
    const historial = Array.isArray(t.historial) ? (t.historial as Dic[]) : []
    const h = historial[historial.length - 1]
    return {
      id: str(t.id),
      cliente: str(t.cliente) || 'global',
      titulo: str(t.titulo) || str(t.check),
      nivel: str(t.nivel),
      detalle: Array.isArray(t.detalle) ? (t.detalle as unknown[]).map(str) : [],
      columna: str(t.columna),
      marca: str(t.marca),
      fiabilidad: str(t.fiabilidad),
      primera: str(t.primera_vez),
      ultima: str(t.ultima_vez),
      movimiento: h
        ? `${str(h.fecha)} · ${h.de ? `${nombreColumna(str(h.de))} → ` : ''}${nombreColumna(str(h.a))} (${str(h.origen)})`
        : '',
    }
  })
  const d = datos.deshecho as Dic | undefined
  return {
    tarjetas,
    meta: {
      existe: datos.existe === true,
      parteFecha: str(datos.parte_fecha),
      semaforo: str(datos.semaforo),
      puedeDeshacer: datos.puede_deshacer === true,
      invalidas: Array.isArray(datos.avisos) ? datos.avisos.length : 0,
    },
    deshecho: d ? `${str(d.cliente)} · ${str(d.titulo)} vuelve a ${nombreColumna(str(d.a))}` : '',
  }
}

// Rojo antes que ámbar y, dentro, por cliente: cada cliente queda junto y no se mezcla con otro.
const ordenTablero = (a: TarjetaTablero, b: TarjetaTablero) =>
  Number(a.nivel !== 'rojo') - Number(b.nivel !== 'rojo') || a.cliente.localeCompare(b.cliente) || a.id.localeCompare(b.id)

const barra = (hechos: number, total: number, ancho = 24) => {
  const llenos = total > 0 ? Math.round((hechos / total) * ancho) : 0
  return { llena: '█'.repeat(llenos), vacia: '░'.repeat(ancho - llenos) }
}

const colorDeriva = (s: string) =>
  s === 'rojo' ? ROJO : s === 'ambar' ? AMBAR : s === 'verde' ? VERDE : TENUE

const cortar = (texto: string, largo: number) =>
  texto.length > largo ? `${texto.slice(0, largo - 1)}…` : texto

const ultimo = (ruta: string) => ruta.split('/').filter(Boolean).pop() ?? ruta

// Proyecto de una carpeta: el primer nivel bajo una de las raíces («~/Documentos/greedisgood/vindam
// platform/x/.claude/worktrees/y» → «vindam platform»). Fuera de las raíces, '' (el grupo «otros»).
const RAICES_PROYECTO = ['~/Documentos/greedisgood/', '~/Documentos/thereisnospoon/']
const proyectoDe = (cwd: string) => {
  const ruta = cwd === HOME || cwd.startsWith(`${HOME}/`) ? `~${cwd.slice(HOME.length)}` : cwd
  for (const raiz of RAICES_PROYECTO) {
    if (ruta.startsWith(raiz)) return ruta.slice(raiz.length).split('/')[0] ?? ''
  }
  return ''
}

// Lo que se ve de la carpeta dentro de su proyecto: nada en la raíz, «⎇ nombre» en un worktree y la
// última carpeta en cualquier otra subcarpeta. Fuera de las raíces, la última carpeta.
const dondeEn = (cwd: string, proyecto: string) => {
  const arbol = /\/\.claude\/worktrees\/([^/]+)/.exec(cwd)
  if (arbol) return `⎇ ${arbol[1]}`
  const fin = ultimo(cwd)
  return proyecto !== '' && fin === proyecto ? '' : fin
}

// La sesión de Ío: la lanza `bin/io` con `--name Ío` (desde ella se ve «Ío (esta)»).
const esSesionIo = (s: Sesion) => /^Ío( \(esta\))?$/.test(s.nombre)

type GrupoSesiones = {
  clave: string
  titulo: string
  sesiones: Sesion[]
  // Bloqueadas o con un permiso pendiente: lo que espera al usuario.
  esperan: number
  // Trabajadores sin interfaz (sin sesión en la lista) que corren en este proyecto.
  sueltos: TrabajadorVivo[]
  actividad: number
}

const RANGO_ESTADO: Record<string, number> = { blocked: 0, busy: 1, idle: 2 }

// Agrupa las sesiones vivas por proyecto, con la de Ío aparte. Orden: primero los grupos con algo
// esperando al usuario, luego por actividad reciente (cuándo se vio por última vez una sesión
// ocupada), luego por sesiones ocupadas y por nombre; «otros» siempre al final.
function agruparSesiones(
  vivas: Sesion[],
  espera: Espera[],
  enMarcha: TrabajadorVivo[],
  actividad: ReadonlyMap<string, number>,
): { io: Sesion[]; grupos: GrupoSesiones[] } {
  const io = vivas.filter(esSesionIo)
  const porClave = new Map<string, GrupoSesiones>()
  const grupo = (clave: string) => {
    let g = porClave.get(clave)
    if (!g) {
      g = { clave, titulo: clave || 'otros', sesiones: [], esperan: 0, sueltos: [], actividad: actividad.get(clave) ?? 0 }
      porClave.set(clave, g)
    }
    return g
  }
  const pide = new Set(espera.map(x => x.nombre))
  for (const s of vivas) {
    if (esSesionIo(s)) continue
    const g = grupo(proyectoDe(s.cwd))
    g.sesiones.push(s)
    if (s.estado === 'blocked' || pide.has(s.nombre) || (s.id !== '' && pide.has(s.id))) g.esperan += 1
  }
  const conSesion = new Set(vivas.map(s => s.nombre.replace(/ \(esta\)$/, '')))
  for (const t of enMarcha) {
    if (conSesion.has(t.nombre) || !t.ruta) continue
    grupo(proyectoDe(t.ruta)).sueltos.push(t)
  }
  const grupos = [...porClave.values()]
  for (const g of grupos) {
    g.sesiones.sort((a, b) => (RANGO_ESTADO[a.estado] ?? 3) - (RANGO_ESTADO[b.estado] ?? 3) || a.nombre.localeCompare(b.nombre))
  }
  const ocupadas = (g: GrupoSesiones) => g.sesiones.filter(s => s.estado === 'busy').length + g.sueltos.length
  grupos.sort(
    (a, b) =>
      Number(a.clave === '') - Number(b.clave === '') ||
      Number(b.esperan > 0) - Number(a.esperan > 0) ||
      b.actividad - a.actividad ||
      ocupadas(b) - ocupadas(a) ||
      a.titulo.localeCompare(b.titulo),
  )
  return { io, grupos }
}

const hora = (ms: number) => {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const colorSemaforo = (s: string) =>
  s === 'rojo' ? ROJO : s === 'ambar' ? AMBAR : s === 'verde' ? VERDE : undefined

const colorEstado = (s: string) =>
  s === 'blocked' ? ROJO : s === 'busy' ? AMBAR : s === 'idle' ? VERDE : undefined

const colorNivel = (n: string) =>
  n === 'rojo' ? ROJO : n === 'ambar' ? AMBAR : undefined

// `narrador puerta lista --json`: {puertas: [...]}, abiertas y respondidas sin cerrar.
function leerPuertas(texto: string): Puerta[] {
  try {
    const datos = JSON.parse(texto) as Dic
    const lista = datos && Array.isArray(datos.puertas) ? (datos.puertas as Dic[]) : []
    return lista.map(p => ({
      id: str(p.id),
      titulo: str(p.titulo),
      comando: str(p.comando),
      coste: str(p.coste),
      vuelta: str(p.vuelta),
      proyecto: str(p.proyecto),
      estado: str(p.estado),
      creada: str(p.creada),
      respondida: str(p.respondida),
      origen: str(p.origen),
    }))
  } catch {
    return []
  }
}

// trabajadores.json: lo lanzado en las últimas 24 h, lo más reciente primero (12 como mucho).
type Lanzado = { nombre: string; tarea: string; ruta: string; tipo: string; log: string; contrato: boolean }
function leerLanzados(texto: string, ahoraMs: number): Lanzado[] {
  try {
    const datos = JSON.parse(texto) as unknown
    if (!Array.isArray(datos)) return []
    return (datos as Dic[])
      .filter(t => typeof t.inicio === 'number' && ahoraMs - t.inicio * 1000 < 24 * 3600 * 1000)
      .slice(-12)
      .reverse()
      .map(t => ({
        nombre: str(t.nombre),
        tarea: str(t.tarea),
        ruta: str(t.ruta),
        tipo: str(t.tipo),
        log: str(t.log),
        contrato: t.contrato === true,
      }))
  } catch {
    return []
  }
}

// El id corto del final del nombre (io-motor-k7q → k7q); los nombres viejos, enteros.
const idTrabajador = (nombre: string) => /-([a-z0-9]{3})$/.exec(nombre)?.[1] ?? nombre

const dolares = (usd: number) => `${usd.toFixed(2).replace('.', ',')} $`

// --- funciones al principio del archivo, porque reciben `$` ---
async function ubicarNarrador($: EngineInterface) {
  try {
    const raiz = (await $.fs.stat($.plugin.root, { resolve: true })).realPath ?? $.plugin.root
    const m = /^(.*)\/mods\/[^/]+\/?$/.exec(raiz)
    if (!m) return
    const candidata = `${m[1]}/bin/narrador`
    if ((await $.fs.stat(candidata)).kind === 'file') NARRADOR = candidata
  } catch {
    // se queda la de reserva
  }
}

async function esSesionDeIo($: EngineInterface): Promise<boolean> {
  try {
    const datos = JSON.parse(await $.fs.read(IO_JSON)) as Dic
    return str(datos.session_id) !== '' && str(datos.session_id) === (await $.session.id())
  } catch {
    return false
  }
}

// Un tono corto. `narrador tono` respeta el silencio, la pausa de escucha y no pisa una locución;
// `$.audio.play` no suena en una terminal de Linux, por eso no se usa.
function sonar($: EngineInterface, nombre: 'terminado' | 'puerta' | 'error') {
  void $.process.run([NARRADOR, 'tono', nombre], { timeoutMs: 20000, env: ENTORNO }).catch(() => undefined)
}

// Trabajadores que siguen en marcha: de fondo, si `claude agents` no los da libres; sin interfaz,
// si su log se ha movido en los últimos dos minutos. Con el informe del contrato escrito, ya terminó.
async function trabajadoresVivos($: EngineInterface, lanzados: Lanzado[], vivas: Sesion[], ahoraMs: number) {
  const salida: TrabajadorVivo[] = []
  for (const t of lanzados) {
    if (t.contrato) {
      const informe = await $.fs.stat(`${NARR}/trabajadores/${t.nombre}.md`).catch(() => undefined)
      if (informe && informe.size > 0) continue
    }
    let enMarcha = false
    if (t.tipo === 'bg') {
      const s = vivas.find(v => v.nombre === t.nombre || v.nombre.startsWith(`${t.nombre} `))
      enMarcha = s !== undefined && s.estado !== 'idle'
    } else if (t.tipo === 'p' && t.log) {
      const log = await $.fs.stat(t.log).catch(() => undefined)
      enMarcha = log !== undefined && ahoraMs - log.mtimeMs < 120000
    }
    if (enMarcha) salida.push({ id: idTrabajador(t.nombre), nombre: t.nombre, tarea: t.tarea, proyecto: ultimo(t.ruta), ruta: t.ruta })
  }
  return salida
}

async function sondearPuertas($: EngineInterface): Promise<Puerta[] | null> {
  try {
    const r = await $.process.run([NARRADOR, 'puerta', 'lista', '--json'], { timeoutMs: 15000, env: ENTORNO })
    if (r.exitCode !== 0) throw new Error(`narrador puerta salió con ${r.exitCode}: ${cortar(r.stderr.trim(), 160)}`)
    const lista = leerPuertas(r.stdout)
    await update($, puertas, () => lista)
    await update($, puertasFallo, () => '')
    return lista
  } catch (error) {
    // lo que ya se veía se queda
    await update($, puertasFallo, () => String(error)).catch(() => undefined)
    return null
  }
}

// «Sí» o «No» en la cabina: lo anota `narrador puerta responder` y se lo pasa a Ío como un mensaje
// del mod ($.prompt.submit: entra como un turno nuevo cuando Ío está libre). Nunca ejecuta el comando.
async function responderPuerta($: EngineInterface, p: Puerta, respuesta: 'si' | 'no') {
  const dicho = respuesta === 'si' ? 'sí' : 'no'
  try {
    const r = await $.process.run([NARRADOR, 'puerta', 'responder', p.id, respuesta, '--origen', 'cabina'], {
      timeoutMs: 15000,
      env: ENTORNO,
    })
    if (r.exitCode === 0) {
      const aviso = r.stdout.trim()
      if (esIo && aviso) {
        await $.prompt.submit({ text: aviso })
        $.ui.toast(cortar(`Anotado: ${dicho} a «${p.titulo}». Se lo paso a Ío; la cabina no ejecuta nada.`, 140), {
          timeoutMs: 6000,
        })
      } else {
        $.ui.toast(cortar(`Anotado: ${dicho} a «${p.titulo}» (narrador puerta lista).`, 140), { timeoutMs: 6000 })
      }
    } else {
      $.ui.toast(
        r.exitCode === 4
          ? 'Esa puerta ya tenía respuesta; vuelvo a leerlas.'
          : cortar(r.stderr.trim() || `narrador puerta salió con ${r.exitCode}`, 140),
        { timeoutMs: 6000 },
      )
    }
  } catch (error) {
    $.ui.toast(cortar(`no pude anotar la respuesta: ${String(error)}`, 140), { timeoutMs: 6000 })
  }
  await sondearPuertas($)
}

async function abrirPuertas($: EngineInterface, columnas: number | undefined, foco: boolean) {
  return $.ui.open({
    id: PANE_PUERTAS,
    title: 'Puertas',
    backgroundColor: FONDO,
    columns: columnas,
    ...(foco ? { focus: true as const } : {}),
  })
}

// --- herramientas para Ío: llaman a `narrador` y devuelven texto corto ---
// trabajador_esperar no está: bloquearía el turno de Ío (y su oído) hasta 30 min. Sigue con Monitor.
type Entrada = Record<string, unknown>
type Herramienta = {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  argv: (e: Entrada) => string[]
  timeoutMs: number
  despues?: (salida: string) => string
}
const VACIO = { type: 'object', properties: {} }
const HERRAMIENTAS: Herramienta[] = [
  {
    name: 'trabajador_lanzar',
    description:
      'Lanza un trabajador (una sesión de Claude Code en segundo plano) en otro proyecto con una tarea autosuficiente; igual que `narrador trabajador lanzar`. Después, vigílalo con un Monitor sobre `narrador trabajador esperar NOMBRE`.',
    inputSchema: {
      type: 'object',
      properties: {
        proyecto: { type: 'string', description: 'Nombre o ruta del proyecto (como en narrador proyectos).' },
        tarea: { type: 'string', description: 'El encargo completo: qué hacer, qué no tocar, qué leer y sus puertas.' },
        modelo: { type: 'string', description: 'Modelo (p. ej. opus para lo difícil); vacío, el de por defecto.' },
        contrato: { type: 'boolean', description: 'Añade el contrato (límites e informe en tres listas). Por defecto, sí.' },
      },
      required: ['proyecto', 'tarea'],
    },
    argv: e => [
      'trabajador',
      'lanzar',
      str(e.proyecto),
      str(e.tarea),
      ...(str(e.modelo) ? ['--modelo', str(e.modelo)] : []),
      ...(e.contrato === false ? [] : ['--contrato']),
    ],
    timeoutMs: 120000,
    despues: salida => {
      const nombre = /trabajador (\S+) lanzado/.exec(salida)?.[1]
      return nombre
        ? `${salida}\nVigílalo ya: Monitor con \`narrador trabajador esperar ${nombre}\`, descripción «fin del trabajador ${nombre}», timeout_ms 1800000.`
        : salida
    },
  },
  {
    name: 'trabajador_lista',
    description: 'Los últimos trabajadores lanzados: estado, tarea y resumen del informe; igual que `narrador trabajador lista`.',
    inputSchema: VACIO,
    argv: () => ['trabajador', 'lista'],
    timeoutMs: 60000,
  },
  {
    name: 'permisos',
    description: 'Qué sesiones esperan algo del usuario (un permiso, una respuesta) y en qué carpeta; igual que `narrador permisos`.',
    inputSchema: VACIO,
    argv: () => ['permisos'],
    timeoutMs: 45000,
  },
  {
    name: 'sesiones_vivas',
    description: 'Las sesiones de Claude Code abiertas ahora: nombre, estado, tipo, carpeta y título; igual que `narrador sesiones --vivas`.',
    inputSchema: VACIO,
    argv: () => ['sesiones', '--vivas'],
    timeoutMs: 45000,
  },
  {
    name: 'puerta_anadir',
    description:
      'Registra una puerta (push, gasto, producción, envío…) para que la cabina la enseñe con botones Sí y No; pregúntala además con AskUserQuestion. Un sí solo se anota: el comando lo ejecutas tú y luego cierras la puerta con `narrador puerta cerrar ID`.',
    inputSchema: {
      type: 'object',
      properties: {
        titulo: { type: 'string', description: 'Qué se va a hacer, en pocas palabras.' },
        comando: { type: 'string', description: 'El comando exacto, ya preparado.' },
        coste: { type: 'string', description: 'Coste o presupuesto, si lo hay.' },
        vuelta: { type: 'string', description: 'Cómo se deshace, si se puede.' },
        proyecto: { type: 'string', description: 'Proyecto al que afecta.' },
      },
      required: ['titulo', 'comando'],
    },
    argv: e => [
      'puerta',
      'añadir',
      str(e.titulo),
      '--comando',
      str(e.comando),
      ...(str(e.coste) ? ['--coste', str(e.coste)] : []),
      ...(str(e.vuelta) ? ['--vuelta', str(e.vuelta)] : []),
      ...(str(e.proyecto) ? ['--proyecto', str(e.proyecto)] : []),
    ],
    timeoutMs: 15000,
    despues: salida =>
      `Puerta ${salida} registrada: sale en la cabina con Sí y No. Pregúntala también con AskUserQuestion; si responde por ahí, anótalo con \`narrador puerta responder ${salida} si|no --origen voz\`.`,
  },
]

async function registrarHerramientas($: EngineInterface) {
  for (const h of HERRAMIENTAS) {
    await $.tool.register({ name: h.name, description: h.description, inputSchema: h.inputSchema, isDeferred: false })
  }
}

async function usarHerramienta($: EngineInterface, nombre: string, e: Entrada): Promise<ToolCallResult> {
  const h = HERRAMIENTAS.find(x => x.name === nombre)
  if (!h || !esIo) return { deny: 'Estas herramientas son solo de la sesión de Ío.' }
  try {
    const r = await $.process.run([NARRADOR, ...h.argv(e)], { timeoutMs: h.timeoutMs, env: ENTORNO })
    const salida = cortar((r.stdout.trim() || r.stderr.trim() || '(sin salida)').replaceAll(HOME, '~'), 3000)
    if (r.exitCode !== 0) return { result: `narrador salió con ${r.exitCode}: ${salida}`, isError: true as const }
    return { result: h.despues ? h.despues(salida) : salida }
  } catch (error) {
    return { result: `no pude ejecutar narrador: ${String(error)}`, isError: true as const }
  }
}

// --- tablero de hallazgos: funciones al principio del archivo, porque reciben `$` ---
async function pintarTablero($: EngineInterface, texto: string) {
  const leido = leerTablero(texto)
  await update($, tablero, () => leido.tarjetas)
  await update($, tableroMeta, () => leido.meta)
  await update($, tableroCuando, () => Date.now())
  await update($, tableroFallo, () => '')
  return leido
}

let leyendoTablero = false
async function sondearTablero($: EngineInterface, forzar = false) {
  if (leyendoTablero && !forzar) return
  leyendoTablero = true
  try {
    const r = await $.process.run([NARRADOR, 'tablero', 'ver', '--json'], { timeoutMs: 15000, env: ENTORNO })
    if (r.exitCode !== 0) {
      throw new Error(`narrador tablero salió con ${r.exitCode}: ${cortar(r.stderr.trim() || r.stdout.trim(), 200)}`)
    }
    await pintarTablero($, r.stdout)
  } catch (error) {
    // Lo que ya se veía se queda: un fallo de lectura no vacía el tablero.
    $.ui.log(`io-cabina tablero: ${String(error)}`, { to: 'debug' })
    try {
      await update($, tableroFallo, () => String(error))
    } catch {
      // sin más recursos
    }
  } finally {
    leyendoTablero = false
  }
}

// Mover o deshacer: la orden escribe el archivo y devuelve el tablero ya cambiado.
async function ordenarTablero($: EngineInterface, args: string[], hecho: (deshecho: string) => string) {
  try {
    const r = await $.process.run([NARRADOR, 'tablero', ...args], { timeoutMs: 15000, env: ENTORNO })
    if (r.exitCode === 0) {
      const leido = await pintarTablero($, r.stdout)
      $.ui.toast(cortar(hecho(leido.deshecho), 120), { timeoutMs: 6000 })
      return
    }
    $.ui.toast(
      r.exitCode === 4
        ? 'La tarjeta cambió mientras tanto; vuelvo a leer el tablero.'
        : cortar(r.stderr.trim() || `narrador tablero salió con ${r.exitCode}`, 120),
      { timeoutMs: 6000 },
    )
  } catch (error) {
    $.ui.toast(cortar(`no pude cambiar el tablero: ${String(error)}`, 120), { timeoutMs: 6000 })
  }
  await sondearTablero($, true)
}

async function moverTarjeta($: EngineInterface, t: TarjetaTablero, columna: string) {
  await ordenarTablero(
    $,
    ['mover', t.id, columna, '--origen', 'mod', '--desde', t.columna],
    () => `${t.cliente} · ${t.titulo} → ${nombreColumna(columna)} (u deshace)`,
  )
}

async function deshacerTablero($: EngineInterface) {
  await ordenarTablero($, ['deshacer', '--origen', 'mod'], deshecho => `Deshecho: ${deshecho || 'último movimiento'}`)
}

async function abrirTablero($: EngineInterface, columnas: number | undefined, foco: boolean) {
  return $.ui.open({
    id: PANE_TABLERO,
    title: 'Tablero',
    backgroundColor: FONDO,
    columns: columnas,
    ...(foco ? { focus: true as const } : {}),
  })
}

export const register: Register = on => {
  let sondeando = false
  let refrescarRoadmap: () => Promise<void> = async () => {}
  // Una vuelta del sondeo de la cabina a demanda (al abrirla con /cabina).
  let refrescar: () => Promise<void> = async () => {}
  // El proyecto fijado vive en un archivo para que Ío también pueda fijarlo.
  const FIJO = `${CAB}/roadmap-fijo`
  let leerFijo: () => Promise<string> = async () => ''
  // Ancho pedido para los paneles (columnas); se guarda en un archivo y lo fija /cabina-ancho N.
  const ANCHO = `${CAB}/ancho`
  const ancho = async (leer: (ruta: string) => Promise<string>): Promise<number | undefined> => {
    try {
      const n = parseInt((await leer(ANCHO)).trim(), 10)
      return Number.isFinite(n) && n >= 24 ? n : undefined
    } catch {
      return undefined
    }
  }
  let primera = true
  const vistas = new Set<string>()
  // Para los tonos: qué trabajadores seguían en marcha y qué puertas había en la vuelta anterior.
  let vivosAntes = new Set<string>()
  // Proyecto → última vez que se vio una sesión suya ocupada o bloqueada (o un trabajador suyo en
  // marcha): ordena los grupos de /cabina por actividad reciente. Una recarga la empieza de cero.
  const actividad = new Map<string, number>()
  let puertasAntes = new Set<string>()

  on('session.start', async ($, e, next) => {
    await ubicarNarrador($)
    esIo = await esSesionDeIo($)
    if (esIo) await registrarHerramientas($)
    await $.command.register({
      name: 'cabina',
      description: 'Abre el panel de Ío con sesiones, trabajos y alertas',
    })
    await $.command.register({
      name: 'puertas',
      description: 'Lo que espera tu sí (push, gasto, envíos…): responde con Sí o No; la cabina nunca ejecuta el comando',
    })
    await $.command.register({
      name: 'roadmap',
      description: 'Roadmap del proyecto de tu sesión activa (o /roadmap NOMBRE para fijarlo, /roadmap auto para soltarlo)',
    })
    await $.command.register({
      name: 'tablero',
      description: 'Tablero de hallazgos del parte: nuevos, en curso, dejados de lado y resueltos; mueve y cierra tarjetas',
    })
    await $.command.register({
      name: 'cabina-ancho',
      description: 'Ancho de los paneles de Ío en columnas: /cabina-ancho 50 (sin número, el de por defecto)',
    })
    await $.command.register({
      name: 'cabina-limpiar',
      description: 'Borra las alertas y los trabajos del panel de Ío',
    })

    const leer = async (ruta: string) => {
      try {
        return await $.fs.read(ruta)
      } catch {
        return ''
      }
    }

    const ultimoParte = async (): Promise<Parte> => {
      try {
        const archivos = (await $.fs.list(`${NARR}/partes`))
          .map(f => f.name)
          .filter(n => /^\d{4}-\d{2}-\d{2}\.json$/.test(n))
          .sort()
        const nombre = archivos[archivos.length - 1]
        if (!nombre) return null
        const d = JSON.parse(await $.fs.read(`${NARR}/partes/${nombre}`))
        return {
          fecha: String(d.fecha ?? nombre.slice(0, 10)),
          semaforo: String(d.semaforo ?? ''),
          resumen: String(d.resumen_voz ?? ''),
        }
      } catch {
        return null
      }
    }

    const sondear = async () => {
      if (sondeando) return
      sondeando = true
      try {
        const [vivas, permisos] = await Promise.all([
          $.process.run([NARRADOR, 'sesiones', '--vivas'], { timeoutMs: 15000, env: ENTORNO }),
          $.process.run([NARRADOR, 'permisos', '--json'], { timeoutMs: 15000, env: ENTORNO }),
        ])
        const nuevas = leerAlertas(await leer(`${CAB}/alertas.jsonl`))
        const trabajosAhora = leerTrabajos(await leer(`${CAB}/trabajos.json`))
        const pendientesAhora = leerPendientes(await leer(RAM))
        const parteAhora = await ultimoParte()
        const sesionesAhora = leerSesiones(vivas.stdout)
        const ahoraMs = Date.now()

        // Trabajadores en marcha: solo si `sesiones --vivas` respondió; si no, sigue lo de antes
        // (una lectura fallida no es «todos han terminado» y no debe sonar).
        let terminados = 0
        if (vivas.exitCode === 0) {
          const lanzados = leerLanzados(await leer(TRABAJADORES), ahoraMs)
          const enMarcha = await trabajadoresVivos($, lanzados, sesionesAhora, ahoraMs)
          const ids = new Set(enMarcha.map(v => v.nombre))
          terminados = [...vivosAntes].filter(n => !ids.has(n)).length
          vivosAntes = ids
          await update($, vivos, () => enMarcha)
          for (const v of enMarcha) if (v.ruta) actividad.set(proyectoDe(v.ruta), ahoraMs)
        }
        // Puertas: las nuevas abiertas suenan; un fallo de lectura no cambia nada.
        const puertasAhora = await sondearPuertas($)
        let puertasNuevas = 0
        if (puertasAhora) {
          const abiertas = new Set(puertasAhora.filter(p => p.estado === 'abierta').map(p => p.id))
          puertasNuevas = [...abiertas].filter(id => !puertasAntes.has(id)).length
          puertasAntes = abiertas
        }
        try {
          const usd = (await $.session.usage()).cost?.usd
          await update($, gasto, () => (typeof usd === 'number' ? usd : null))
        } catch {
          // el motor no lleva la cuenta aquí
        }

        for (const s of sesionesAhora) {
          if (s.estado === 'busy' || s.estado === 'blocked') actividad.set(proyectoDe(s.cwd), ahoraMs)
        }
        await update($, sesiones, () => sesionesAhora)
        await update($, esperas, () => leerEsperas(permisos.stdout))
        await update($, alertas, () => nuevas)
        await update($, trabajos, () => trabajosAhora)
        await update($, pendientes, () => pendientesAhora)
        await update($, parte, () => parteAhora)
        await update($, actualizado, () => Date.now())
        await update($, fallo, () => '')

        // Un aviso emergente por alerta nueva roja o ámbar; las que ya
        // existían al abrir la sesión solo se anotan.
        let rojasNuevas = 0
        for (const a of nuevas) {
          if (vistas.has(a.id)) continue
          vistas.add(a.id)
          if (!primera && colorNivel(a.nivel)) {
            $.ui.toast(cortar(a.texto, 120), { timeoutMs: 8000 })
            if (a.nivel === 'rojo') rojasNuevas += 1
          }
        }
        // Un solo tono por vuelta, el más importante. La primera vuelta (arranque o recarga) solo anota.
        if (!primera) {
          if (rojasNuevas > 0) sonar($, 'error')
          else if (puertasNuevas > 0) sonar($, 'puerta')
          else if (terminados > 0) sonar($, 'terminado')
        }
        primera = false
      } catch (error) {
        $.ui.log(`io-cabina: ${String(error)}`, { to: 'debug' })
        try {
          await update($, fallo, () => String(error))
        } catch {
          // sin más recursos
        }
      } finally {
        sondeando = false
      }
    }

    refrescar = sondear
    void sondear()
    $.clock.every(CADA_MS, () => {
      void sondear()
    })

    // Roadmap: se lee cada minuto (git en tres repos; barato, pero no cada 8 s).
    let leyendoRoadmap = false
    const sondearRoadmap = async () => {
      if (leyendoRoadmap) return
      leyendoRoadmap = true
      try {
        const fijo = (await leerFijo()).trim()
        await update($, roadmapFijo, () => fijo)
        const r = await $.process.run([NARRADOR, 'roadmap', '--json', fijo || '--activo'], {
          timeoutMs: 45000,
          env: ENTORNO,
        })
        if (r.exitCode === 2) {
          // ninguna sesión tuya abierta: no es un fallo
          await update($, roadmap, () => [])
          await update($, roadmapOrigen, () => 'sin sesión activa')
          await update($, roadmapCuando, () => Date.now())
          await update($, roadmapFallo, () => '')
          return
        }
        if (r.exitCode !== 0) {
          throw new Error(`narrador roadmap salió con ${r.exitCode}: ${cortar(r.stderr.trim() || r.stdout.trim(), 200)}`)
        }
        const proyectos = leerRoadmap(r.stdout)
        let origen = `fijado: ${fijo}`
        if (!fijo) {
          const act = (JSON.parse(r.stdout) as Dic).activo as Dic | null
          origen = act ? `sesión ${str(act.sesion)} · ${ultimo(str(act.cwd))}` : 'sin sesión activa'
        }
        await update($, roadmap, () => proyectos)
        await update($, roadmapOrigen, () => origen)
        await update($, roadmapCuando, () => Date.now())
        await update($, roadmapFallo, () => '')
      } catch (error) {
        $.ui.log(`io-cabina roadmap: ${String(error)}`, { to: 'debug' })
        try {
          await update($, roadmapFallo, () => String(error))
        } catch {
          // sin más recursos
        }
      } finally {
        leyendoRoadmap = false
      }
    }
    refrescarRoadmap = sondearRoadmap
    leerFijo = async () => {
      try {
        return await $.fs.read(FIJO)
      } catch {
        return ''
      }
    }
    void sondearRoadmap()
    $.clock.every(ROADMAP_CADA_MS, () => {
      void sondearRoadmap()
    })

    // Tablero: leer un archivo local es barato; cada 20 s recoge lo que muevan el parte o Ío por voz.
    void sondearTablero($)
    $.clock.every(TABLERO_CADA_MS, () => {
      void sondearTablero($)
    })
    void (async () => {
      await $.ui.open({ id: PANE, title: 'Cabina de Ío', backgroundColor: FONDO, columns: await ancho(r => $.fs.read(r)) })
      // El tablero se abre solo, como pestaña junto a la cabina y sin pedir el teclado.
      await abrirTablero($, await ancho(r => $.fs.read(r)), false)
    })()

    return next(e)
  })

  on('command.run', { command: 'cabina' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Cabina de Ío', backgroundColor: FONDO, columns: await ancho(r => $.fs.read(r)) })
    await refrescar()
    return { text: 'Cabina abierta.' }
  })

  // /puertas: pestaña con el detalle de cada puerta (comando, coste, vuelta atrás) y el teclado para s/n.
  on('command.run', { command: 'puertas' }, async $ => {
    await abrirPuertas($, await ancho(r => $.fs.read(r)), true)
    const lista = (await sondearPuertas($)) ?? (await read($, puertas))
    const abiertas = lista.filter(p => p.estado === 'abierta').length
    return {
      text: abiertas
        ? `${abiertas} puerta(s) esperan tu sí. Responder solo lo anota: el comando lo ejecuta Ío.`
        : 'No hay puertas abiertas.',
    }
  })

  // Herramientas de Ío (solo se registran en su sesión; aquí, además, se niegan fuera de ella).
  on('tool.call', { tool: 'mcp__io-cabina__trabajador_lanzar' }, ($, e) => usarHerramienta($, 'trabajador_lanzar', e as unknown as Entrada)).catch(
    () => ({ deny: 'io-cabina: la herramienta falló; usa narrador por Bash.' }),
  )
  on('tool.call', { tool: 'mcp__io-cabina__trabajador_lista' }, ($, e) => usarHerramienta($, 'trabajador_lista', e as unknown as Entrada)).catch(
    () => ({ deny: 'io-cabina: la herramienta falló; usa narrador por Bash.' }),
  )
  on('tool.call', { tool: 'mcp__io-cabina__permisos' }, ($, e) => usarHerramienta($, 'permisos', e as unknown as Entrada)).catch(
    () => ({ deny: 'io-cabina: la herramienta falló; usa narrador por Bash.' }),
  )
  on('tool.call', { tool: 'mcp__io-cabina__sesiones_vivas' }, ($, e) => usarHerramienta($, 'sesiones_vivas', e as unknown as Entrada)).catch(
    () => ({ deny: 'io-cabina: la herramienta falló; usa narrador por Bash.' }),
  )
  on('tool.call', { tool: 'mcp__io-cabina__puerta_anadir' }, ($, e) => usarHerramienta($, 'puerta_anadir', e as unknown as Entrada)).catch(
    () => ({ deny: 'io-cabina: la herramienta falló; usa narrador por Bash.' }),
  )

  // /tablero: abre la pestaña, le da el teclado (para los atajos) y vuelve a leer el archivo.
  on('command.run', { command: 'tablero' }, async $ => {
    await abrirTablero($, await ancho(r => $.fs.read(r)), true)
    await sondearTablero($, true)
    const lista = await read($, tablero)
    const cuenta = (c: string) => lista.filter(t => t.columna === c).length
    return {
      text: `Tablero: ${cuenta('nuevos')} nuevos, ${cuenta('en_curso')} en curso, ${cuenta('dejados')} dejados de lado y ${cuenta('resueltos')} resueltos.`,
    }
  })

  // /cabina-ancho N: ancho en columnas de la cabina y el roadmap (máx. 45 % de la terminal); sin N, el reparto por defecto.
  on('command.run', { command: 'cabina-ancho' }, async ($, e) => {
    const n = parseInt(e.args.trim(), 10)
    const valor = Number.isFinite(n) && n >= 24 ? n : undefined
    await $.fs.write(ANCHO, valor ? String(valor) : '')
    await $.ui.open({ id: PANE, title: 'Cabina de Ío', backgroundColor: FONDO, columns: valor })
    return {
      text: valor
        ? `Paneles a ${valor} columnas (el máximo es el 45 % de la terminal). Vuelve a abrir /roadmap para aplicarlo allí.`
        : 'Ancho por defecto. Usa /cabina-ancho N con N ≥ 24.',
    }
  })

  // /roadmap: abre; /roadmap NOMBRE|RUTA: lo fija; /roadmap auto: vuelve a seguir la sesión activa.
  on('command.run', { command: 'roadmap' }, async ($, e) => {
    const arg = e.args.trim()
    if (arg === 'auto') {
      await $.fs.write(FIJO, '')
      await update($, roadmapFijo, () => '')
    } else if (arg) {
      await $.fs.write(FIJO, arg)
      await update($, roadmapFijo, () => arg)
    }
    await $.ui.open({ id: PANE_ROADMAP, title: 'Roadmap', backgroundColor: FONDO, columns: await ancho(r => $.fs.read(r)) })
    void refrescarRoadmap()
    const fijo = arg === 'auto' ? '' : arg || (await read($, roadmapFijo))
    return {
      text: fijo
        ? `Roadmap fijado en «${fijo}» (/roadmap auto para seguir tu sesión activa).`
        : 'Roadmap del proyecto de tu sesión activa más reciente.',
    }
  })

  on('command.run', { command: 'cabina-limpiar' }, async $ => {
    await $.fs.write(`${CAB}/alertas.jsonl`, '')
    await $.fs.write(`${CAB}/trabajos.json`, '[]')
    await update($, alertas, () => [])
    await update($, trabajos, () => [])
    return { text: 'Alertas y trabajos borrados.' }
  })

  // Una sola línea sobre el prompt: solo se pinta si hay algo que mirar.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const vivas = await read($, sesiones)
    const espera = await read($, esperas)
    const avisos = await read($, alertas)
    const p = await read($, parte)
    const bloqueadas = vivas.filter(s => s.estado === 'blocked').length
    const urgentes = avisos.filter(a => colorNivel(a.nivel)).length
    const tarde = (await read($, roadmap)).filter(r => r.semaforo === 'rojo').length
    const nuevas = (await read($, tablero)).filter(t => t.columna === 'nuevos')
    const enMarcha = await read($, vivos)
    const abiertas = (await read($, puertas)).filter(p => p.estado === 'abierta')
    const usd = await read($, gasto)

    // Solo sale si hay algo en marcha o esperándote (u otras sesiones abiertas, como antes); el gasto solo acompaña.
    const algo = bloqueadas + espera.length + urgentes + tarde + nuevas.length + enMarcha.length + abiertas.length
    if (algo === 0 && vivas.length <= 1) {
      return next(e)
    }

    // Una línea: los trabajadores con su id y la tarea recortada al sitio que quede.
    const columnas = e.props.bodyColumns ?? 100
    const tareaLarga = Math.max(12, Math.min(32, Math.floor((columnas - 60) / Math.max(1, Math.min(enMarcha.length, 3)))))
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box>
        <Text color={ACENTO}>✦ Ío</Text>
        {vivas.length > 1 && <Text color={TENUE}> · {vivas.length} sesiones</Text>}
        {enMarcha.slice(0, 3).map(v => (
          <Text color={AMBAR}>
            {' '}
            · ⚙ {v.id} <Text color={TENUE}>{cortar(v.tarea.replace(/\s+/g, ' '), tareaLarga)}</Text>
          </Text>
        ))}
        {enMarcha.length > 3 && <Text color={AMBAR}> +{enMarcha.length - 3}</Text>}
        {abiertas.length > 0 && (
          <Text color={DORADO}>
            {' '}
            · {abiertas.length === 1 ? `puerta: ${cortar(abiertas[0]?.titulo ?? '', 28)}` : `${abiertas.length} puertas`} · /puertas
          </Text>
        )}
        {bloqueadas > 0 && <Text color={ROJO}> · {bloqueadas} bloqueada(s)</Text>}
        {espera.length > 0 && <Text color={ROJO}> · {espera.length} esperan permiso</Text>}
        {urgentes > 0 && <Text color={AMBAR}> · {urgentes} alerta(s)</Text>}
        {p && <Text color={colorSemaforo(p.semaforo)}> · parte {p.semaforo}</Text>}
        {tarde > 0 && <Text color={ROJO}> · {tarde} proyecto(s) con retraso · /roadmap</Text>}
        {nuevas.length > 0 && (
          <Text color={nuevas.some(t => t.nivel === 'rojo') ? ROJO : AMBAR}>
            {' '}
            · {nuevas.length} hallazgo(s) nuevo(s) · /tablero
          </Text>
        )}
        {usd !== null && <Text color={TENUE}> · sesión {dolares(usd)}</Text>}
        <Text color={TENUE}> · /cabina</Text>
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE_PUERTAS }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const lista = await read($, puertas)
    const error = await read($, puertasFallo)
    const abiertas = lista.filter(p => p.estado === 'abierta')
    const respondidas = lista.filter(p => p.estado === 'si' || p.estado === 'no')

    return (
      <Box flexDirection="column" paddingX={1}>
        <Box borderStyle="round" borderColor={ACENTO} paddingX={1} justifyContent="space-between">
          <Text bold color={ACENTO}>
            ✦ Puertas
          </Text>
          <Text color={TENUE}>{abiertas.length} abiertas</Text>
        </Box>
        {error !== '' && (
          <Box marginTop={1}>
            <Text color={ROJO}>⚠ {cortar(error, 200)}</Text>
          </Box>
        )}
        {abiertas.length === 0 && (
          <Box marginTop={1}>
            <Text color={TENUE}>Nada espera tu sí. Ío las registra con narrador puerta añadir.</Text>
          </Box>
        )}
        {abiertas.map((p, i) => (
          <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor={MARCO} paddingX={1}>
            <Text bold color={DORADO}>
              {p.id} · {cortar(p.titulo, 70)}
            </Text>
            {(p.proyecto !== '' || p.coste !== '') && (
              <Text color={TENUE}>
                {[p.proyecto, p.coste ? `coste ${p.coste}` : ''].filter(Boolean).join(' · ')}
              </Text>
            )}
            <Text>
              <Text color={TENUE}>comando: </Text>
              {cortar(p.comando, 300)}
            </Text>
            {p.vuelta !== '' && (
              <Text>
                <Text color={TENUE}>vuelta atrás: </Text>
                {cortar(p.vuelta, 200)}
              </Text>
            )}
            <Box>
              <Box marginRight={2}>
                <Button
                  key={`si-${p.id}`}
                  variant="primary"
                  label="Sí"
                  {...(i === 0 ? { hotkey: 's' } : {})}
                  onPress={() => void responderPuerta($, p, 'si')}
                />
              </Box>
              <Button
                key={`no-${p.id}`}
                label="No"
                {...(i === 0 ? { hotkey: 'n' } : {})}
                onPress={() => void responderPuerta($, p, 'no')}
              />
            </Box>
          </Box>
        ))}
        {respondidas.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text color={DORADO} bold>
              ◆ RESPONDIDAS · {respondidas.length}
            </Text>
            {respondidas.map(p => (
              <Text color={TENUE}>
                <Text color={p.estado === 'si' ? VERDE : ROJO}>{p.estado === 'si' ? '✓ sí' : '✗ no'}</Text> · {p.id} ·{' '}
                {cortar(p.titulo, 50)} · {p.estado === 'si' ? 'Ío lo ejecuta y la cierra' : 'Ío la cierra'}
              </Text>
            ))}
          </Box>
        )}
        <Box marginTop={1}>
          <Text color={TENUE}>
            Responder solo lo anota y se lo pasa a Ío: la cabina nunca ejecuta el comando. Con el panel enfocado, s y n
            responden a la primera.
          </Text>
        </Box>
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE_TABLERO }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const lista = await read($, tablero)
    const meta = await read($, tableroMeta)
    const cuando = await read($, tableroCuando)
    const error = await read($, tableroFallo)
    const sel = await read($, tableroSel)

    const Tarjeta = (t: TarjetaTablero) => {
      const abierta = t.id === sel
      return (
        <Box flexDirection="column">
          <Button
            key={`tarjeta-${t.id}`}
            plain
            onPress={() => update($, tableroSel, actual => (actual === t.id ? '' : t.id))}
          >
            <Text color={colorNivel(t.nivel)}>{abierta ? '▾ ' : '● '}</Text>
            <Text bold>{t.cliente}</Text>
            <Text> · {cortar(t.titulo, 40)}</Text>
            <Text color={DORADO}>{t.marca ? ` · ${t.marca}` : ''}</Text>
            <Text color={TENUE}>{t.fiabilidad === 'estimado' ? ' · estimado' : ''}</Text>
          </Button>
          {!abierta && (
            <Text color={TENUE}>
              {'  '}
              {cortar(t.detalle[0] ?? '', 100)}
              {t.detalle.length > 1 ? ` (+${t.detalle.length - 1})` : ''}
            </Text>
          )}
          {abierta && (
            <Box flexDirection="column" borderStyle="round" borderColor={MARCO} paddingX={1}>
              {t.detalle.map(d => (
                <Text>{cortar(d, 200)}</Text>
              ))}
              <Text color={TENUE}>
                {t.nivel === 'rojo' ? 'rojo' : 'ámbar'} · {t.fiabilidad || 'comprobado'} · desde el {t.primera} · visto el{' '}
                {t.ultima}
              </Text>
              {t.movimiento !== '' && <Text color={TENUE}>último movimiento: {t.movimiento}</Text>}
              <Box>
                {COLUMNAS_TABLERO.filter(c => c.id !== t.columna).map(c => (
                  <Box marginRight={2}>
                    <Button
                      key={`mover-${c.id}`}
                      plain
                      hotkey={c.tecla}
                      label={c.accion}
                      onPress={() => void moverTarjeta($, t, c.id)}
                    />
                  </Box>
                ))}
              </Box>
            </Box>
          )}
        </Box>
      )
    }

    return (
      <Box flexDirection="column" paddingX={1}>
        <Box borderStyle="round" borderColor={ACENTO} paddingX={1} justifyContent="space-between">
          <Text bold color={ACENTO}>
            ✦ Tablero
          </Text>
          <Text color={TENUE}>{cuando ? `actualizado ${hora(cuando)}` : 'cargando…'}</Text>
        </Box>
        {cuando > 0 && meta.existe && (
          <Text color={TENUE}>
            {' '}
            {meta.parteFecha ? `parte del ${meta.parteFecha}` : 'sin cruzar con ningún parte'} ·{' '}
            <Text color={colorSemaforo(meta.semaforo)}>● {meta.semaforo}</Text>
          </Text>
        )}

        {error !== '' && (
          <Box marginTop={1}>
            <Text color={ROJO}>⚠ {cortar(error, 200)}</Text>
          </Box>
        )}
        {meta.invalidas > 0 && (
          <Box marginTop={1}>
            <Text color={AMBAR}>
              ⚠ {meta.invalidas} tarjeta(s) con formato no válido, sin mostrar · narrador tablero ver --json
            </Text>
          </Box>
        )}
        {meta.puedeDeshacer && (
          <Box marginTop={1}>
            <Button key="deshacer" plain hotkey="u" label="deshacer el último movimiento" onPress={() => void deshacerTablero($)} />
          </Box>
        )}

        {cuando === 0 && error === '' && (
          <Box marginTop={1}>
            <Text color={TENUE}>Leyendo el tablero…</Text>
          </Box>
        )}
        {cuando > 0 && !meta.existe && (
          <Box marginTop={1}>
            <Text color={TENUE}>No hay tablero todavía. Lo estrena el parte con narrador tablero aplicar --crear.</Text>
          </Box>
        )}

        {cuando > 0 &&
          meta.existe &&
          COLUMNAS_TABLERO.map(c => {
            const propias = lista.filter(t => t.columna === c.id)
            const visibles =
              c.id === 'resueltos'
                ? [...propias].sort((a, b) => b.ultima.localeCompare(a.ultima) || a.id.localeCompare(b.id)).slice(0, RESUELTOS_VISIBLES)
                : [...propias].sort(ordenTablero)
            return (
              <Box flexDirection="column" marginTop={1}>
                <Text color={DORADO} bold>
                  ◆ {c.titulo.toUpperCase()} · {propias.length}
                </Text>
                {propias.length === 0 && <Text color={TENUE}>Nada.</Text>}
                {visibles.map(Tarjeta)}
                {propias.length > visibles.length && (
                  <Text color={TENUE}>… y {propias.length - visibles.length} más · narrador tablero ver</Text>
                )}
              </Box>
            )
          })}

        {cuando > 0 && meta.existe && lista.length > 0 && (
          <Box marginTop={1}>
            <Text color={TENUE}>
              Pulsa una tarjeta para desplegarla. Con el panel enfocado, n, c, d y r mueven la desplegada y u deshace.
            </Text>
          </Box>
        )}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const abrirSesion = (clave: string) => {
      void (async () => {
        try {
          const r = await $.process.run([NARRADOR, 'sesion', 'abrir', clave], { timeoutMs: 15000, env: ENTORNO })
          $.ui.toast(cortar((r.exitCode === 0 ? r.stdout : r.stderr).trim() || 'hecho', 120), { timeoutMs: 5000 })
        } catch (error) {
          $.ui.toast(cortar(`no pude abrir ${clave}: ${String(error)}`, 120), { timeoutMs: 6000 })
        }
      })()
    }
    const vivas = await read($, sesiones)
    const espera = await read($, esperas)
    const avisos = await read($, alertas)
    const lista = await read($, trabajos)
    const pend = await read($, pendientes)
    const p = await read($, parte)
    const cuando = await read($, actualizado)
    const error = await read($, fallo)
    const bloqueadas = vivas.filter(s => s.estado === 'blocked')
    const abiertas = (await read($, puertas)).filter(p => p.estado === 'abierta')
    const { io: sesionesIo, grupos } = agruparSesiones(vivas, espera, await read($, vivos), actividad)
    // Anchos a la medida del panel: en uno estrecho se recortan los nombres, nunca la cabecera entera.
    const ancho = Math.max(24, (e.props.bodyColumns ?? 80) - 2)
    const largoNombre = Math.max(12, Math.min(34, ancho - 22))
    const largoProyecto = Math.max(8, ancho - 26)

    const FilaSesion = (props: { s: Sesion; donde: string }) => (
      <Button key={`ses-${props.s.id || props.s.nombre}`} plain onPress={() => abrirSesion(props.s.id || props.s.nombre)}>
        <Text color={colorEstado(props.s.estado)}>
          {'  '}
          {props.s.estado === 'idle' ? '○ ' : '● '}
        </Text>
        <Text>{cortar(props.s.nombre, largoNombre)} </Text>
        <Text color={TENUE}>
          {props.s.estado}
          {props.donde ? ` · ${cortar(props.donde, Math.max(10, ancho - largoNombre - 16))}` : ''}
        </Text>
      </Button>
    )

    const Seccion = (props: { titulo: string; children?: RenderChildren }) => (
      <Box flexDirection="column" marginTop={1}>
        <Text color={DORADO} bold>
          ◆ {props.titulo.toUpperCase()}
        </Text>
        {props.children}
      </Box>
    )

    return (
      <Box flexDirection="column" paddingX={1}>
        <Box borderStyle="round" borderColor={ACENTO} paddingX={1} justifyContent="space-between">
          <Text bold color={ACENTO}>
            ✦ Ío
          </Text>
          <Text color={TENUE}>{cuando ? `actualizado ${hora(cuando)}` : 'cargando…'}</Text>
        </Box>

        {error !== '' && (
          <Box marginTop={1}>
            <Text color={ROJO}>⚠ {cortar(error, 140)}</Text>
          </Box>
        )}

        {p && (
          <Seccion titulo="Parte">
            <Text>
              <Text color={colorSemaforo(p.semaforo)}>● {p.semaforo}</Text>
              <Text color={TENUE}> · {p.fecha}</Text>
            </Text>
            <Text color={TENUE}>{cortar(p.resumen, 110)}</Text>
          </Seccion>
        )}

        <Seccion titulo="Te esperan">
          {espera.length === 0 && bloqueadas.length === 0 && (
            <Text color={TENUE}>Nada pendiente de tu permiso.</Text>
          )}
          {espera.map(x => (
            <Button key={`espera-${x.nombre}`} plain onPress={() => abrirSesion(x.nombre)}>
              <Text color={ROJO}>● {x.nombre} </Text>
              <Text color={TENUE}>· {cortar(x.detalle, 50)} · abrir para aprobar</Text>
            </Button>
          ))}
          {bloqueadas.map(s => (
            <Button key={`bloq-${s.id || s.nombre}`} plain onPress={() => abrirSesion(s.id || s.nombre)}>
              <Text color={ROJO}>● {cortar(s.nombre, 30)} </Text>
              <Text color={TENUE}>bloqueada · {cortar(proyectoDe(s.cwd) || ultimo(s.cwd), 24)} · abrir para aprobar</Text>
            </Button>
          ))}
        </Seccion>

        {abiertas.length > 0 && (
          <Seccion titulo="Puertas">
            {abiertas.map(p => (
              <Box flexDirection="column">
                <Text>
                  <Text color={DORADO}>● {p.id} </Text>
                  {cortar(p.titulo, 60)}
                  <Text color={TENUE}>{p.coste ? ` · ${cortar(p.coste, 30)}` : ''}</Text>
                </Text>
                <Box>
                  <Text>{'  '}</Text>
                  <Box marginRight={2}>
                    <Button key={`si-${p.id}`} plain label="Sí" onPress={() => void responderPuerta($, p, 'si')} />
                  </Box>
                  <Button key={`no-${p.id}`} plain label="No" onPress={() => void responderPuerta($, p, 'no')} />
                </Box>
              </Box>
            ))}
            <Text color={TENUE}>Solo se anota y se le pasa a Ío; el detalle, en /puertas.</Text>
          </Seccion>
        )}

        <Seccion titulo="Sesiones">
          {vivas.length === 0 && <Text color={TENUE}>Sin datos todavía.</Text>}
          {sesionesIo.map(s => (
            <Button key={`ses-${s.id || s.nombre}`} plain onPress={() => abrirSesion(s.id || s.nombre)}>
              <Text color={ACENTO}>✦ </Text>
              <Text bold>{s.nombre} </Text>
              <Text color={TENUE}>{s.estado}</Text>
            </Button>
          ))}
          {grupos.map(g => (
            <Box key={`grupo-${g.titulo}`} flexDirection="column" marginTop={1}>
              <Text>
                <Text color={g.clave === '' ? TENUE : ACENTO} bold>
                  ▸ {cortar(g.titulo, largoProyecto)}
                </Text>
                <Text color={TENUE}>
                  {' '}
                  · {g.sesiones.length} {g.sesiones.length === 1 ? 'sesión' : 'sesiones'}
                </Text>
                {g.sueltos.length > 0 && <Text color={AMBAR}> · ⚙ {g.sueltos.length}</Text>}
                {g.esperan > 0 && <Text color={ROJO}> · {g.esperan} te {g.esperan === 1 ? 'espera' : 'esperan'}</Text>}
              </Text>
              {g.sesiones.map(s => (
                <FilaSesion s={s} donde={dondeEn(s.cwd, g.clave)} />
              ))}
              {g.sueltos.map(t => (
                <Text color={AMBAR}>
                  {'  '}⚙ {t.id} <Text color={TENUE}>{cortar(t.tarea.replace(/\s+/g, ' '), Math.max(10, ancho - 12))}</Text>
                </Text>
              ))}
            </Box>
          ))}
          {vivas.length > 0 && <Text color={TENUE}>Pulsa una sesión para abrirla o traer su ventana.</Text>}
        </Seccion>

        {lista.length > 0 && (
          <Seccion titulo="Trabajos">
            {lista.map(t => (
              <Text>
                <Text color={t.estado === 'fallo' ? ROJO : t.estado === 'hecho' ? VERDE : AMBAR}>
                  {t.estado === 'hecho' ? '✓' : t.estado === 'fallo' ? '✗' : '…'}
                </Text>{' '}
                {cortar(t.nombre, 28)} <Text color={TENUE}>{cortar(t.detalle, 70)}</Text>
              </Text>
            ))}
          </Seccion>
        )}

        <Seccion titulo="Alertas">
          {avisos.length === 0 && <Text color={TENUE}>Sin alertas.</Text>}
          {avisos.slice(0, 6).map(a => (
            <Text color={colorNivel(a.nivel)}>
              <Text color={TENUE}>{hora(a.ts)}</Text> {cortar(a.texto, 100)}
            </Text>
          ))}
        </Seccion>

        {pend.length > 0 && (
          <Seccion titulo="Pendiente">
            {pend.map(x => (
              <Text color={TENUE}>· {cortar(x, 100)}</Text>
            ))}
          </Seccion>
        )}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE_ROADMAP }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const lista = await read($, roadmap)
    const cuando = await read($, roadmapCuando)
    const error = await read($, roadmapFallo)
    const origen = await read($, roadmapOrigen)

    return (
      <Box flexDirection="column" paddingX={1}>
        <Box borderStyle="round" borderColor={ACENTO} paddingX={1} justifyContent="space-between">
          <Text bold color={ACENTO}>
            ✦ Roadmap
          </Text>
          <Text color={TENUE}>{cuando ? `actualizado ${hora(cuando)}` : 'cargando…'}</Text>
        </Box>
        {origen !== '' && <Text color={TENUE}> {cortar(origen, 90)}</Text>}

        {error !== '' && (
          <Box marginTop={1}>
            <Text color={ROJO}>⚠ {cortar(error, 200)}</Text>
          </Box>
        )}

        {lista.length === 0 && error === '' && (
          <Box marginTop={1}>
            <Text color={TENUE}>
              {origen === 'sin sesión activa'
                ? 'No hay ninguna sesión tuya abierta. Abre una en un proyecto o fija uno con /roadmap NOMBRE.'
                : 'Leyendo el vault del proyecto…'}
            </Text>
          </Box>
        )}

        {lista.map(r => {
          const b = barra(r.hechos, r.total)
          return (
            <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor={MARCO} paddingX={1}>
              <Box justifyContent="space-between">
                <Text bold color={ACENTO}>
                  {r.nombre}
                </Text>
                {r.error === '' && <Text color={colorDeriva(r.semaforo)}>● {cortar(r.deriva, 48)}</Text>}
              </Box>
              {r.error !== '' ? (
                <Text color={ROJO}>⚠ {cortar(r.error, 160)}</Text>
              ) : (
                <Box flexDirection="column">
                  <Text>
                    <Text color={ACENTO}>{b.llena}</Text>
                    <Text color={TENUE}>{b.vacia}</Text>
                    <Text>
                      {' '}
                      {r.hechos}/{r.total} hitos{r.pct !== null ? ` · ${r.pct} %` : ''}
                    </Text>
                  </Text>
                  <Text color={TENUE}>
                    medido · último movimiento {r.ultimo || '?'}
                    {r.diasSinTocar !== null ? ` (hace ${r.diasSinTocar} d)` : ''}
                    {r.commits4s !== null ? ` · ${r.commits4s} commits en 4 sem` : ''}
                    {r.sinCommit ? ` · ${r.sinCommit} sin commit` : ''}
                    {r.responsable ? ` · ${cortar(r.responsable, 30)}` : ''}
                  </Text>
                  <Text color={r.confianza === 'baja' ? AMBAR : undefined}>
                    <Text color={TENUE}>estimado · </Text>
                    {r.prevista
                      ? `${r.restantes} hitos restantes → hacia el ${r.prevista} (${r.ritmo ?? '?'}/sem, confianza ${r.confianza})`
                      : `sin previsión · ${r.restantes} hitos restantes`}
                  </Text>
                  {r.motivo !== '' && <Text color={TENUE}>  {cortar(r.motivo, 140)}</Text>}
                  <Text>
                    <Text color={ACENTO}>→ </Text>
                    {r.siguienteFase ? <Text color={TENUE}>{cortar(r.siguienteFase, 30)}: </Text> : null}
                    {cortar(r.siguiente || 'sin siguiente paso', 150)}
                  </Text>
                  {lista.length > 1 && r.avisos > 0 && (
                    <Text color={TENUE}>{r.avisos} aviso(s) en las notas · narrador roadmap {r.nombre}</Text>
                  )}
                  {lista.length === 1 && (
                    <Box flexDirection="column">
                      <Text bold color={ACENTO}> </Text>
                      <Text bold color={DORADO}>◆ PREVISIÓN</Text>
                      <Text>
                        objetivo <Text bold>{r.objetivo || 'sin fecha'}</Text> · previsto{' '}
                        <Text bold>{r.prevista || '—'}</Text>
                        {r.desfase !== null && (
                          <Text color={r.desfase > 0 ? ROJO : VERDE}>
                            {' '}
                            ({r.desfase > 0 ? `${r.desfase} d tarde` : `${-r.desfase} d de margen`})
                          </Text>
                        )}
                      </Text>
                      <Text color={TENUE}>
                        ritmo {r.ritmo ?? '?'} hitos/sem (histórico {r.ritmoHist ?? '?'}) ·{' '}
                        {r.semanasRest ?? '?'} sem restantes · {r.commitsTotal ?? '?'} commits en total
                      </Text>
                      {r.cierres.length > 0 && (
                        <Text color={TENUE}>cerradas en 4 sem: {cortar(r.cierres.join(', '), 120)}</Text>
                      )}

                      <Text bold color={ACENTO}> </Text>
                      <Text bold color={DORADO}>◆ FASES</Text>
                      {r.fases.map(f => {
                        const fb = barra(f.hechos, f.total, 12)
                        const icono =
                          f.estado === 'hecho' ? '✓' : f.estado === 'en-curso' ? '●' : f.estado === 'aparcado' ? '◌' : '○'
                        const color =
                          f.estado === 'hecho' ? VERDE : f.estado === 'en-curso' ? AMBAR : TENUE
                        return (
                          <Box flexDirection="column" marginTop={1}>
                            <Text>
                              <Text color={color}>{icono}</Text>{' '}
                              <Text bold>{cortar(f.nota, 44)}</Text>{' '}
                              <Text color={ACENTO}>{fb.llena}</Text>
                              <Text color={TENUE}>{fb.vacia}</Text>
                              <Text>
                                {' '}
                                {f.hechos}/{f.total}
                              </Text>
                            </Text>
                            <Text color={TENUE}>
                              {'  '}
                              {f.estado}
                              {f.inicio ? ` · desde ${f.inicio}` : ''}
                              {f.objetivo ? ` · objetivo ${f.objetivo}` : ''}
                              {f.cerrado ? ` · cerrada ${f.cerrado}` : ''}
                              {f.responsable ? ` · ${cortar(f.responsable, 24)}` : ''}
                            </Text>
                            {f.estado !== 'hecho' && f.siguiente !== '' && (
                              <Text>
                                {'  '}
                                <Text color={ACENTO}>→ </Text>
                                {cortar(f.siguiente, 160)}
                              </Text>
                            )}
                            {f.estado !== 'hecho' &&
                              f.pendientes.slice(0, 4).map(hito => (
                                <Text color={TENUE}>
                                  {'    '}☐ {cortar(hito, 110)}
                                </Text>
                              ))}
                          </Box>
                        )
                      })}

                      {r.listaAvisos.length > 0 && (
                        <Box flexDirection="column">
                          <Text bold color={ACENTO}> </Text>
                          <Text bold color={DORADO}>◆ AVISOS</Text>
                          {r.listaAvisos.slice(0, 6).map(a => (
                            <Text color={AMBAR}>· {cortar(a, 120)}</Text>
                          ))}
                        </Box>
                      )}
                    </Box>
                  )}
                </Box>
              )}
            </Box>
          )
        })}
      </Box>
    )
  })
}
