export type Sesion = {
  nombre: string
  estado: string
  tipo: string
  cwd: string
  id: string
}
export type Espera = { nombre: string; detalle: string }
export type Alerta = {
  id: string
  ts: number
  nivel: string
  texto: string
  fuente: string
}
export type Trabajo = { nombre: string; estado: string; detalle: string }
export type Parte = { fecha: string; semaforo: string; resumen: string } | null
// Una tarjeta de /roadmap: lo que da `narrador roadmap --json` por proyecto, ya aplanado.
export type FaseRoadmap = {
  nota: string
  fase: string
  estado: string
  hechos: number
  total: number
  inicio: string
  objetivo: string
  cerrado: string
  responsable: string
  siguiente: string
  pendientes: string[]
}
export type ProyectoRoadmap = {
  fases: FaseRoadmap[]
  objetivo: string
  desfase: number | null
  ritmoHist: number | null
  semanasRest: number | null
  commitsTotal: number | null
  cierres: string[]
  listaAvisos: string[]
  nombre: string
  error: string
  semaforo: string
  deriva: string
  hechos: number
  total: number
  pct: number | null
  prevista: string
  confianza: string
  ritmo: number | null
  restantes: number
  motivo: string
  siguiente: string
  siguienteFase: string
  responsable: string
  ultimo: string
  diasSinTocar: number | null
  commits4s: number | null
  sinCommit: number | null
  avisos: number
}
// Una tarjeta del tablero de hallazgos, tal como la da `narrador tablero ver --json`.
export type TarjetaTablero = {
  id: string
  cliente: string
  titulo: string
  nivel: string
  detalle: string[]
  columna: string
  marca: string
  fiabilidad: string
  primera: string
  ultima: string
  movimiento: string
}
export type MetaTablero = {
  existe: boolean
  parteFecha: string
  semaforo: string
  puedeDeshacer: boolean
  invalidas: number
}
// Una puerta: lo que espera un sí del usuario (`narrador puerta lista --json`). La cabina solo
// anota la respuesta; el comando lo ejecuta Ío.
export type Puerta = {
  id: string
  titulo: string
  comando: string
  coste: string
  vuelta: string
  proyecto: string
  estado: string
  creada: string
  respondida: string
  origen: string
}
// Un trabajador que sigue en marcha: id corto, nombre completo y tarea.
export type TrabajadorVivo = { id: string; nombre: string; tarea: string; proyecto: string; ruta: string }

declare module 'claude-code' {
  interface PluginState {
    'io-cabina': {
      sesiones: Shaped<Sesion[]>
      esperas: Shaped<Espera[]>
      alertas: Shaped<Alerta[]>
      trabajos: Shaped<Trabajo[]>
      pendientes: Shaped<string[]>
      parte: Shaped<Parte>
      actualizado: number
      fallo: string
      roadmap: Shaped<ProyectoRoadmap[]>
      roadmapCuando: number
      roadmapFallo: string
      roadmapOrigen: string
      roadmapFijo: string
      tablero: Shaped<TarjetaTablero[]>
      tableroMeta: Shaped<MetaTablero>
      tableroCuando: number
      tableroFallo: string
      tableroSel: string
      puertas: Shaped<Puerta[]>
      puertasFallo: string
      vivos: Shaped<TrabajadorVivo[]>
      gasto: number | null
    }
  }
}
