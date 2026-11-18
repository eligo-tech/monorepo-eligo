import { describe, expect, it, vi } from 'vitest'

import { berlinDateTimeLocal, berlinIsoDate, openPicker, presetFor } from './datePicker'
import { readFollowUpDate } from './followUps'
import { composeEntry, composerToday } from './InteractionComposer'

// ELI-53. Instants are given in UTC so the suite means the same thing in any
// time zone it runs in; 18.11.2026 is a Wednesday.

describe('the day in Germany', () => {
  it('is Berlin’s calendar day, not UTC’s', () => {
    // 00:30 on the 19th in Berlin is still the 18th in UTC.
    expect(berlinIsoDate(new Date('2026-11-18T23:30:00Z'))).toBe('2026-11-19')
    expect(berlinIsoDate(new Date('2026-11-18T15:12:00Z'))).toBe('2026-11-18')
    // Summer time: 23:30 UTC on 30 June is 01:30 on 1 July in Berlin.
    expect(berlinIsoDate(new Date('2026-06-30T23:30:00Z'))).toBe('2026-07-01')
  })

  it('opens a datetime field on today at the next full hour', () => {
    expect(berlinDateTimeLocal(new Date('2026-11-18T15:12:00Z'))).toBe('2026-11-18T17:00')
    // Late at night it stays today rather than rolling to tomorrow.
    expect(berlinDateTimeLocal(new Date('2026-11-18T22:40:00Z'))).toBe('2026-11-18T23:00')
  })
})

describe('presetFor', () => {
  const now = new Date('2026-11-18T15:12:00Z')
  it('fills an empty field with today', () => {
    expect(presetFor('date', '', now)).toBe('2026-11-18')
    expect(presetFor('datetime-local', '', now)).toBe('2026-11-18T17:00')
  })
  it('never overwrites a value that is set', () => {
    expect(presetFor('date', '2027-02-01', now)).toBeNull()
    expect(presetFor('datetime-local', '2027-02-01T09:00', now)).toBeNull()
  })
})

describe('openPicker', () => {
  it('opens the calendar where the browser can', () => {
    const showPicker = vi.fn()
    openPicker({ showPicker } as unknown as HTMLInputElement)
    expect(showPicker).toHaveBeenCalledOnce()
  })
  it('does nothing where it cannot', () => {
    const throwing = {
      showPicker: () => {
        throw new DOMException('no user gesture', 'NotAllowedError')
      },
    } as unknown as HTMLInputElement
    expect(() => openPicker(throwing)).not.toThrow()
    expect(() => openPicker({} as HTMLInputElement)).not.toThrow()
    expect(() => openPicker(null)).not.toThrow()
  })
})

describe('the composer’s default day', () => {
  it('is today in Germany, also just after midnight', () => {
    // Was `toISOString().slice(0, 10)`: a note written at 00:30 got yesterday.
    expect(composerToday(new Date('2026-11-18T23:30:00Z'))).toBe('2026-11-19')
  })
  it('a date-only note stays on its day', () => {
    expect(composeEntry('business_call', 'x', '2026-11-19', '').occurred_at).toBe(
      new Date('2026-11-19T12:00:00').toISOString(),
    )
  })
})

describe('readFollowUpDate — the bug in ELI-53', () => {
  // A recruiter wrote "Neuer Anruf morgen" as the Wiedervorlage's to-do on
  // 18.11.2026; the form kept its default date — today — and saved the
  // follow-up for the 18th. The to-do's own words now set the date.
  it('reads "morgen" against today, giving tomorrow', async () => {
    const suggest = vi.fn(async () => ({ suggestions: [{ due_date: '2026-11-19', phrase: 'morgen' }] }))
    const found = await readFollowUpDate('Neuer Anruf morgen', new Date('2026-11-18T15:12:00Z'), suggest)
    expect(suggest).toHaveBeenCalledWith('Neuer Anruf morgen', '2026-11-18')
    expect(found).toEqual({ due_date: '2026-11-19', phrase: 'morgen' })
  })

  it('asks with Germany’s day after midnight', async () => {
    const suggest = vi.fn(async () => ({ suggestions: [] }))
    await readFollowUpDate('morgen', new Date('2026-11-18T23:30:00Z'), suggest)
    expect(suggest).toHaveBeenCalledWith('morgen', '2026-11-19')
  })

  it('no date in the text, or the reader down: nothing', async () => {
    expect(await readFollowUpDate('Bedarf erfragen', new Date(), async () => ({ suggestions: [] }))).toBeNull()
    expect(
      await readFollowUpDate('morgen', new Date(), async () => {
        throw new Error('offline')
      }),
    ).toBeNull()
    const never = vi.fn()
    expect(await readFollowUpDate('   ', new Date(), never)).toBeNull()
    expect(never).not.toHaveBeenCalled()
  })
})
