import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'io-cabina',
  component: 'Pane',
  requestId: 'roadmap',
  props: {
    title: 'Roadmap',
    isFocused: false,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const JSON_ROADMAP = JSON.stringify({
  proyectos: [
    {
      nombre: 'project-soma',
      error: '',
      semaforo: 'sin_objetivo',
      deriva_texto: 'sin fecha objetivo',
      medido: {
        hitos_hechos: 6,
        hitos_total: 10,
        avance_pct: 60,
        siguiente: 'medir F7.6',
        siguiente_fase: 'F7',
        responsable: 'seppuq',
        ultimo_movimiento: '2026-11-07',
        dias_sin_tocar: 2,
        commits_4_semanas: 120,
      },
      estimado: {
        fecha_prevista: '2026-12-20',
        confianza: 'baja',
        ritmo_hitos_semana: 0.7,
        hitos_restantes: 4,
        motivo: 'pocos datos: ninguna fase con fecha de cierre',
      },
      avisos: [],
    },
    {
      nombre: 'holo-ui',
      error: 'sin vault: falta /x/conocimiento/roadmap',
      semaforo: 'sin_objetivo',
      deriva_texto: '',
      medido: null,
      estimado: null,
      avisos: [],
    },
    {
      nombre: 'vindam',
      error: '',
      semaforo: 'rojo',
      deriva_texto: '20 días tarde (F2)',
      medido: { hitos_hechos: 1, hitos_total: 4, avance_pct: 25, siguiente: 'cerrar F2' },
      estimado: { fecha_prevista: '', hitos_restantes: 3, motivo: '' },
      avisos: ['x'],
    },
  ],
})

type Salida = { exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean }

test('una tarjeta por proyecto, con deriva, estimación y errores dentro', async ($, on) => {
  const salida: Salida = { exitCode: 0, stdout: JSON_ROADMAP, stderr: '', isStdoutTruncated: false, isStderrTruncated: false }
  on('command.register', () => ({ value: { command: '' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => ({
    value: JSON.stringify(e).includes('roadmap') ? salida : { exitCode: 0, stdout: '[]', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  }))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /sin fecha objetivo/ }))?.text).toContain('sin fecha objetivo')
  expect((await ui.find({ type: 'Text', text: /6\/10 hitos/ }))?.text).toContain('60 %')
  expect((await ui.find({ type: 'Text', text: /hacia el 2026-12-20/ }))?.text).toContain('confianza baja')
  expect((await ui.find({ type: 'Text', text: /sin vault/ }))?.text).toContain('sin vault')
  expect((await ui.find({ type: 'Text', text: /20 días tarde/ }))?.text).toContain('F2')
  expect((await ui.find({ type: 'Text', text: /medir F7.6/ }))?.text).toContain('medir F7.6')
  await ui.unmount()
})

test('si la orden falla, el fallo se ve en el panel', async ($, on) => {
  const salida: Salida = { exitCode: 3, stdout: '', stderr: 'roadmap: boom', isStdoutTruncated: false, isStderrTruncated: false }
  on('command.register', () => ({ value: { command: '' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => ({
    value: JSON.stringify(e).includes('roadmap') ? salida : { exitCode: 0, stdout: '[]', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  }))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /boom/ }))?.text).toContain('salió con 3')
  await ui.unmount()
})

test('fijado en un proyecto: vista detallada por fases', async ($, on) => {
  const datos = "{\n  \"generado\": \"2026-11-09T19:17:50\",\n  \"hoy\": \"2026-11-09\",\n  \"activo\": null,\n  \"proyectos\": [\n    {\n      \"nombre\": \"vindam_dashboard_engine\",\n      \"ruta\": \"/home/seppuq/Documentos/greedisgood/vindam platform/vindam_dashboard_engine\",\n      \"vault\": \"/home/seppuq/Documentos/greedisgood/vindam platform/vindam_dashboard_engine/conocimiento\",\n      \"error\": \"\",\n      \"semaforo\": \"verde\",\n      \"deriva_texto\": \"en fecha (objetivo 2027-02-27)\",\n      \"medido\": {\n        \"hitos_hechos\": 65,\n        \"hitos_total\": 113,\n        \"avance_pct\": 58,\n        \"fases\": {\n          \"hecho\": 2,\n          \"en-curso\": 4,\n          \"pendiente\": 0,\n          \"aparcado\": 1\n        },\n        \"fases_total\": 7,\n        \"deriva_dias\": null,\n        \"deriva_fase\": null,\n        \"fecha_objetivo\": \"2027-02-27\",\n        \"fases_con_objetivo\": 1,\n        \"cierres_con_desfase\": [],\n        \"cierres_4_semanas\": [\n          {\n            \"nota\": \"F0 Higiene\",\n            \"cerrado\": \"2026-10-24\"\n          },\n          {\n            \"nota\": \"F1 Medir el motor\",\n            \"cerrado\": \"2026-10-24\"\n          }\n        ],\n        \"commits_4_semanas\": 296,\n        \"commits_total\": 1330,\n        \"ultimo_movimiento\": \"2026-11-09\",\n        \"ultimo_movimiento_texto\": \"Merge branch 'fix/anonimizador-asesores-y-sobremarcado' into develop (anonimizador v9: asesores con <ASESOR_n>, menos sobremarcado y menos r\",\n        \"dias_sin_tocar\": 0,\n        \"cambios_sin_commit\": 0,\n        \"ultima_nota_actualizada\": \"2026-11-09\",\n        \"responsable\": \"\",\n        \"siguiente\": \"Piloto con Buscador Casa (escalones en F2); K3 exige 14 d\u00edas al 100 % por cliente, as\u00ed que K entra al final de F3, cliente a cliente\",\n        \"siguiente_fase\": \"Conmutaci\u00f3n de clientes y retiro de n8n\"\n      },\n      \"estimado\": {\n        \"hitos_restantes\": 48,\n        \"desde\": \"2026-03-02\",\n        \"semanas_de_historia\": 36.0,\n        \"ritmo_hitos_semana\": 3.61,\n        \"ritmo_historico_semana\": 1.81,\n        \"factor_actividad\": 2.0,\n        \"semanas_restantes\": 13.3,\n        \"fecha_prevista\": \"2027-02-10\",\n        \"desfase_dias\": -17,\n        \"confianza\": \"alta\",\n        \"pocos_datos\": false,\n        \"motivo\": \"\"\n      },\n      \"avisos\": [],\n      \"notas\": [\n        {\n          \"nota\": \"Conmutaci\u00f3n de clientes y retiro de n8n\",\n          \"fase\": \"PT-J-K\",\n          \"estado\": \"en-curso\",\n          \"responsable\": \"\",\n          \"inicio\": null,\n          \"objetivo\": \"2027-02-27\",\n          \"cerrado\": null,\n          \"actualizado\": \"2026-11-09\",\n          \"hitos_total\": 14,\n          \"hitos_hechos\": 6,\n          \"siguiente\": \"Piloto con Buscador Casa (escalones en F2); K3 exige 14 d\u00edas al 100 % por cliente, as\u00ed que K entra al final de F3, cliente a cliente\",\n          \"pendientes\": [\n            \"Buscador Casa conmutado (piloto; sus escalones est\u00e1n en [[F2 Bloqueantes de la conmutaci\u00f3n]])\",\n            \"Vindam conmutado (J0; aparcado el 3-11 porque cambian los precios de VIMY)\",\n            \"Marlovet conmutado (J1; en pausa)\",\n            \"Loyal conmutado (J3; el 7-11 se adelanta como corpus sin conexi\u00f3n)\",\n            \"K0\",\n            \"K3 \u00b7 14 d\u00edas al 100 % por cliente\"\n          ]\n        },\n        {\n          \"nota\": \"F0 Higiene\",\n          \"fase\": \"F0\",\n          \"estado\": \"hecho\",\n          \"responsable\": \"\",\n          \"inicio\": \"2026-10-23\",\n          \"objetivo\": null,\n          \"cerrado\": \"2026-10-24\",\n          \"actualizado\": \"2026-11-09\",\n          \"hitos_total\": 2,\n          \"hitos_hechos\": 1,\n          \"siguiente\": \"Pedir a la f\u00e1brica que corrija el horario de su faq.csv (8:30 frente a 9:00); se hace en chatcore-n8n\",\n          \"pendientes\": [\n            \"Pedir a la f\u00e1brica que corrija el horario de su `faq.csv` antes de congelar el corpus\"\n          ]\n        },\n        {\n          \"nota\": \"F1 Medir el motor\",\n          \"fase\": \"F1\",\n          \"estado\": \"hecho\",\n          \"responsable\": \"\",\n          \"inicio\": \"2026-10-24\",\n          \"objetivo\": null,\n          \"cerrado\": \"2026-10-24\",\n          \"actualizado\": \"2026-11-09\",\n          \"hitos_total\": 6,\n          \"hitos_hechos\": 6,\n          \"siguiente\": \"\",\n          \"pendientes\": []\n        },\n        {\n          \"nota\": \"F2 Bloqueantes de la conmutaci\u00f3n\",\n          \"fase\": \"F2\",\n          \"estado\": \"en-curso\",\n          \"responsable\": \"\",\n          \"inicio\": \"2026-10-24\",\n          \"objetivo\": null,\n          \"cerrado\": null,\n          \"actualizado\": \"2026-11-09\",\n          \"hitos_total\": 16,\n          \"hitos_hechos\": 11,\n          \"siguiente\": \"Escal\u00f3n 1 sin conexi\u00f3n: censo y corpus de Loyal (preparados el 7-11; los lanza o autoriza el usuario) y corpus de Buscador Casa; t78 sigue abierta\",\n          \"pendientes\": [\n            \"t55 \u00b7 el motor como paquete instalable (fase 3 en el main de la app el 31-10; producci\u00f3n publicaba 0.15.0 el 2-11; PR de 0.17.0 sin abrir)\",\n            \"t78 \u00b7 consentimiento bloqueante (c\u00f3digo en 0.18.0 y 0.18.1, 04-11; la tarea sigue `vigente`)\",\n            \"Escal\u00f3n 1 \u00b7 corpus sin conexi\u00f3n, con divergencias explicadas\",\n            \"Escal\u00f3n 2 \u00b7 sombra en vivo sin divergencias cr\u00edticas (exige la orden directa del usuario)\",\n            \"Escal\u00f3n 3 \u00b7 activo por porcentaje (exige la orden directa del usuario)\"\n          ]\n        },\n        {\n          \"nota\": \"F3 Antes del 100 %\",\n          \"fase\": \"F3\",\n          \"estado\": \"en-curso\",\n          \"responsable\": \"\",\n          \"inicio\": \"2026-10-24\",\n          \"objetivo\": null,\n          \"cerrado\": null,\n          \"actualizado\": \"2026-11-09\",\n          \"hitos_total\": 32,\n          \"hitos_hechos\": 25,\n          \"siguiente\": \"Cerrar los P1 abiertos: t09, t05, t06, t11, t27, t42 y t67\",\n          \"pendientes\": [\n            \"t09 \u00b7 aclarar una vez con confianza baja\",\n            \"t27 \u00b7 el contenido nunca borra\",\n            \"t05 \u00b7 textos can\u00f3nicos con aprobaci\u00f3n\",\n            \"t06 \u00b7 price mode y anclaje\",\n            \"t11 \u00b7 l\u00e9xico ejecutable\",\n            \"t67 \u00b7 verticales desde la f\u00e1brica\"\n          ]\n        },\n        {\n          \"nota\": \"F4 Calidad\",\n          \"fase\": \"F4\",\n          \"estado\": \"en-curso\",\n          \"responsable\": \"\",\n          \"inicio\": \"2026-10-24\",\n          \"objetivo\": null,\n          \"cerrado\": null,\n          \"actualizado\": \"2026-11-09\",\n          \"hitos_total\": 27,\n          \"hitos_hechos\": 6,\n          \"siguiente\": \"Sin orden obligatorio salvo dependencias: t23 desbloquea GATE-09\u202611 y t40 las pruebas de t15, t16 y t24\",\n          \"pendientes\": [\n            \"t23 \u00b7 golden y kappa (incluye la jornada humana)\",\n            \"t29 \u00b7 las compuertas publican su evaluaci\u00f3n\",\n            \"t35 \u00b7 reglas que nunca disparan\",\n            \"t24 \u00b7 cobertura de aristas\",\n            \"t40 \u00b7 reloj fijo en la bater\u00eda\",\n            \"t41 \u00b7 GATE-04 con cero mutantes\"\n          ]\n        },\n        {\n          \"nota\": \"Plan T\u00e9cnico de Onboarding \u00b7 carril de alta\",\n          \"fase\": \"PT-A-M\",\n          \"estado\": \"aparcado\",\n          \"responsable\": \"el otro desarrollador\",\n          \"inicio\": \"2026-09-28\",\n          \"objetivo\": null,\n          \"cerrado\": null,\n          \"actualizado\": \"2026-11-09\",\n          \"hitos_total\": 16,\n          \"hitos_hechos\": 10,\n          \"siguiente\": \"Operar lo que ya tiene c\u00f3digo: contenido del cat\u00e1logo de verticales, firmar las decisiones del plan, usarlo con un cliente nuevo y medirlo con M-01\",\n          \"pendientes\": [\n            \"G2 \u00b7 Borrar las columnas `*_legacy`\",\n            \"I \u00b7 F\u00e1brica y corpus (T3\u2013T8 hechas; faltan T0\u2013T2 y T9)\",\n            \"L \u00b7 Tema por tokens (espera a que lo pida un segundo cliente)\",\n            \"Operaci\u00f3n pendiente de A\u2013I: crons, T12 de E2, F2 y H, T9 de G, nginx\",\n            \"M \u00b7 Proceso comercial: decisiones D1\u2013D15 firmadas\",\n            \"Meta M-01: tres clientes nuevos seguidos en tres d\u00edas h\u00e1biles\"\n          ]\n        }\n      ]\n    }\n  ]\n}\n"
  const vistos: string[] = []
  on('command.register', () => ({ value: { command: '' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('fs.read', (_, e) => ({ value: JSON.stringify(e).includes('roadmap-fijo') ? 'vindam_dashboard_engine\n' : '' }))
  on('process.run', (_, e) => {
    vistos.push(JSON.stringify(e))
    return { value: JSON.stringify(e).includes('roadmap') ? { exitCode: 0, stdout: datos, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } : { exitCode: 0, stdout: '[]', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /F3 Antes/ }))?.text).toContain('F3')
  await ui.unmount()
})
