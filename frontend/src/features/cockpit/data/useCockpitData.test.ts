// A signed-in workspace must never show the demo book. Demo cards look like
// real processes but have nothing behind them to save to, so on a workspace
// with no processes yet they read as "editing is broken for this user"
// (2026-11-05, an empty second workspace next to a populated one).
//
// The demo floor stays for the no-login demo build only.

import { describe, expect, it } from 'vitest'

import { cockpitBaseline, loadCockpit, type CockpitClient } from './useCockpitData'
import { MOCK_COCKPIT } from './mock'

const empty: CockpitClient = {
  processes: async () => [],
  board: async () => ({ columns: [] }) as never,
  candidates: async () => [],
  jobs: async () => [],
  companies: async () => [],
  reportingOverview: async () => ({ dwell: [] }) as never,
  matchJob: async () => [],
}

const down: CockpitClient = {
  processes: () => Promise.reject(new Error('502')),
  board: () => Promise.reject(new Error('502')),
  candidates: () => Promise.reject(new Error('502')),
  jobs: () => Promise.reject(new Error('502')),
  companies: () => Promise.reject(new Error('502')),
  reportingOverview: () => Promise.reject(new Error('502')),
  matchJob: () => Promise.reject(new Error('502')),
}

const closingOf = (data: ReturnType<typeof cockpitBaseline>) =>
  data.slides.flatMap((s) => (s.panels ? Object.values(s.panels).flatMap((p) => p.closing) : []))

describe('a real workspace with nothing in it', () => {
  it('shows no demo processes, mandates, scores, deals, signals or actions', async () => {
    const { data, live } = await loadCockpit(empty, false)
    expect(data.processes).toEqual([])
    expect(data.mandates).toEqual([])
    expect(data.jobScores).toEqual([])
    expect(data.signals).toEqual([])
    expect(data.actions).toEqual([])
    expect(closingOf(data)).toEqual([])
    expect(live.unavailable).toBe(false)
  })

  it('says the processes could not be loaded instead of showing demo cards', async () => {
    const { data, live } = await loadCockpit(down, false)
    expect(data.processes).toEqual([])
    expect(data.mandates).toEqual([])
    expect(live.unavailable).toBe(true)
  })

  it('does not flash the demo book while loading', () => {
    const data = cockpitBaseline(false)
    expect(data.processes).toEqual([])
    expect(data.jobScores).toEqual([])
    expect(closingOf(data)).toEqual([])
  })
})

describe('the no-login demo build', () => {
  it('keeps the demo floor', async () => {
    const { data } = await loadCockpit(empty, true)
    expect(data.processes).toEqual(MOCK_COCKPIT.processes)
    expect(data.jobScores).toEqual(MOCK_COCKPIT.jobScores)
    expect(data.signals).toEqual(MOCK_COCKPIT.signals)
  })
})
