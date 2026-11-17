// Wiedervorlagen (ELI-44): the pure part — which bucket a to-do is in, how
// many need doing today, where the person lives, and the calendar file.
//
// "Today" is the recruiter's calendar day, computed in the browser: the
// server stores a plain date ("Anfang Februar" is 01.02., wherever you are)
// and has no idea which time zone the person reading it sits in.

import type { FollowUpDTO } from '@/api/types'

/** `YYYY-MM-DD` of the LOCAL calendar day — not `toISOString()`, which is
 *  UTC and turns 23:30 in Berlin into tomorrow. */
export function localIsoDate(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** `YYYY-MM-DD` as a LOCAL date. `new Date('2027-02-01')` is UTC midnight,
 *  which is the 31st of January anywhere west of Greenwich. */
export function parseLocalDate(isoDate: string): Date {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(y, m - 1, d)
}

/** `HH:MM` of a `HH:MM:SS` time, or null. */
export const shortTime = (t: string | null): string | null => (t ? t.slice(0, 5) : null)

/** Date, then time (a to-do without a time leads its day), then written order. */
function soonest(a: FollowUpDTO, b: FollowUpDTO): number {
  return (
    a.due_date.localeCompare(b.due_date) ||
    (a.due_time ?? '').localeCompare(b.due_time ?? '') ||
    a.created_at.localeCompare(b.created_at)
  )
}

export function bucketFollowUps(
  rows: readonly FollowUpDTO[],
  today: string,
): { overdue: FollowUpDTO[]; today: FollowUpDTO[]; upcoming: FollowUpDTO[] } {
  const open = rows.filter((r) => r.status === 'open').sort(soonest)
  return {
    overdue: open.filter((r) => r.due_date < today),
    today: open.filter((r) => r.due_date === today),
    upcoming: open.filter((r) => r.due_date > today),
  }
}

/** The navigation badge: what needs doing today — overdue plus due today. */
export function dueCount(rows: readonly FollowUpDTO[], today: string): number {
  return rows.filter((r) => r.status === 'open' && r.due_date <= today).length
}

/** Leads and managers are one table and one page; candidates have theirs. */
export function personHref(row: Pick<FollowUpDTO, 'subject_kind' | 'manager_id' | 'candidate_id'>): string {
  return row.subject_kind === 'candidate' ? `#kandidaten/${row.candidate_id}` : `#managers/${row.manager_id}`
}

/** Longest default text for a follow-up taken from a note. */
const NOTE_TEXT_MAX = 140

/** The text a follow-up confirmed from a note starts with: the note itself,
 *  on one line, cut at a word — the to-do list shows one line per row, and
 *  the whole note stays one click away on the person's page. */
export function textFromNote(summary: string): string {
  const flat = summary.replace(/\s+/g, ' ').trim()
  if (flat.length <= NOTE_TEXT_MAX) return flat
  const cut = flat.slice(0, NOTE_TEXT_MAX)
  const space = cut.lastIndexOf(' ')
  return `${(space > 40 ? cut.slice(0, space) : cut).trimEnd()}…`
}

/** Tells every open list (the cockpit, the badge, a person's page) that the
 *  set changed — there is no realtime transport, and one window event is
 *  cheaper than threading callbacks through four screens. */
export const FOLLOW_UPS_CHANGED = 'eligo:follow-ups-changed'

export function announceFollowUpsChanged(): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(FOLLOW_UPS_CHANGED))
}

/** A timed follow-up is a half-hour slot; the record has no end time. */
const SLOT_MINUTES = 30

/** RFC 5545 §3.3.11: backslash, semicolon, comma and newline are reserved. */
const icsText = (s: string) =>
  s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')

const compact = (isoDate: string) => isoDate.replace(/-/g, '')
const utcStamp = (d: Date) => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')

/** The day after `YYYY-MM-DD`, computed in UTC so no time zone can shift it. */
function nextDay(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString().slice(0, 10)
}

/** A single-event calendar file for the follow-up, so it lands in the
 *  recruiter's own calendar instead of being typed in a second time. Built in
 *  the browser: nothing leaves Eligo except by the recruiter opening it.
 *
 *  No time → an all-day entry (VALUE=DATE). A time → "floating" local time,
 *  no `Z`: 09:30 means 09:30 wherever the calendar is, which is what
 *  "um 9:30 anrufen" means. */
export function followUpIcs(
  row: Pick<FollowUpDTO, 'id' | 'due_date' | 'due_time' | 'text'>,
  title: string,
  now: Date = new Date(),
): string {
  let when: string[]
  if (row.due_time) {
    const [h, m] = row.due_time.split(':').map(Number)
    const start = new Date(`${row.due_date}T00:00:00Z`)
    start.setUTCHours(h, m)
    const end = new Date(start.getTime() + SLOT_MINUTES * 60_000)
    const local = (d: Date) => utcStamp(d).replace(/Z$/, '')
    when = [`DTSTART:${local(start)}`, `DTEND:${local(end)}`]
  } else {
    when = [`DTSTART;VALUE=DATE:${compact(row.due_date)}`, `DTEND;VALUE=DATE:${compact(nextDay(row.due_date))}`]
  }
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Eligo Labs//Wiedervorlagen//DE',
    'CALSCALE:GREGORIAN',
    'BEGIN:VEVENT',
    `UID:${row.id}@eligo-followup`,
    `DTSTAMP:${utcStamp(now)}`,
    ...when,
    `SUMMARY:${icsText(title)}`,
    ...(row.text ? [`DESCRIPTION:${icsText(row.text)}`] : []),
    'END:VEVENT',
    'END:VCALENDAR',
  ]
  return lines.join('\r\n') + '\r\n'
}
