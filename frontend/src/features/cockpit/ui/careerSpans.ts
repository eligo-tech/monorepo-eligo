// The career timeline's arithmetic, kept out of the component so it can be
// tested without a DOM — and because what makes a career chart trustworthy is
// what it refuses to draw.
//
// Extracted CV dates are free text: "2019", "03/2019", "Mar 2024",
// "seit Jan. 2021", "heute", "". A chart that silently skipped what it cannot
// read would show a five-station career as three and look complete, so every
// role is either placed or counted in `undated`, which the caller prints.

import type { RoleEntry } from '@/data/types'

/** Months since year 0. A plain integer axis: the arithmetic is exact and
 *  nothing depends on `Date`'s day or timezone handling, which a CV that says
 *  only "2019" cannot supply anyway. */
export type Months = number

/** How precisely the source stated a date. "2019" cannot settle whether a
 *  four-month gap exists; "03/2019" can. */
export type Precision = 'month' | 'year'

export interface Stamp {
  months: Months
  precision: Precision
}

/** A date the source left open: "heute", or simply nothing. */
export const OPEN = 'open'

const PRESENT =
  /\b(heute|jetzt|aktuell|laufend|derzeit|present|current|currently|now|today|ongoing|date)\b/

/** Month words, German and English, long and abbreviated. Matched as a
 *  prefix because sources write "Sept", "Sept.", "September" and "Sep". */
const MONTH_WORDS: [RegExp, number][] = [
  [/\bjan/, 1],
  [/\bfeb/, 2],
  [/\b(mär|maer|mar|mrz)/, 3],
  [/\bapr/, 4],
  [/\b(mai|may)/, 5],
  [/\bjun/, 6],
  [/\bjul/, 7],
  [/\baug/, 8],
  [/\bsep/, 9],
  [/\b(okt|oct)/, 10],
  [/\bnov/, 11],
  [/\b(dez|dec)/, 12],
]

const stamp = (year: number, month: number | null, edge: 'start' | 'end'): Stamp =>
  month === null
    ? // A bare year is read charitably at both ends — January if it is a
      // start, December if it is an end — so "2019" → "2020" is one
      // continuous stretch and not a phantom eleven-month gap.
      { months: year * 12 + (edge === 'start' ? 0 : 11), precision: 'year' }
    : { months: year * 12 + month - 1, precision: 'month' }

/** Read one end of a role's span. `null` means unreadable, `OPEN` means the
 *  source named no end — which is the current job, but also a CV that just
 *  left the field blank. The component draws those two the same way, because
 *  nothing here can tell them apart. */
export function parseStamp(
  raw: string | undefined | null,
  edge: 'start' | 'end',
): Stamp | typeof OPEN | null {
  const whole = (raw ?? '').toLowerCase().replace(/\./g, ' ').trim()
  if (!whole) return edge === 'end' ? OPEN : null
  const s = side(whole, edge)
  if (PRESENT.test(s)) return OPEN

  // ISO-ish, year first: 2019-03, 2019/3, 2019-03-15, and 2019.03 — which
  // arrives here as "2019 03", the dots already flattened.
  const iso = s.match(/(\d{4})\s*[-/ ]\s*(\d{1,2})\b/)
  if (iso) return stamp(+iso[1], month(+iso[2]), edge)

  // Month first: 03/2019, 3-2019, 03 2019.
  const num = s.match(/\b(\d{1,2})\s*[-/ ]\s*(\d{4})\b/)
  if (num) return stamp(+num[2], month(+num[1]), edge)

  const year = s.match(YEAR)
  if (!year) return null
  const named = MONTH_WORDS.find(([rx]) => rx.test(s))
  return stamp(+year[0], named ? named[1] : null, edge)
}

const YEAR = /\b(?:19|20)\d{2}\b/

/** One field that holds the WHOLE range — "2019 - 2021", "2019/2021",
 *  "Mar 2019 - Present". 73 of the live records write a single date per
 *  field, but some write the line as the CV had it, and reading "2019-2021"
 *  as one date makes a role that ended in 2021 run to today instead.
 *
 *  A hyphen is also the ISO separator, so the split only counts when two
 *  halves each carry a date of their own: "2019-03" stays one stamp. */
function side(s: string, edge: 'start' | 'end'): string {
  const parts = s
    .split(/\s*(?:–|—|-|\bbis\b|\bto\b|\buntil\b|(?<=\d{4})\s*\/\s*(?=\d{4}))\s*/)
    .map((p) => p.trim())
    .filter((p) => YEAR.test(p) || PRESENT.test(p))
  if (parts.length < 2) return s
  return edge === 'start' ? parts[0] : parts[parts.length - 1]
}

/** A month number the source may have got wrong. 13 is not a month, and
 *  guessing which digit was meant would be an invention. */
const month = (n: number): number | null => (n >= 1 && n <= 12 ? n : null)

export interface Span {
  role: RoleEntry
  /** Inclusive start, in months. */
  from: Months
  /** Exclusive end: a role that ended in March ran THROUGH March. */
  to: Months
  /** No end date in the source. Drawn without a right edge. */
  open: boolean
}

export interface Gap {
  from: Months
  to: Months
  months: number
}

export interface Timeline {
  /** In the order the roles arrived, so row N is list entry N. */
  spans: Span[]
  gaps: Gap[]
  /** Axis bounds, on January boundaries so ticks line up with gridlines. */
  from: Months
  to: Months
  /** The years to label. */
  ticks: number[]
  /** Roles whose dates could not be read. Never silently dropped. */
  undated: number
  /** True while a role is still running, which is what extends the axis to
   *  today rather than to the last date anybody wrote down. */
  openEnded: boolean
}

/** A gap of up to this many months is a notice period, not a hole in a
 *  career — three months is the statutory Kündigungsfrist most German
 *  contracts settle on, so flagging it would put a warning on the most
 *  ordinary job change there is. Flagged strictly above it. */
export const BENIGN_GAP_MONTHS = 3

/** One bar is not a timeline, it is a rectangle. */
const MIN_SPANS = 2

const nowMonths = (now: Date): Months => now.getFullYear() * 12 + now.getMonth()

/** `null` when there is not enough dated history to draw — the caller then
 *  shows the plain list, which is never wrong. */
export function buildTimeline(roles: RoleEntry[], now: Date = new Date()): Timeline | null {
  const today = nowMonths(now) + 1
  const spans: Span[] = []
  let undated = 0

  for (const role of roles) {
    const start = parseStamp(role.start, 'start')
    // An unreadable start cannot be placed at all; an unreadable END still
    // leaves a known start, and "began here, no end recorded" is exactly
    // what an open bar says.
    if (start === null || start === OPEN) {
      undated += 1
      continue
    }
    const end = parseStamp(role.end, 'end')
    const open = end === null || end === OPEN
    const to = open ? today : (end as Stamp).months + 1
    if (!open && to <= start.months) {
      // Ends before it starts. Contradictory, so it is not drawn — but it is
      // counted, and the row stays in the list below where it can be fixed.
      undated += 1
      continue
    }
    spans.push({ role, from: start.months, to, open })
  }

  if (spans.length < MIN_SPANS) return null

  const openEnded = spans.some((s) => s.open)
  const from = Math.floor(Math.min(...spans.map((s) => s.from)) / 12) * 12
  const latest = Math.max(...spans.map((s) => s.to))
  const to = Math.max(Math.ceil(latest / 12) * 12, from + 12)

  return { spans, gaps: findGaps(spans), from, to, ticks: ticks(from, to), undated, openEnded }
}

/** Holes in the covered time, walking the spans in chronological order and
 *  tracking the furthest point reached — so two parallel roles (a freelance
 *  mandate beside an employment) do not read as a gap between them. */
function findGaps(spans: Span[]): Gap[] {
  const order = [...spans].sort((a, b) => a.from - b.from)
  const gaps: Gap[] = []
  let covered = order[0].to
  let coveredPrecision = endPrecision(order[0])

  for (const span of order.slice(1)) {
    const months = span.from - covered
    if (months > BENIGN_GAP_MONTHS && resolvable(months, coveredPrecision, startPrecision(span))) {
      gaps.push({ from: covered, to: span.from, months })
    }
    if (span.to > covered) {
      covered = span.to
      coveredPrecision = endPrecision(span)
    }
  }
  return gaps
}

/** Two year-only dates cannot establish a four-month gap — "2019" to "2020"
 *  is a gap of anywhere between one month and two years, and flagging it
 *  would invent a hole out of imprecision. A year or more apart, even
 *  year-only dates agree that something is missing. */
const resolvable = (months: number, a: Precision, b: Precision): boolean =>
  months >= 12 || (a === 'month' && b === 'month')

function startPrecision(span: Span): Precision {
  const s = parseStamp(span.role.start, 'start')
  return s && s !== OPEN ? s.precision : 'year'
}

function endPrecision(span: Span): Precision {
  if (span.open) return 'month'
  const e = parseStamp(span.role.end, 'end')
  return e && e !== OPEN ? e.precision : 'year'
}

/** Years to label, thinned so a thirty-year career does not print thirty
 *  numbers into a drawer three hundred pixels wide. */
export function ticks(from: Months, to: Months, maxLabels = 6): number[] {
  const first = from / 12
  const last = to / 12
  // Anchored on multiples of the step, so the labels are round years
  // (2010, 2015, 2020) rather than wherever this CV happens to begin — which
  // also means the count has to be taken from the labels themselves. Dividing
  // the span by the step is off by one, and a six-year career printed seven.
  const at = (step: number): number[] => {
    const out: number[] = []
    for (let y = Math.ceil(first / step) * step; y <= last; y += step) out.push(y)
    return out
  }
  for (const step of [1, 2, 5, 10, 20, 50]) {
    const years = at(step)
    if (years.length <= maxLabels) return years
  }
  return at(100)
}

/** Where a month sits on the axis, 0–100. */
export const pct = (months: Months, from: Months, to: Months): number =>
  ((months - from) / (to - from)) * 100
