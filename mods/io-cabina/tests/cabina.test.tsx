import { expect, test } from 'claude-code/testing'
declare const setTimeout: (hacer: (valor?: unknown) => void, ms?: number) => unknown

const PANE = {
  plugin: 'io-cabina',
  component: 'Pane',
  requestId: 'cabina',
  props: { title: 'Cabina de Ío', isFocused: false, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
} as const

const VIVAS = `io-io-assistant-171558  blocked  background  ~/Documentos/thereisnospoon/io-assistant
    sesión 29f65fb3  «sin título»
Ío (esta)  busy  interactive  ~/Documentos
    sesión c2b4b9b8  «sin título»
`

test('las sesiones son botones que abren la sesión', async ($, on) => {
  const llamadas: string[] = []
  on('command.register', () => ({ value: { command: '' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => {
    const t = JSON.stringify(e)
    llamadas.push(t)
    if (t.includes('"sesiones"')) return { value: { exitCode: 0, stdout: VIVAS, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    if (t.includes('"abrir"')) return { value: { exitCode: 0, stdout: 'abierta', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    return { value: { exitCode: 0, stdout: '[]', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const boton = await ui.find({ type: 'Button', key: 'bloq-29f65fb3' })
  expect(boton).toBeTruthy()
  await ui.press({ key: 'bloq-29f65fb3' })
  await new Promise(r => setTimeout(r, 20))
  expect(llamadas.some(l => l.includes('"abrir"') && l.includes('29f65fb3'))).toBe(true)
  await ui.unmount()
})
