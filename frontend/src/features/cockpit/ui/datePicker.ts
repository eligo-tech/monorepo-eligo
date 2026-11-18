// Date fields in the cockpit (ELI-53): one click opens the calendar, and an
// empty field opens on today.
//
// A native `<input type="date">` shows "tt.mm.jjjj" and opens its calendar
// only from the small icon; recruiters typed dates by hand. `DateField` opens
// the picker on a click anywhere in the box and, when the field is empty,
// fills in today first, so the calendar opens with today selected. A value
// that is already there is never touched.
//
// "Today" is Germany's calendar day: the product's times are "Ortszeit
// Deutschland", and `toISOString()` — UTC — turns 00:30 in Berlin into
// yesterday, which is how a note typed after midnight was filed a day early.

const BERLIN = 'Europe/Berlin'

function berlinParts(now: Date): Record<string, string> {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: BERLIN,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now)
  return Object.fromEntries(parts.map((p) => [p.type, p.value]))
}

/** `YYYY-MM-DD` of the calendar day in Germany. */
export function berlinIsoDate(now: Date = new Date()): string {
  const p = berlinParts(now)
  return `${p.year}-${p.month}-${p.day}`
}

/** `YYYY-MM-DDTHH:00` for a datetime-local field: today in Germany at the
 *  next full hour (a Termin is rarely booked for the minute it is typed),
 *  never past 23:00 so it stays today. */
export function berlinDateTimeLocal(now: Date = new Date()): string {
  const hour = Math.min(Number(berlinParts(now).hour) + 1, 23)
  return `${berlinIsoDate(now)}T${String(hour).padStart(2, '0')}:00`
}

export type DateFieldType = 'date' | 'datetime-local'

/** What an EMPTY field is filled with when its calendar is opened; null
 *  when the field already holds a value, which stays as it is. */
export function presetFor(type: DateFieldType, value: string, now: Date = new Date()): string | null {
  if (value) return null
  return type === 'date' ? berlinIsoDate(now) : berlinDateTimeLocal(now)
}

/** Opens the browser's calendar. `showPicker` is missing in older browsers
 *  and throws without a user gesture or in a cross-origin frame — the field
 *  then simply works as it did before. */
export function openPicker(el: HTMLInputElement | null): void {
  if (!el || typeof el.showPicker !== 'function') return
  try {
    el.showPicker()
  } catch {
    /* not supported here — typing still works */
  }
}
