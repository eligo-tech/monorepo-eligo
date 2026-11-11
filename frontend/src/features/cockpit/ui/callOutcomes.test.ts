import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { CALL_OUTCOMES, callOutcomeLabel, canSaveCall, needsDate } from './callOutcomes'

// ELI-22 call list: the outcomes the recruiters agreed on, in backend order
// (`CallOutcome`), and the one rule the backend enforces — a call-back needs a
// date, or it never comes due.
describe('call outcomes', () => {
  it('are the agreed seven, in the backend order', () => {
    expect(CALL_OUTCOMES).toEqual([
      'not_reached', 'voicemail', 'call_back', 'wrong_person', 'not_interested', 'meeting_booked', 'mandate',
    ])
  })

  it('each has a label, not the raw key', () => {
    for (const o of CALL_OUTCOMES) expect(callOutcomeLabel(o)).not.toBe(o)
    // Whatever language the test runner renders in, it is the dictionary's word.
    expect(callOutcomeLabel('call_back')).toBe(t('Rückruf vereinbart'))
  })

  it('a call-back cannot be saved without a date', () => {
    expect(needsDate('call_back')).toBe(true)
    expect(canSaveCall('call_back', '')).toBe(false)
    expect(canSaveCall('call_back', '2026-11-13T09:00')).toBe(true)
    expect(canSaveCall('voicemail', '')).toBe(true)
    expect(canSaveCall('', '')).toBe(false)
  })
})
