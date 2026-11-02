import { describe, expect, it } from 'vitest'

import type { HistoryEntryDTO } from '@/api/types'
import { t } from '@/i18n'

import { historyValue } from './HistoryTrail'

const entry = (over: Partial<HistoryEntryDTO>): HistoryEntryDTO => ({
  at: '2026-11-02T10:00:00Z',
  actor: 'T. Bauer',
  agent: 'recruiter',
  field: 'current_title',
  summary: 'write current_title',
  source: 'human_verified',
  ...over,
})

describe('historyValue', () => {
  it('shows the value the server read from the provenance record', () => {
    expect(historyValue(entry({ value: 'Lead Engineer' }))).toBe('Lead Engineer')
  })

  it('says erased only when the server says the record is gone', () => {
    expect(historyValue(entry({ value: null }))).toBe(t('gelöscht'))
  })

  it('shows a dash for a cleared field, not an erasure', () => {
    expect(historyValue(entry({ value: '' }))).toBe('—')
  })

  it('reads the summary when the backend predates the field', () => {
    // Vercel can ship before Railway; that must not claim every line erased.
    const old = entry({ summary: "write current_title='Lead Engineer'" })
    delete old.value
    expect(historyValue(old)).toBe('Lead Engineer')
  })
})
