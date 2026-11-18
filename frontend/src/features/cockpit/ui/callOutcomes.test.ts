import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { CALL_OUTCOMES, callOutcomeLabel, canSaveCall, needsDate, nextCallInstant } from './callOutcomes'

// ELI-22 call list: the outcomes the recruiters agreed on, in backend order
// (`CallOutcome`), and the one rule the backend enforces — a call-back needs a
// date, or it never comes due.
describe('call outcomes', () => {
  it('are the agreed six, in the backend order — no Mailbox (ELI-35)', () => {
    expect(CALL_OUTCOMES).toEqual([
      'not_reached', 'call_back', 'wrong_person', 'not_interested', 'meeting_booked', 'mandate',
    ])
  })

  it('shows an old Mailbox call as Nicht erreicht', () => {
    expect(callOutcomeLabel('voicemail')).toBe(t('Nicht erreicht'))
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
    // ELI-35: "Nicht erreicht" needs neither a date nor any text.
    expect(canSaveCall('not_reached', '')).toBe(true)
    expect(canSaveCall('', '')).toBe(false)
  })
})

describe('nextCallInstant — the next call is a day, not a time (ELI-35)', () => {
  it('a picked day is due from the start of that day', () => {
    expect(nextCallInstant('2026-11-19')).toBe(new Date(2026, 10, 19).toISOString())
  })
  it('no day, no next call', () => {
    expect(nextCallInstant('')).toBeNull()
  })
})
