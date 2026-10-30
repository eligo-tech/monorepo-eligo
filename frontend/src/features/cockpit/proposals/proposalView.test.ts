import { describe, expect, it } from 'vitest'

import type { ProposalDTO } from '@/api/types'
import { changeLines, isOpen } from './proposalView'

const base: ProposalDTO = {
  id: 'p1',
  kind: 'step',
  status: 'pending',
  title: 'Anna Beispiel · COC Lead — Interviewtermin',
  tool: 'pipeline.propose_step',
  before: { step: null },
  after: { application_id: 'a1', step_key: 'interview', scheduled_at: null, done_at: '2026-10-29T10:00:00+00:00', outcome: 'pass' },
  reason: 'lief gut',
  asked_by_name: 'Dana',
  client_id: 'lEpz2crhuszLqEo0',
  created_at: '2026-10-30T09:00:00Z',
  expires_at: '2026-11-06T09:00:00Z',
  decided_by_name: null,
  decided_at: null,
}

describe('what a proposal changes', () => {
  it('a step shows only the fields it changes, before → after', () => {
    const lines = changeLines(base)
    expect(lines.map((l) => l.field)).toEqual(['done_at', 'outcome'])
    expect(lines[0].before).toBeNull() // no step yet
    expect(lines[0].after).toBe('2026-10-29T10:00:00+00:00')
    expect(lines[1].after).toBe('pass')
  })

  it('a step that existed shows its old value', () => {
    const p = { ...base, before: { step: { scheduled_at: null, done_at: null, outcome: 'open' } } }
    expect(changeLines(p).find((l) => l.field === 'outcome')?.before).toBe('open')
  })

  it('a note shows its text', () => {
    const p: ProposalDTO = { ...base, kind: 'candidate_note', before: {}, after: { candidate_id: 'c', text: 'Start im März' } }
    expect(changeLines(p)).toEqual([{ field: 'text', before: null, after: 'Start im März' }])
  })

  it('only a pending proposal can be decided', () => {
    expect(isOpen(base)).toBe(true)
    for (const status of ['confirmed', 'declined', 'stale', 'expired'])
      expect(isOpen({ ...base, status })).toBe(false)
  })
})
