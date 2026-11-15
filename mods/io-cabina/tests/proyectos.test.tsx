import { expect, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'

// /cabina agrupa las sesiones vivas por proyecto: la carpeta de primer nivel bajo greedisgood o
// thereisnospoon, con sus subcarpetas y worktrees; lo de fuera, en «otros»; Ío arriba, aparte.

const PANE = (columnas: number) =>
  ({
    plugin: 'io-cabina',
    component: 'Pane',
    requestId: 'cabina',
    props: { title: 'Cabina de Ío', isFocused: false, bodyColumns: columnas, placement: 'dock', scroll: { offset: 0, bodyRows: 80 }, view: {} },
  }) as const

type Salida = { exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean }
const bien = (stdout: string): Salida => ({ exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false })

const VIVAS = `Ío  busy  interactive  ~/Documentos
    sesión b7df17d2  «sin título»
laboratorio-94  idle  interactive  ~/Documentos/thereisnospoon/laboratorio
    sesión d67fbb1f  «sin título»
DSPy y Rasa (plan)  idle  interactive  ~/Documentos/greedisgood/vindam platform
    sesión 4353b89e  «sin título»
io-vindam-dashboard-engine-h8s  busy  background  ~/Documentos/greedisgood/vindam platform/vindam_dashboard_engine/.claude/worktrees/anexo-traspaso
    sesión b4afc81d  «sin título»
io-vindam-dashboard-engine-nh5  idle  background  /home/seppuq/Documentos/greedisgood/vindam platform/vindam_dashboard_engine
    sesión 9d646abb  «sin título»
chatcore-1  blocked (permission)  interactive  ~/Documentos/greedisgood/chatcore-n8n/flujos
    sesión 1a2b3c4d  «sin título»
suelta  idle  interactive  /tmp/pruebas
    sesión 5e6f7a8b  «sin título»
io-io-assistant-3vz (esta)  busy  background  ~/Documentos/thereisnospoon/io-assistant/.claude/worktrees/cabina-por-proyecto
    sesión 4c5f5d9a  «sin título»
`

const preparar: (columnas: number, vivas?: string) => TestBody = (columnas, vivas = VIVAS) => async ($, on) => {
  on('command.register', () => ({ value: { command: '' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => {
    const t = JSON.stringify(e)
    if (t.includes('"sesiones"')) return { value: bien(vivas) }
    return { value: bien('[]') }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
}

const cabeceras = async (ui: { findAll: (q: { type?: string; text?: RegExp }) => Promise<{ text: string }[]> }) =>
  (await ui.findAll({ type: 'Text', text: /^▸ .* · \d+ sesi/ })).map(t => t.text)

test('agrupa por proyecto, con worktrees en su proyecto, «otros» al final y Ío aparte', async ($, on) => {
  await preparar(90)($, on)
  const ui = await $.ui.mount({ ...PANE(90), surface: 'terminal' })
  const grupos = await cabeceras(ui)
  // chatcore-n8n tiene una bloqueada: va primero. io-assistant y vindam platform tienen una ocupada
  // cada una y empatan en actividad: van por nombre. laboratorio, solo en reposo, después.
  expect(grupos.map(g => g.replace(/ ·.*/, ''))).toEqual([
    '▸ chatcore-n8n',
    '▸ io-assistant',
    '▸ vindam platform',
    '▸ laboratorio',
    '▸ otros',
  ])
  expect(grupos[0]).toContain('1 sesión')
  expect(grupos[0]).toContain('1 te espera')
  expect(grupos[2]).toContain('3 sesiones')
  expect(grupos[4]).toContain('1 sesión')
  // La de Ío no cae en ningún grupo: arriba, con su marca.
  expect(await ui.find({ type: 'Button', key: 'ses-b7df17d2' })).toBeTruthy()
  expect((await ui.find({ type: 'Button', key: 'ses-b7df17d2' }))?.text).toContain('✦')
  // El worktree se ve como tal dentro de su proyecto.
  expect((await ui.find({ type: 'Button', key: 'ses-b4afc81d' }))?.text).toContain('⎇ anexo-traspaso')
  expect((await ui.find({ type: 'Button', key: 'ses-4c5f5d9a' }))?.text).toContain('⎇ cabina-por-proyecto')
  // El estado con motivo («blocked (permission)») se sigue leyendo.
  expect((await ui.find({ type: 'Button', key: 'ses-1a2b3c4d' }))?.text).toContain('blocked')
  expect((await ui.find({ type: 'Button', key: 'bloq-1a2b3c4d' }))?.text).toContain('chatcore-n8n')
  await ui.unmount()
})

test('el orden de los grupos sigue la sesión ocupada y la espera, no la carpeta', async ($, on) => {
  const vivas = `alfa-1  idle  interactive  ~/Documentos/thereisnospoon/alfa
    sesión aaaaaaaa  «sin título»
beta-1  busy  interactive  ~/Documentos/thereisnospoon/beta/sub/carpeta
    sesión bbbbbbbb  «sin título»
`
  await preparar(90, vivas)($, on)
  const ui = await $.ui.mount({ ...PANE(90), surface: 'terminal' })
  expect((await cabeceras(ui)).map(g => g.replace(/ ·.*/, ''))).toEqual(['▸ beta', '▸ alfa'])
  // La subcarpeta cuenta como el proyecto y se enseña su último tramo.
  expect((await ui.find({ type: 'Button', key: 'ses-bbbbbbbb' }))?.text).toContain('carpeta')
  await ui.unmount()
})

test('en un panel estrecho el nombre de proyecto largo se recorta con elipsis', async ($, on) => {
  const vivas = `largo-1  idle  interactive  ~/Documentos/greedisgood/un proyecto con un nombre larguísimo de verdad
    sesión cccccccc  «sin título»
`
  await preparar(36, vivas)($, on)
  const ui = await $.ui.mount({ ...PANE(36), surface: 'terminal' })
  const [cabecera] = await cabeceras(ui)
  expect(cabecera).toContain('…')
  expect(cabecera).toContain('1 sesión')
  await ui.unmount()
})
