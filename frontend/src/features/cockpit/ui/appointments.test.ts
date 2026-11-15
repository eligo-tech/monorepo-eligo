import { describe, expect, it } from 'vitest'

import {
  appointmentIcs,
  isAppointmentKind,
  occurredAt,
  splitAppointments,
} from './appointments'
import { MANAGER_INTERACTION_KINDS } from './interactionKinds'

// ELI-40: choosing "Meeting Notes" in the composer puts the entry in Termine.
describe('appointment kinds', () => {
  it('treats a meeting as a Termin, and only a meeting', () => {
    expect(MANAGER_INTERACTION_KINDS.filter(isAppointmentKind)).toEqual(['meeting'])
  })
})

describe('occurredAt', () => {
  it('keeps the time a Termin was set for', () => {
    expect(occurredAt('2026-11-13', '14:30')).toBe(new Date('2026-11-13T14:30:00').toISOString())
  })

  it('pins a date-only note to midday, as before', () => {
    expect(occurredAt('2026-11-13', null)).toBe(new Date('2026-11-13T12:00:00').toISOString())
  })
})

describe('splitAppointments', () => {
  const row = (id: string, occurred_at: string) => ({ id, occurred_at })
  const now = new Date('2026-11-15T09:00:00Z')

  it('puts the next Termin first and the last one held first among the past', () => {
    const { upcoming, past } = splitAppointments(
      [
        row('later', '2026-12-01T10:00:00Z'),
        row('old', '2026-01-01T10:00:00Z'),
        row('soon', '2026-11-16T10:00:00Z'),
        row('recent', '2026-11-10T10:00:00Z'),
      ],
      now,
    )
    expect(upcoming.map((r) => r.id)).toEqual(['soon', 'later'])
    expect(past.map((r) => r.id)).toEqual(['recent', 'old'])
  })
})

describe('appointmentIcs', () => {
  const ics = appointmentIcs(
    { id: 'abc', occurred_at: '2026-11-20T13:30:00Z', summary: 'Kickoff; Raum 3, OG' },
    'Meeting — Achim Dreyer',
    new Date('2026-11-15T09:00:00Z'),
  )

  it('is one VEVENT at the Termin’s time, one hour long', () => {
    expect(ics).toContain('BEGIN:VCALENDAR')
    expect(ics).toContain('DTSTART:20261120T133000Z')
    expect(ics).toContain('DTEND:20261120T143000Z')
    expect(ics).toContain('UID:abc@eligo')
    expect(ics).toContain('SUMMARY:Meeting — Achim Dreyer')
  })

  it('escapes what RFC 5545 reserves', () => {
    expect(ics).toContain('DESCRIPTION:Kickoff\\; Raum 3\\, OG')
  })

  it('uses CRLF line endings', () => {
    expect(ics.split('\r\n').length).toBeGreaterThan(5)
  })
})
