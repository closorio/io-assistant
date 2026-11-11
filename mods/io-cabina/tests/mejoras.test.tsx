import { expect, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'
declare const setTimeout: (hacer: (valor?: unknown) => void, ms?: number) => unknown

// Pruebas de las cuatro mejoras: puertas con botones, franja sobre el prompt, tonos y herramientas.

const SESION_IO = '5b7ad123-838e-4043-896f-43d896860612'
const NARR = '/home/seppuq/.local/share/narrador'

type Salida = { exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean }
const bien = (stdout: string): Salida => ({ exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false })
const espera = (ms = 40) => new Promise(r => setTimeout(r, ms))

const PANE = (requestId: string, title: string) =>
  ({
    plugin: 'io-cabina',
    component: 'Pane',
    requestId,
    props: { title, isFocused: true, bodyColumns: 90, placement: 'dock', scroll: { offset: 0, bodyRows: 60 }, view: {} },
  }) as const

const FRANJA = {
  plugin: 'io-cabina',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isCollapsed: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 160,
    scroll: { offset: 0, bodyRows: 10 },
    view: {},
  },
} as const

const puerta = (id: string, estado: string, extra: Record<string, unknown> = {}) => ({
  id,
  titulo: 'Push de la rama de la cabina',
  comando: 'git push origin feat/cabina',
  coste: '0 €',
  vuelta: 'git push --delete origin feat/cabina',
  proyecto: 'io-assistant',
  estado,
  creada: '2026-11-10T20:00:00',
  respondida: null,
  origen: null,
  ...extra,
})

// Un mundo de mentira que cada prueba puede cambiar entre vueltas del sondeo.
type Mundo = {
  sesionId: string
  vivas: string
  vivasCodigo: number
  permisos: string
  puertas: unknown[]
  trabajadores: unknown[]
  informes: Record<string, number>
  alertas: string
  usd: number | null
  responder: (orden: string[]) => Salida
}

const mundo = (cambios: Partial<Mundo> = {}): Mundo => ({
  sesionId: SESION_IO,
  vivas: '',
  vivasCodigo: 0,
  permisos: '[]',
  puertas: [],
  trabajadores: [],
  informes: {},
  alertas: '',
  usd: null,
  responder: () => bien(''),
  ...cambios,
})

async function arrancar(
  $: Parameters<TestBody>[0],
  on: Parameters<TestBody>[1],
  m: Mundo,
) {
  const ordenes: string[][] = []
  const avisos: string[] = []
  const enviados: string[] = []
  const herramientas: string[] = []
  on('command.register', () => ({ value: { command: '' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', (_, e) => {
    avisos.push(JSON.stringify(e))
    return { value: undefined }
  })
  on('tool.register', (_, e) => {
    herramientas.push(String((e as { name?: string }).name))
    return { value: { tool: `mcp__io-cabina__${(e as { name?: string }).name}` } }
  })
  on('prompt.submit', (_, e) => {
    enviados.push(e.text)
    return { text: e.text }
  })
  on('session.id', () => ({ value: m.sesionId }))
  on('session.usage', () => {
    if (m.usd === null) throw new Error('sin cuenta')
    return { value: { startedAt: 0, rateLimits: [], cost: { usd: m.usd } } as never }
  })
  on('fs.read', (_, e) => {
    if (e.path === `${NARR}/io.json`) return { value: JSON.stringify({ session_id: SESION_IO }) }
    if (e.path === `${NARR}/trabajadores.json`) return { value: JSON.stringify(m.trabajadores) }
    if (e.path === `${NARR}/cabina/alertas.jsonl`) return { value: m.alertas }
    throw new Error(`ENOENT ${e.path}`)
  })
  on('fs.stat', (_, e) => {
    const informe = /\/trabajadores\/(.+)\.md$/.exec(e.path)?.[1]
    if (informe && m.informes[informe]) {
      return { value: { kind: 'file', size: m.informes[informe], mtimeMs: 0, isLink: false } }
    }
    throw new Error(`ENOENT ${e.path}`)
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => {
    const argv = [...((e as { argv: readonly string[] }).argv ?? [])].slice(1)
    ordenes.push(argv)
    const t = argv.join(' ')
    if (t.startsWith('sesiones --vivas')) return { value: { exitCode: m.vivasCodigo, stdout: m.vivas, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    if (t.startsWith('permisos --json')) return { value: bien(m.permisos) }
    if (t.startsWith('puerta lista')) return { value: bien(JSON.stringify({ puertas: m.puertas })) }
    if (t.startsWith('tablero')) return { value: bien(JSON.stringify({ existe: false, tarjetas: [] })) }
    if (t.startsWith('roadmap')) return { value: { exitCode: 2, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    return { value: m.responder(argv) }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await espera()
  const tonos = () => ordenes.filter(o => o[0] === 'tono').map(o => o[1])
  return { ordenes, avisos, enviados, herramientas, tonos }
}

// --- 1. puertas con botones --------------------------------------------------------------

test('la pestaña de puertas enseña comando, coste y vuelta atrás, con Sí y No', async ($, on) => {
  await arrancar($, on, mundo({ puertas: [puerta('k3m', 'abierta'), puerta('p7z', 'si', { titulo: 'Gasto de corridas' })] }))
  const ui = await $.ui.mount({ ...PANE('puertas', 'Puertas'), surface: 'terminal' })
  expect(await ui.find({ type: 'Button', key: 'si-k3m' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'no-k3m' })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /git push origin feat\/cabina/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /vuelta atrás/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /coste 0 €/ })).toBeTruthy()
  // la ya respondida no tiene botones: espera a que Ío la ejecute y la cierre
  expect(await ui.find({ type: 'Button', key: 'si-p7z' })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /RESPONDIDAS/ })).toBeTruthy()
  await ui.unmount()

  const cabina = await $.ui.mount({ ...PANE('cabina', 'Cabina de Ío'), surface: 'terminal' })
  expect(await cabina.find({ type: 'Button', key: 'si-k3m' })).toBeTruthy()
  await cabina.unmount()
})

test('Sí lo anota con origen cabina y se lo pasa a Ío, sin ejecutar el comando', async ($, on) => {
  const m = mundo({ puertas: [puerta('k3m', 'abierta')] })
  m.responder = argv =>
    argv[0] === 'puerta' && argv[1] === 'responder'
      ? bien('[puerta k3m] sí a «Push de la rama de la cabina» (desde cabina). Nada se ha ejecutado.')
      : bien('')
  const { ordenes, enviados, avisos } = await arrancar($, on, m)
  const ui = await $.ui.mount({ ...PANE('puertas', 'Puertas'), surface: 'terminal' })
  m.puertas = [puerta('k3m', 'si')]
  await ui.press({ key: 'si-k3m' })
  await espera()
  expect(ordenes.some(o => o.join(' ') === 'puerta responder k3m si --origen cabina')).toBe(true)
  // ninguna orden lleva el comando de la puerta: la cabina no lo ejecuta
  expect(ordenes.some(o => o.some(a => a.includes('git push')))).toBe(false)
  expect(enviados).toEqual(['[puerta k3m] sí a «Push de la rama de la cabina» (desde cabina). Nada se ha ejecutado.'])
  expect(avisos.some(a => a.includes('no ejecuta nada'))).toBe(true)
  expect(await ui.find({ type: 'Button', key: 'si-k3m' })).toBeFalsy()
  await ui.unmount()
})

test('No también se anota y se le pasa a Ío', async ($, on) => {
  const m = mundo({ puertas: [puerta('k3m', 'abierta')] })
  m.responder = argv => (argv[1] === 'responder' ? bien('[puerta k3m] no a «Push».') : bien(''))
  const { ordenes, enviados } = await arrancar($, on, m)
  const ui = await $.ui.mount({ ...PANE('puertas', 'Puertas'), surface: 'terminal' })
  await ui.press({ key: 'no-k3m' })
  await espera()
  expect(ordenes.some(o => o.join(' ') === 'puerta responder k3m no --origen cabina')).toBe(true)
  expect(enviados).toEqual(['[puerta k3m] no a «Push».'])
  await ui.unmount()
})

test('una puerta que ya tenía respuesta avisa y no manda nada a Ío', async ($, on) => {
  const m = mundo({ puertas: [puerta('k3m', 'abierta')] })
  m.responder = argv => (argv[1] === 'responder' ? { exitCode: 4, stdout: '', stderr: 'ya no está abierta', isStdoutTruncated: false, isStderrTruncated: false } : bien(''))
  const { enviados, avisos } = await arrancar($, on, m)
  const ui = await $.ui.mount({ ...PANE('puertas', 'Puertas'), surface: 'terminal' })
  await ui.press({ key: 'si-k3m' })
  await espera()
  expect(enviados).toEqual([])
  expect(avisos.some(a => a.includes('ya tenía respuesta'))).toBe(true)
  await ui.unmount()
})

test('fuera de la sesión de Ío el sí se anota pero no se manda a ninguna sesión', async ($, on) => {
  const m = mundo({ sesionId: 'otra-sesion', puertas: [puerta('k3m', 'abierta')] })
  m.responder = argv => (argv[1] === 'responder' ? bien('[puerta k3m] sí') : bien(''))
  const { ordenes, enviados } = await arrancar($, on, m)
  const ui = await $.ui.mount({ ...PANE('puertas', 'Puertas'), surface: 'terminal' })
  await ui.press({ key: 'si-k3m' })
  await espera()
  expect(ordenes.some(o => o.join(' ') === 'puerta responder k3m si --origen cabina')).toBe(true)
  expect(enviados).toEqual([])
  await ui.unmount()
})

// --- 2. franja sobre el prompt -------------------------------------------------------------

const ahora = () => Date.now() / 1000
const lanzado = (nombre: string, tarea: string, extra: Record<string, unknown> = {}) => ({
  nombre,
  ruta: '/home/seppuq/Documentos/thereisnospoon/motor',
  tarea,
  contrato: true,
  modelo: null,
  inicio: ahora() - 600,
  tipo: 'bg',
  ...extra,
})

test('la franja enseña trabajadores por id, esperas, puertas y el gasto de la sesión', async ($, on) => {
  await arrancar(
    $,
    on,
    mundo({
      vivas: 'io-motor-k7q  busy  background  ~/Documentos/thereisnospoon/motor\n    sesión 11111111  «x»\n',
      trabajadores: [
        lanzado('io-motor-k7q', 'Arreglar el login del panel y sus pruebas'),
        lanzado('io-motor-m4z', 'Ya terminado', { inicio: ahora() - 900 }),
      ],
      permisos: JSON.stringify([{ nombre: 'buscasa', carpeta: '~/x', motivo: 'un permiso' }]),
      puertas: [puerta('k3m', 'abierta')],
      usd: 1.5,
    }),
  )
  const ui = await $.ui.mount({ ...FRANJA, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /k7q/ }))?.text).toContain('Arreglar el login')
  expect(await ui.find({ type: 'Text', text: /m4z/ })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /1 esperan permiso/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /puerta: Push de la rama/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /sesión 1,50 \$/ })).toBeTruthy()
  await ui.unmount()
})

test('un trabajador con su informe escrito ya no sale como en marcha', async ($, on) => {
  await arrancar(
    $,
    on,
    mundo({
      vivas: 'io-motor-k7q  busy  background  ~/x\n',
      trabajadores: [lanzado('io-motor-k7q', 'tarea')],
      informes: { 'io-motor-k7q': 120 },
      puertas: [puerta('k3m', 'abierta')],
    }),
  )
  const ui = await $.ui.mount({ ...FRANJA, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /k7q/ })).toBeFalsy()
  await ui.unmount()
})

test('sin nada en marcha la franja no sale', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>motor</Text>
  })
  await arrancar($, on, mundo({ usd: 2 }))
  const ui = await $.ui.mount({ ...FRANJA, surface: 'terminal' })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('motor')
  await ui.unmount()
})

// --- 3. tonos --------------------------------------------------------------------------------

test('al arrancar no suena nada aunque ya haya puertas y trabajadores', async ($, on) => {
  const { tonos } = await arrancar(
    $,
    on,
    mundo({
      vivas: 'io-motor-k7q  busy  background  ~/x\n',
      trabajadores: [lanzado('io-motor-k7q', 'tarea')],
      puertas: [puerta('k3m', 'abierta')],
      alertas: JSON.stringify({ id: 'a1', ts: 1, nivel: 'rojo', texto: 'caído' }),
    }),
  )
  expect(tonos()).toEqual([])
})

test('suena «terminado» cuando un trabajador deja de estar en marcha', async ($, on) => {
  const m = mundo({ vivas: 'io-motor-k7q  busy  background  ~/x\n', trabajadores: [lanzado('io-motor-k7q', 'tarea')] })
  const { tonos } = await arrancar($, on, m)
  m.vivas = 'io-motor-k7q  idle  background  ~/x\n'
  await $.command.run({ command: 'cabina' } as never)
  await espera()
  expect(tonos()).toEqual(['terminado'])
})

test('si no se pudieron leer las sesiones, no suena como si todos hubieran terminado', async ($, on) => {
  const m = mundo({ vivas: 'io-motor-k7q  busy  background  ~/x\n', trabajadores: [lanzado('io-motor-k7q', 'tarea')] })
  const { tonos } = await arrancar($, on, m)
  m.vivas = ''
  m.vivasCodigo = 1
  await $.command.run({ command: 'cabina' } as never)
  await espera()
  expect(tonos()).toEqual([])
})

test('una puerta nueva suena «puerta» y una alerta roja nueva, «error» (uno por vuelta)', async ($, on) => {
  const m = mundo()
  const { tonos } = await arrancar($, on, m)
  m.puertas = [puerta('k3m', 'abierta')]
  await $.command.run({ command: 'cabina' } as never)
  await espera()
  expect(tonos()).toEqual(['puerta'])
  m.puertas = [puerta('k3m', 'abierta'), puerta('q2w', 'abierta')]
  m.alertas = JSON.stringify({ id: 'a1', ts: 1, nivel: 'rojo', texto: 'caído' })
  await $.command.run({ command: 'cabina' } as never)
  await espera()
  expect(tonos()).toEqual(['puerta', 'error'])
})

// --- 4. herramientas para Ío ---------------------------------------------------------------

test('en la sesión de Ío registra sus herramientas, y no trabajador_esperar', async ($, on) => {
  const { herramientas } = await arrancar($, on, mundo())
  expect(herramientas.sort()).toEqual(['permisos', 'puerta_anadir', 'sesiones_vivas', 'trabajador_lanzar', 'trabajador_lista'])
})

test('fuera de la sesión de Ío no registra ninguna y las niega', async ($, on) => {
  const { herramientas, ordenes } = await arrancar($, on, mundo({ sesionId: 'otra' }))
  expect(herramientas).toEqual([])
  const r = await $.tool.call({ tool: 'mcp__io-cabina__trabajador_lista' } as never)
  expect(JSON.stringify(r)).toContain('solo de la sesión de Ío')
  expect(ordenes.some(o => o[0] === 'trabajador')).toBe(false)
})

test('trabajador_lanzar llama a narrador con contrato y recuerda vigilarlo', async ($, on) => {
  const m = mundo()
  m.responder = argv =>
    argv[0] === 'trabajador' ? bien('trabajador io-motor-k7q lanzado en segundo plano en ~/x') : bien('')
  const { ordenes } = await arrancar($, on, m)
  const r = await $.tool.call({ tool: 'mcp__io-cabina__trabajador_lanzar', proyecto: 'motor', tarea: 'haz X', modelo: 'opus' } as never)
  expect(ordenes).toContainEqual(['trabajador', 'lanzar', 'motor', 'haz X', '--modelo', 'opus', '--contrato'])
  expect(JSON.stringify(r)).toContain('narrador trabajador esperar io-motor-k7q')
})

test('trabajador_lanzar sin contrato si se pide, y un fallo vuelve como error', async ($, on) => {
  const m = mundo()
  m.responder = argv => (argv[0] === 'trabajador' ? { exitCode: 1, stdout: '', stderr: 'no encuentro el proyecto', isStdoutTruncated: false, isStderrTruncated: false } : bien(''))
  const { ordenes } = await arrancar($, on, m)
  const r = await $.tool.call({ tool: 'mcp__io-cabina__trabajador_lanzar', proyecto: 'nada', tarea: 't', contrato: false } as never)
  expect(ordenes).toContainEqual(['trabajador', 'lanzar', 'nada', 't'])
  expect(JSON.stringify(r)).toContain('no encuentro el proyecto')
  expect(JSON.stringify(r)).toContain('isError')
})

test('puerta_anadir, permisos, sesiones_vivas y trabajador_lista llaman a su orden', async ($, on) => {
  const m = mundo()
  m.responder = argv => (argv[0] === 'puerta' ? bien('k3m') : bien(`salida de ${argv[0]}`))
  const { ordenes } = await arrancar($, on, m)
  const r = await $.tool.call({
    tool: 'mcp__io-cabina__puerta_anadir',
    titulo: 'Push',
    comando: 'git push origin x',
    coste: '0 €',
  } as never)
  expect(ordenes).toContainEqual(['puerta', 'añadir', 'Push', '--comando', 'git push origin x', '--coste', '0 €'])
  expect(JSON.stringify(r)).toContain('Puerta k3m registrada')
  await $.tool.call({ tool: 'mcp__io-cabina__permisos' } as never)
  await $.tool.call({ tool: 'mcp__io-cabina__trabajador_lista' } as never)
  expect(ordenes).toContainEqual(['permisos'])
  expect(ordenes).toContainEqual(['trabajador', 'lista'])
  // sesiones_vivas usa la misma orden que el sondeo
  await $.tool.call({ tool: 'mcp__io-cabina__sesiones_vivas' } as never)
  expect(ordenes.filter(o => o.join(' ') === 'sesiones --vivas').length).toBeGreaterThan(1)
})
