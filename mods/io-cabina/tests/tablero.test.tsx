import { expect, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'
declare const setTimeout: (hacer: (valor?: unknown) => void, ms?: number) => unknown

const PANE = {
  plugin: 'io-cabina',
  component: 'Pane',
  requestId: 'tablero',
  props: {
    title: 'Tablero',
    isFocused: true,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 60 },
    view: {},
  },
} as const

type Tarjeta = Record<string, unknown>
type Salida = { exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean }

const tarjeta = (id: string, columna: string, extra: Tarjeta = {}): Tarjeta => ({
  id,
  ambito: id.split('--')[0],
  check: id.split('--')[1],
  cliente: id.split('--')[0],
  titulo: 'Chatwoot',
  nivel: 'ambar',
  detalle: ['25 sin asignar más de 4 h'],
  columna,
  marca: null,
  fiabilidad: 'comprobado',
  primera_vez: '2026-11-03',
  ultima_vez: '2026-11-09',
  historial: [{ fecha: '2026-11-03', de: null, a: columna, origen: 'parte' }],
  ...extra,
})

const TARJETAS = [
  tarjeta('vindam--chatwoot', 'nuevos'),
  tarjeta('buscasa--meta_numero', 'nuevos', {
    titulo: 'número de WhatsApp',
    nivel: 'rojo',
    detalle: ['calidad baja', 'límite reducido'],
    marca: 'reabierta',
  }),
  tarjeta('loyal--wf_activo', 'en_curso', { titulo: 'workflow activo', detalle: ['inactivo'] }),
  tarjeta('marlovet--env_permisos', 'dejados', { titulo: 'permisos del .env', detalle: ['644'] }),
  tarjeta('global--openai_saldo', 'resueltos', {
    cliente: 'global',
    titulo: 'saldo de OpenAI',
    fiabilidad: 'estimado',
    detalle: ['quedan 3 días'],
  }),
]

const tablero = (tarjetas: Tarjeta[], extra: Record<string, unknown> = {}) =>
  JSON.stringify({
    existe: true,
    rev: 4,
    parte_fecha: '2026-11-09',
    semaforo: 'rojo',
    puede_deshacer: false,
    ultimo_movimiento: null,
    tarjetas,
    avisos: [],
    ...extra,
  })

const bien = (stdout: string): Salida => ({ exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false })
const espera = (ms = 30) => new Promise(r => setTimeout(r, ms))

// Arranca la sesión con un `narrador` de mentira: `responder` contesta a las órdenes del tablero.
async function arrancar(
  $: Parameters<TestBody>[0],
  on: Parameters<TestBody>[1],
  responder: (orden: string) => Salida,
) {
  const llamadas: string[] = []
  const abiertos: string[] = []
  const avisos: string[] = []
  on('command.register', () => ({ value: { command: '' } }))
  on('ui.open', (_, e) => {
    abiertos.push(JSON.stringify(e))
    return { value: { isPlaced: true } }
  })
  on('ui.toast', (_, e) => {
    avisos.push(JSON.stringify(e))
    return { value: undefined }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => {
    const t = JSON.stringify(e)
    if (!t.includes('"tablero"')) return { value: bien('[]') }
    llamadas.push(t)
    return { value: responder(t) }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await espera()
  return { llamadas, abiertos, avisos }
}

test('la pestaña se abre sola al arrancar y lee el tablero local', async ($, on) => {
  const { llamadas, abiertos } = await arrancar($, on, () => bien(tablero(TARJETAS)))
  expect(abiertos.some(a => a.includes('"id":"tablero"') && a.includes('"title":"Tablero"'))).toBe(true)
  expect(llamadas.some(l => l.includes('"ver"') && l.includes('"--json"'))).toBe(true)
})

test('cuatro columnas con nivel, cliente y detalle de cada tarjeta', async ($, on) => {
  await arrancar($, on, () => bien(tablero(TARJETAS)))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /NUEVOS/ }))?.text).toContain('2')
  expect((await ui.find({ type: 'Text', text: /EN CURSO/ }))?.text).toContain('1')
  expect((await ui.find({ type: 'Text', text: /DEJADOS DE LADO/ }))?.text).toContain('1')
  expect((await ui.find({ type: 'Text', text: /RESUELTOS/ }))?.text).toContain('1')
  expect(await ui.find({ type: 'Button', key: 'tarjeta-vindam--chatwoot' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'tarjeta-buscasa--meta_numero' })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /buscasa/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /número de WhatsApp/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /calidad baja/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /reabierta/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /parte del 2026-11-09/ })).toBeTruthy()
  // sin nada seleccionado no hay botones de mover ni de deshacer
  expect(await ui.find({ type: 'Button', key: 'mover-en_curso' })).toBeFalsy()
  expect(await ui.find({ type: 'Button', key: 'deshacer' })).toBeFalsy()
  await ui.unmount()
})

test('pulsar una tarjeta la despliega y un botón la mueve con origen mod', async ($, on) => {
  const movidas = TARJETAS.map(t => (t.id === 'vindam--chatwoot' ? { ...t, columna: 'en_curso' } : t))
  const { llamadas, avisos } = await arrancar($, on, orden =>
    orden.includes('"mover"')
      ? bien(tablero(movidas, { rev: 5, puede_deshacer: true }))
      : bien(tablero(TARJETAS)),
  )
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tarjeta-vindam--chatwoot' })
  await espera()
  expect(await ui.find({ type: 'Button', key: 'mover-en_curso' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'mover-dejados' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'mover-resueltos' })).toBeTruthy()
  // la columna en la que ya está no se ofrece
  expect(await ui.find({ type: 'Button', key: 'mover-nuevos' })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /desde el 2026-11-03/ })).toBeTruthy()

  await ui.press({ key: 'mover-en_curso' })
  await espera()
  const mover = llamadas.find(l => l.includes('"mover"'))
  expect(mover).toBeTruthy()
  expect(mover).toContain('"mover","vindam--chatwoot","en_curso","--origen","mod","--desde","nuevos"')
  expect((await ui.find({ type: 'Text', text: /EN CURSO/ }))?.text).toContain('2')
  expect((await ui.find({ type: 'Text', text: /NUEVOS/ }))?.text).toContain('1')
  expect(await ui.find({ type: 'Button', key: 'deshacer' })).toBeTruthy()
  expect(avisos.some(a => a.includes('en curso'))).toBe(true)
  await ui.unmount()
})

test('cerrar una tarjeta es moverla a resueltos', async ($, on) => {
  const { llamadas } = await arrancar($, on, () => bien(tablero(TARJETAS)))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tarjeta-loyal--wf_activo' })
  await espera()
  await ui.press({ key: 'mover-resueltos' })
  await espera()
  expect(
    llamadas.some(l => l.includes('"mover","loyal--wf_activo","resueltos","--origen","mod","--desde","en_curso"')),
  ).toBe(true)
  await ui.unmount()
})

test('deshacer llama a la orden y repinta', async ($, on) => {
  const { llamadas, avisos } = await arrancar($, on, orden =>
    orden.includes('"deshacer"')
      ? bien(
          tablero(TARJETAS, {
            deshecho: { id: 'vindam--chatwoot', cliente: 'vindam', titulo: 'Chatwoot', de: 'en_curso', a: 'nuevos' },
          }),
        )
      : bien(tablero(TARJETAS, { puede_deshacer: true })),
  )
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'deshacer' })
  await espera()
  expect(llamadas.some(l => l.includes('"deshacer","--origen","mod"'))).toBe(true)
  expect(await ui.find({ type: 'Button', key: 'deshacer' })).toBeFalsy()
  expect(avisos.some(a => a.includes('Deshecho'))).toBe(true)
  await ui.unmount()
})

test('si la tarjeta cambió mientras tanto, avisa y vuelve a leer', async ($, on) => {
  const { llamadas, avisos } = await arrancar($, on, orden =>
    orden.includes('"mover"')
      ? { exitCode: 4, stdout: '', stderr: 'tablero: vindam--chatwoot ya no está en nuevos, está en resueltos', isStdoutTruncated: false, isStderrTruncated: false }
      : bien(tablero(TARJETAS)),
  )
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tarjeta-vindam--chatwoot' })
  await espera()
  const antes = llamadas.filter(l => l.includes('"ver"')).length
  await ui.press({ key: 'mover-en_curso' })
  await espera()
  expect(llamadas.filter(l => l.includes('"ver"')).length).toBeGreaterThan(antes)
  expect(avisos.some(a => a.includes('cambió mientras tanto'))).toBe(true)
  await ui.unmount()
})

test('si el archivo no se puede leer, el fallo se ve en el panel', async ($, on) => {
  await arrancar($, on, () => ({ exitCode: 3, stdout: '', stderr: 'tablero: ArchivoRoto: no es JSON', isStdoutTruncated: false, isStderrTruncated: false }))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /ArchivoRoto/ }))?.text).toContain('salió con 3')
  await ui.unmount()
})

test('sin tablero todavía lo dice, sin columnas vacías', async ($, on) => {
  await arrancar($, on, () => bien(tablero([], { existe: false, rev: 0, parte_fecha: null, semaforo: 'verde' })))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /No hay tablero todavía/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /NUEVOS/ })).toBeFalsy()
  await ui.unmount()
})

test('el texto de una tarjeta se recorta y los resueltos se limitan a cinco', async ($, on) => {
  const muchas = Array.from({ length: 8 }, (_, i) =>
    tarjeta(`c${i}--tls`, 'resueltos', { ultima_vez: `2026-11-0${i + 1}`, titulo: `certificado ${i}` }),
  )
  await arrancar($, on, () => bien(tablero(muchas)))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /RESUELTOS/ }))?.text).toContain('8')
  expect(await ui.find({ type: 'Button', key: 'tarjeta-c7--tls' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'tarjeta-c0--tls' })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /3 más/ })).toBeTruthy()
  await ui.unmount()
})
