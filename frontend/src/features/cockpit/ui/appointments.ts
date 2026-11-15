// Termine on a manager (ELI-40): choosing "Meeting Notes" puts it in the
// calendar.
//
// A Termin is not a separate record. It is the note the composer already
// writes, of an appointment kind — so the Termine tab is a view of the notes
// and can never disagree with them. Mirrors `APPOINTMENT_INTERACTION_KINDS`
// in the backend, which serves the tab from `/managers/{id}/appointments`.

/** The kinds that belong in the calendar. */
const APPOINTMENT_KINDS = new Set(['meeting'])

export function isAppointmentKind(kind: string): boolean {
  return APPOINTMENT_KINDS.has(kind)
}

/** The instant to store. A Termin keeps the time it was set for; a note
 *  typed with a date only is pinned to midday, so it does not drift across a
 *  day boundary when it is read back in another timezone. */
export function occurredAt(date: string, time: string | null): string {
  return new Date(`${date}T${time || '12:00'}:00`).toISOString()
}

/** The next full hour, as a time input wants it — a meeting is rarely booked
 *  for the minute it is typed in. */
export function nextFullHour(now: Date = new Date()): string {
  const h = (now.getHours() + 1) % 24
  return `${String(h).padStart(2, '0')}:00`
}

/** Upcoming first, soonest at the top; then what was held, newest first. */
export function splitAppointments<T extends { occurred_at: string }>(
  rows: readonly T[],
  now: Date = new Date(),
): { upcoming: T[]; past: T[] } {
  const at = (r: T) => new Date(r.occurred_at).getTime()
  const cut = now.getTime()
  return {
    upcoming: rows.filter((r) => at(r) >= cut).sort((a, b) => at(a) - at(b)),
    past: rows.filter((r) => at(r) < cut).sort((a, b) => at(b) - at(a)),
  }
}

/** One hour unless somebody says otherwise; the record has no end time. */
const DURATION_MS = 60 * 60 * 1000

const icsDate = (d: Date) => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')

/** RFC 5545 §3.3.11: backslash, semicolon, comma and newline are reserved. */
const icsText = (s: string) =>
  s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')

/** A single-event calendar file, so the Termin lands in the recruiter's own
 *  calendar. Built in the browser: nothing about the meeting leaves Eligo
 *  except by the recruiter opening the file. */
export function appointmentIcs(
  entry: { id: string; occurred_at: string; summary?: string | null },
  title: string,
  now: Date = new Date(),
): string {
  const start = new Date(entry.occurred_at)
  const end = new Date(start.getTime() + DURATION_MS)
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Eligo Labs//Termine//DE',
    'CALSCALE:GREGORIAN',
    'BEGIN:VEVENT',
    `UID:${entry.id}@eligo`,
    `DTSTAMP:${icsDate(now)}`,
    `DTSTART:${icsDate(start)}`,
    `DTEND:${icsDate(end)}`,
    `SUMMARY:${icsText(title)}`,
    ...(entry.summary ? [`DESCRIPTION:${icsText(entry.summary)}`] : []),
    'END:VEVENT',
    'END:VCALENDAR',
  ]
  return lines.join('\r\n') + '\r\n'
}
