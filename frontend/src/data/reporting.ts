import type { DwellStage, FunnelStage } from './types'

export const funnel: FunnelStage[] = [
  { label: 'Beworben', value: 564 },
  { label: 'Engaged', value: 130 },
  { label: 'Interview', value: 60 },
  { label: 'Benchmark', value: 35 },
  { label: 'Awaiting F/B', value: 15 },
  { label: 'Hold', value: 2 },
]

export const dwell: DwellStage[] = [
  { label: 'Beworben', height: 1.0, caption: '1M 7T' },
  { label: 'Engaged', height: 0.86, caption: '23T 22h' },
  { label: 'Interview', height: 0.3, caption: '6T 19h' },
  { label: 'Benchmark', height: 0.26, caption: '5T 20h' },
  { label: 'Awaiting F/B', height: 0.66, caption: '15T 18h' },
  { label: 'Hold', height: 0.12, caption: '2T 6h' },
]

export const createdJobs: { label: string; height: number }[] = [
  { label: 'Manu S.', height: 1.0 },
  { label: 'Kevin V.', height: 0.82 },
  { label: 'Pierre D.', height: 0.58 },
  { label: 'Nicola R.', height: 0.36 },
  { label: 'Alice B.', height: 0.28 },
  { label: 'Jasper C.', height: 0.2 },
  { label: 'Sander M.', height: 0.18 },
]

export const feeShare: { label: string; value: number; color: string }[] = [
  { label: 'Manu Spott', value: 44, color: '#277c59' },
  { label: 'Pierre Delfosse', value: 26, color: '#4ea886' },
  { label: 'Jasper Callaerts', value: 18, color: '#78c0a0' },
  { label: 'Kevin Vandeputte', value: 12, color: '#a9d8c1' },
]