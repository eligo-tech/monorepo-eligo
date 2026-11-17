import { describe, expect, it } from 'vitest'

import type { FollowUpDTO } from '@/api/types'
import {
  bucketFollowUps,
  dueCount,
  followUpIcs,
  localIsoDate,
  personHref,
  textFromNote,
} from './followUps'

// ELI-44: Wiedervorlagen. "today" is always passed in, so these mean the same
// thing on any day the suite runs.

const row = (over: Partial<FollowUpDTO>): FollowUpDTO => ({
  id: 'f1',
  manager_id: 'm1',
  candidate_id: null,
  source_interaction_id: null,
  due_date: '2027-02-01',
  due_time: null,
  text: 'Wieder melden',
  status: 'open',
  origin: 'manual',
  created_at: '2026-11-17T09:00:00Z',
  created_by_name: null,
  done_at: null,
  done_by_name: null,
  subject_kind: 'lead',
  person_name: 'Petra Weber',
  company_id: 'c1',
  company_name: 'Zühlke Engineering GmbH',
  ...over,
})

describe('bucketFollowUps', () => {
  it('splits into overdue, today and upcoming — soonest first in each', () => {
    const rows = [
      row({ id: 'up2', due_date: '2027-02-01' }),
      row({ id: 'late', due_date: '2026-11-10' }),
      row({ id: 'now-t', due_date: '2026-11-17', due_time: '09:30:00' }),
      row({ id: 'up1', due_date: '2026-11-18' }),
      row({ id: 'now', due_date: '2026-11-17' }),
      row({ id: 'later', due_date: '2026-11-03' }),
    ]
    const b = bucketFollowUps(rows, '2026-11-17')
    expect(b.overdue.map((r) => r.id)).toEqual(['later', 'late'])
    // A date-only to-do leads the day; timed ones follow by time.
    expect(b.today.map((r) => r.id)).toEqual(['now', 'now-t'])
    expect(b.upcoming.map((r) => r.id)).toEqual(['up1', 'up2'])
  })

  it('ignores done ones', () => {
    const b = bucketFollowUps([row({ status: 'done', due_date: '2026-11-01' })], '2026-11-17')
    expect(b.overdue).toEqual([])
  })
})

describe('dueCount', () => {
  it('is what needs doing today: overdue plus due today', () => {
    const rows = [
      row({ id: 'a', due_date: '2026-11-10' }),
      row({ id: 'b', due_date: '2026-11-17' }),
      row({ id: 'c', due_date: '2026-11-18' }),
    ]
    expect(dueCount(rows, '2026-11-17')).toBe(2)
  })
})

describe('localIsoDate', () => {
  it('is the calendar day where the recruiter is, not in UTC', () => {
    expect(localIsoDate(new Date(2026, 10, 17, 23, 30))).toBe('2026-11-17')
    expect(localIsoDate(new Date(2027, 0, 4, 0, 5))).toBe('2027-01-04')
  })
})

describe('personHref', () => {
  it('opens the manager page for leads and managers, the candidate for candidates', () => {
    expect(personHref(row({ subject_kind: 'lead', manager_id: 'm1' }))).toBe('#managers/m1')
    expect(personHref(row({ subject_kind: 'manager', manager_id: 'm2' }))).toBe('#managers/m2')
    expect(
      personHref(row({ subject_kind: 'candidate', manager_id: null, candidate_id: 'k1' })),
    ).toBe('#kandidaten/k1')
  })
})

describe('followUpIcs', () => {
  const now = new Date('2026-11-17T10:00:00Z')

  it('is an all-day entry when no time was given', () => {
    const ics = followUpIcs(row({}), 'Wiedervorlage — Petra Weber', now)
    expect(ics).toContain('BEGIN:VEVENT')
    expect(ics).toContain('UID:f1@eligo-followup')
    expect(ics).toContain('DTSTART;VALUE=DATE:20270201')
    expect(ics).toContain('DTEND;VALUE=DATE:20270202')
    expect(ics).toContain('SUMMARY:Wiedervorlage — Petra Weber')
    expect(ics).toContain('DESCRIPTION:Wieder melden')
    expect(ics.endsWith('\r\n')).toBe(true)
  })

  it('keeps the wall-clock time when one was given', () => {
    const ics = followUpIcs(row({ due_time: '09:30:00', text: 'Anruf; Budget, Q1' }), 'X', now)
    expect(ics).toContain('DTSTART:20270201T093000')
    expect(ics).toContain('DTEND:20270201T100000')
    // RFC 5545 escaping.
    expect(ics).toContain('DESCRIPTION:Anruf\\; Budget\\, Q1')
  })

  it('folds long lines at 75 octets without splitting a character (RFC 5545 §3.1)', () => {
    const text = 'Bedarf für 2027 klären — Ansprechpartnerin Frau Müller-Lüdenscheidt, Rückruf erwünscht; '.repeat(4)
    const ics = followUpIcs(row({ text }), 'Wiedervorlage — Jürgen Groß-Übelhör', now)
    const lines = ics.split('\r\n')
    for (const line of lines) expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(75)
    // Unfolding gives the escaped text back intact.
    const unfolded = ics.replace(/\r\n /g, '')
    expect(unfolded).toContain(`DESCRIPTION:${text.replace(/;/g, '\\;').replace(/,/g, '\\,')}`)
  })

  it('rolls an end past midnight into the next day', () => {
    const ics = followUpIcs(row({ due_date: '2026-12-31', due_time: '23:45:00' }), 'X', now)
    expect(ics).toContain('DTEND:20270101T001500')
  })
})

describe('textFromNote', () => {
  it('is the note, on one line, cut at a word under the limit', () => {
    expect(textFromNote('  Kein Bedarf.\nAnfang Februar melden.  ')).toBe('Kein Bedarf. Anfang Februar melden.')
    const long = 'wort '.repeat(60)
    const cut = textFromNote(long)
    expect(cut.length).toBeLessThanOrEqual(141)
    expect(cut.endsWith('…')).toBe(true)
    expect(cut).not.toContain('wor…')
  })
})
