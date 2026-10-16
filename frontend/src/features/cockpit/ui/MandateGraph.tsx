// The mandate as a graph: one root, one child per candidate.
//
// The cards below say everything this does and more — but they say it in a
// column a screen and a half long, and the question "who is on this mandate,
// and which of them actually fits?" is one glance, not a scroll. Three
// candidates on the IT-Administrator mandate score 8, 7 and 5; that ordering
// is the whole point and it was only legible by reading three cards.
//
// Hand-rolled SVG, like every other chart here (`ui/Gauge.tsx`) — no chart
// library.
//
// Two rules it keeps:
//
//  * **Nothing is invented.** The edge is weighted and coloured by the fit
//    score from the Kandidatenauswertung, and a candidate nobody has assessed
//    gets a thin neutral edge and "—", not a guess at where they belong. The
//    graph is a second rendering of the record, so it must not be able to
//    say something the cards do not.
//  * **The node is a link.** An `<a href="#kandidaten/…">` inside the SVG, so
//    it is keyboard-reachable and middle-clickable like the name on the card,
//    rather than a div with an onClick.

import { useState } from 'react'

import { cn } from '@/lib/cn'
import { scoreTone } from './ScoreBar'
import { Label } from './primitives'
import type { Mandate, ProcessCard } from '../data/types'

/** Node geometry. One row per candidate; the root is centred against them. */
const ROOT = { x: 4, w: 232, h: 72 }
const CHILD = { x: 332, w: 452, h: 60 }
const GAP = 14
const PAD = 10

const STROKE = {
  mint: 'stroke-mint-500',
  gold: 'stroke-gold-500',
  coral: 'stroke-coral-500',
  none: 'stroke-cockpit-line',
} as const

const DOT = {
  mint: 'fill-mint-400',
  gold: 'fill-gold-400',
  coral: 'fill-coral-400',
  none: 'fill-cockpit-faint',
} as const

const TEXT = {
  mint: 'fill-mint-300',
  gold: 'fill-gold-300',
  coral: 'fill-coral-300',
  none: 'fill-cockpit-faint',
} as const

export type Tone = keyof typeof STROKE

/** The fit score decides the tone, on the same thresholds as everything else:
 *  `scoreTone` owns ≥70 mint / ≥50 gold / else coral, and the assessment is
 *  scored 0–10. An unassessed candidate has no tone, not a bad one. */
export function toneOf(card: ProcessCard): Tone {
  const fit = card.assessment?.fitScore
  return fit === null || fit === undefined ? 'none' : scoreTone(fit * 10)
}

/** Where the process stands — the same line the collapsed card shows. */
export function standing(card: ProcessCard): string {
  const out = card.steps.find((s) => s.state === 'out')
  if (out) return `abgesagt · ${out.label}`
  const current = card.steps.find((s) => s.state === 'current')
  if (current) return current.label
  const done = [...card.steps].reverse().find((s) => s.state === 'done')
  return done ? `${done.label} ✓` : 'noch kein Schritt'
}

/** Cut a label to fit its box. SVG does not wrap, and an ellipsis is more
 *  honest than a name that runs out of the panel. */
export function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`
}

export function MandateGraph({ mandate }: { mandate: Mandate }) {
  // Best fit first: the ordering IS the answer to "which of them fits".
  // Unassessed candidates sort last — no score is not a low score, but it is
  // also not a reason to put them at the top.
  const cards = [...mandate.cards].sort((a, b) => {
    const fa = a.assessment?.fitScore
    const fb = b.assessment?.fitScore
    if (fa == null && fb == null) return a.candidateName.localeCompare(b.candidateName)
    if (fa == null) return 1
    if (fb == null) return -1
    return fb - fa
  })

  if (cards.length === 0) return null

  const rowH = CHILD.h + GAP
  const height = cards.length * rowH - GAP + PAD * 2
  const width = CHILD.x + CHILD.w + 4
  const rootY = height / 2 - ROOT.h / 2
  const rootRight = ROOT.x + ROOT.w
  const yOf = (i: number) => PAD + i * rowH

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        style={{ minWidth: 560, maxHeight: height }}
        role="img"
        aria-label={`${mandate.title}: ${cards.length} Kandidaten, nach Passung sortiert`}
      >
        {/* Edges first, so a node always sits on top of its own line. */}
        {cards.map((card, i) => {
          const tone = toneOf(card)
          const y = yOf(i) + CHILD.h / 2
          const mid = (rootRight + CHILD.x) / 2
          const fit = card.assessment?.fitScore
          return (
            <path
              key={`edge-${card.id}`}
              d={`M ${rootRight} ${rootY + ROOT.h / 2} C ${mid} ${rootY + ROOT.h / 2}, ${mid} ${y}, ${CHILD.x} ${y}`}
              fill="none"
              // Thicker for a better fit — the one place the number is also a
              // shape, so the ranking reads before the digits do.
              strokeWidth={fit == null ? 1 : 1.25 + (fit / 10) * 2.25}
              className={cn(STROKE[tone], tone === 'none' && 'opacity-70')}
            />
          )
        })}

        {/* The mandate. */}
        <g>
          <rect
            x={ROOT.x}
            y={rootY}
            width={ROOT.w}
            height={ROOT.h}
            rx={12}
            className="fill-cockpit-raised stroke-cockpit-edge"
            strokeWidth={1}
          />
          <text
            x={ROOT.x + 16}
            y={rootY + 25}
            className="fill-cockpit-faint font-mono text-[11px]"
          >
            {mandate.ref}
          </text>
          <text
            x={ROOT.x + 16}
            y={rootY + 45}
            className="fill-cockpit-text text-[13px] font-semibold"
          >
            {clip(mandate.title, 26)}
          </text>
          <text
            x={ROOT.x + 16}
            y={rootY + 62}
            className="fill-cockpit-dim font-mono text-[11px]"
          >
            {clip(mandate.client, 22)} · {cards.length}{' '}
            {cards.length === 1 ? 'Kandidat' : 'Kandidaten'}
          </text>
        </g>

        {/* The candidates. */}
        {cards.map((card, i) => {
          const tone = toneOf(card)
          const y = yOf(i)
          const fit = card.assessment?.fitScore
          const node = (
            <>
              <rect
                x={CHILD.x}
                y={y}
                width={CHILD.w}
                height={CHILD.h}
                rx={12}
                className="fill-cockpit-surface stroke-cockpit-line transition-colors group-hover:stroke-cockpit-edge"
                strokeWidth={1}
              />
              <circle cx={CHILD.x + 20} cy={y + CHILD.h / 2} r={4} className={DOT[tone]} />
              <text
                x={CHILD.x + 36}
                y={y + 25}
                className="fill-cockpit-text text-[13.5px] font-semibold"
              >
                {clip(card.candidateName, 30)}
              </text>
              <text
                x={CHILD.x + 36}
                y={y + 44}
                className="fill-cockpit-faint font-mono text-[11px]"
              >
                {card.candidateRef} · {clip(standing(card), 30)}
              </text>
              <text
                x={CHILD.x + CHILD.w - 16}
                y={y + 36}
                textAnchor="end"
                className={cn('font-mono text-[17px] font-semibold', TEXT[tone])}
              >
                {fit == null ? '—' : `${fit}/10`}
              </text>
            </>
          )
          return card.candidateId ? (
            <a
              key={card.id}
              href={`#kandidaten/${card.candidateId}`}
              className="group cursor-pointer"
              aria-label={`${card.candidateName}, Passung ${fit ?? 'nicht bewertet'} — Kandidatenakte öffnen`}
            >
              {node}
            </a>
          ) : (
            <g key={card.id}>{node}</g>
          )
        })}
      </svg>
    </div>
  )
}

/** The legend, in HTML rather than SVG so it wraps on a narrow panel. */
export function MandateGraphLegend() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
      <Label>Passung</Label>
      {(
        [
          ['mint', '7–10 · trägt'],
          ['gold', '5–6 · mit Vorbehalt'],
          ['coral', '0–4 · kritisch'],
          ['none', 'nicht bewertet'],
        ] as const
      ).map(([tone, label]) => (
        <span
          key={tone}
          className="flex items-center gap-1.5 font-mono text-[11px] text-cockpit-faint"
        >
          <svg width="18" height="8" aria-hidden>
            <line
              x1="0"
              y1="4"
              x2="18"
              y2="4"
              strokeWidth={tone === 'none' ? 1 : 2.5}
              className={STROKE[tone]}
            />
          </svg>
          {label}
        </span>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// The whole book of business, three levels deep
// ---------------------------------------------------------------------------
//
// `#cockpit` is every mandate at once, and a flat fan of root → candidate
// would be twenty rows tall — longer than the cards it is supposed to save
// you from reading. So the book graph is the same picture one level up:
//
//     alle Prozesse ──→ Mandat ──→ Kandidat
//
// Mandates are the children, ranked by the BEST fit anybody on them has, and
// a mandate opens in place to show who that is. Which answers the question
// the Gesamt view exists for and the per-mandate graph cannot: where is there
// somebody who fits, and which searches have nobody yet.
//
// The edge to a mandate carries its best candidate's score — an aggregate,
// and the node says which number it is showing ("bester Fit 8/10") so it is
// never mistaken for an average or for a judgement about the mandate itself.

const BOOK_ROOT = { x: 4, w: 196, h: 76 }
const BOOK_MANDATE = { x: 268, w: 392, h: 62 }
const BOOK_CAND = { x: 720, w: 396, h: 62 }
const ROW_GAP = 10

/** The candidate node's inset, and the column it keeps clear on the right.
 *  The reserve is measured against the WIDEST score, not the common one:
 *  "10/10" is five characters at 16px mono, 48px, and the four-character
 *  "8/10" is what made the old 14px reserve look sufficient. */
const CAND_PAD = 16
const CAND_SCORE = 72

/** Where the candidate's two lines start, and how wide they may be. */
const CAND_TEXT = CAND_PAD + 22
const CAND_LINE = BOOK_CAND.w - CAND_TEXT - CAND_SCORE

/** The mandate node's own left inset. Wider than `PAD`, which is the gap
 *  around the whole picture. */
const MANDATE_PAD = 16

/** What the mandate node keeps clear on its right: the tone dot, the expand
 *  caret and the button that opens the mandate. The caption stops before it. */
const MANDATE_CONTROLS = 58

/** Advance width of one character in the mono face, as a fraction of the font
 *  size. JetBrains Mono — and the two faces the Jet · Mono · Heli switch puts in
 *  its place — are 0.6em, which is what makes the character budget below an
 *  exact width rather than a guess. */
const MONO_ADVANCE = 0.6

/** How many characters of the mono face fit in `widthPx`. */
function monoFit(widthPx: number, fontPx: number): number {
  return Math.max(Math.floor(widthPx / (fontPx * MONO_ADVANCE)), 2)
}

/** Clip a mono line to the pixels it is allowed.
 *
 *  Only for mono: the sans face has no fixed advance, so a character count
 *  there is an estimate and is kept deliberately short of the real room. */
export function fitMono(text: string, widthPx: number, fontPx: number): string {
  return clip(text, monoFit(widthPx, fontPx))
}

/** The mandate caption, measured tail-first.
 *
 *  The score is the point of the line, so when the room runs out it is the
 *  client name that gives way, never the number. What this replaces wrote the
 *  line left to right and clipped only the client, at a fixed 18 characters:
 *  "Linde + Wiemann · 3 Kandidaten · bester Fit 8/10" is 48 characters, the box
 *  held 36, and the part that hung outside it was the part worth reading. */
export function mandateCaption(
  client: string,
  count: number,
  fit: number | null,
  { width = BOOK_MANDATE.w, fontPx = 11 }: { width?: number; fontPx?: number } = {},
): string {
  const tail = ` · ${count} ${count === 1 ? 'Kandidat' : 'Kandidaten'}${
    fit === null ? ' · ohne Bewertung' : ` · bester Fit ${fit}/10`
  }`
  const room = width - MANDATE_PAD - MANDATE_CONTROLS
  const budget = monoFit(room, fontPx) - tail.length
  return `${clip(client, Math.max(budget, 2))}${tail}`
}

/** The best fit on a mandate, and the tone that goes with it. `null` when
 *  nobody on it has been assessed — which is a finding, not a zero. */
function bestFit(mandate: Mandate): number | null {
  const scores = mandate.cards
    .map((c) => c.assessment?.fitScore)
    .filter((f): f is number => f !== null && f !== undefined)
  return scores.length > 0 ? Math.max(...scores) : null
}

type Row =
  | { kind: 'mandate'; y: number; mandate: Mandate }
  | { kind: 'candidate'; y: number; card: ProcessCard; parent: string }

export function BookGraph({
  mandates,
  onOpenMandate,
}: {
  mandates: Mandate[]
  /** Opens the per-job view. Absent for a demo mandate with no job row. */
  onOpenMandate?: (mandateId: string) => void
}) {
  const [open, setOpen] = useState<Set<string>>(new Set())

  // Mandates with a fitting candidate first; mandates nobody has assessed
  // last, sorted by how many people are waiting on them — that is the work
  // the graph is pointing at.
  const ranked = [...mandates].sort((a, b) => {
    const fa = bestFit(a)
    const fb = bestFit(b)
    if (fa === null && fb === null) return b.cards.length - a.cards.length
    if (fa === null) return 1
    if (fb === null) return -1
    return fb - fa
  })

  const rows: Row[] = []
  let y = PAD
  for (const mandate of ranked) {
    rows.push({ kind: 'mandate', y, mandate })
    y += BOOK_MANDATE.h + ROW_GAP
    if (!open.has(mandate.id)) continue
    for (const card of [...mandate.cards].sort(
      (a, b) => (b.assessment?.fitScore ?? -1) - (a.assessment?.fitScore ?? -1),
    )) {
      rows.push({ kind: 'candidate', y, card, parent: mandate.id })
      y += BOOK_CAND.h + ROW_GAP
    }
  }
  if (rows.length === 0) return null

  const height = y - ROW_GAP + PAD
  const width = BOOK_CAND.x + BOOK_CAND.w + 4
  const rootY = Math.min(height / 2 - BOOK_ROOT.h / 2, 220)
  const rootMid = rootY + BOOK_ROOT.h / 2
  const rootRight = BOOK_ROOT.x + BOOK_ROOT.w
  const total = mandates.reduce((n, m) => n + m.cards.length, 0)

  const mandateRow = (id: string) =>
    rows.find((r) => r.kind === 'mandate' && r.mandate.id === id) as
      | { kind: 'mandate'; y: number; mandate: Mandate }
      | undefined

  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        style={{ minWidth: 720, maxHeight: height }}
        role="img"
        aria-label={`${mandates.length} Mandate mit ${total} Kandidaten, nach bester Passung sortiert`}
      >
        {rows.map((row) => {
          if (row.kind === 'mandate') {
            const fit = bestFit(row.mandate)
            const tone: Tone = fit === null ? 'none' : scoreTone(fit * 10)
            const mid = (rootRight + BOOK_MANDATE.x) / 2
            const y2 = row.y + BOOK_MANDATE.h / 2
            return (
              <path
                key={`e-${row.mandate.id}`}
                d={`M ${rootRight} ${rootMid} C ${mid} ${rootMid}, ${mid} ${y2}, ${BOOK_MANDATE.x} ${y2}`}
                fill="none"
                strokeWidth={fit === null ? 1 : 1.25 + (fit / 10) * 2.25}
                className={cn(STROKE[tone], tone === 'none' && 'opacity-70')}
              />
            )
          }
          const parent = mandateRow(row.parent)
          if (!parent) return null
          const tone = toneOf(row.card)
          const fit = row.card.assessment?.fitScore
          const from = parent.y + BOOK_MANDATE.h / 2
          const to = row.y + BOOK_CAND.h / 2
          const mid = (BOOK_MANDATE.x + BOOK_MANDATE.w + BOOK_CAND.x) / 2
          return (
            <path
              key={`e-${row.card.id}`}
              d={`M ${BOOK_MANDATE.x + BOOK_MANDATE.w} ${from} C ${mid} ${from}, ${mid} ${to}, ${BOOK_CAND.x} ${to}`}
              fill="none"
              strokeWidth={fit == null ? 1 : 1.25 + (fit / 10) * 2.25}
              className={cn(STROKE[tone], tone === 'none' && 'opacity-70')}
            />
          )
        })}

        {/* The book. */}
        <rect
          x={BOOK_ROOT.x}
          y={rootY}
          width={BOOK_ROOT.w}
          height={BOOK_ROOT.h}
          rx={12}
          className="fill-cockpit-raised stroke-cockpit-edge"
          strokeWidth={1}
        />
        <text x={BOOK_ROOT.x + 16} y={rootY + 26} className="fill-cockpit-faint font-mono text-[11px]">
          Laufende Prozesse
        </text>
        <text x={BOOK_ROOT.x + 16} y={rootY + 48} className="fill-cockpit-text text-[15px] font-semibold">
          {mandates.length} {mandates.length === 1 ? 'Mandat' : 'Mandate'}
        </text>
        <text x={BOOK_ROOT.x + 16} y={rootY + 65} className="fill-cockpit-dim font-mono text-[11px]">
          {total} {total === 1 ? 'Kandidat' : 'Kandidaten'}
        </text>

        {rows.map((row) => {
          if (row.kind === 'mandate') {
            const { mandate } = row
            const fit = bestFit(mandate)
            const tone: Tone = fit === null ? 'none' : scoreTone(fit * 10)
            const shown = open.has(mandate.id)
            return (
              <g key={mandate.id}>
                {/* The body toggles; the arrow at the end opens the mandate.
                    Two targets, because "show me who" and "take me there"
                    are different intentions and one click cannot be both. */}
                <g className="group cursor-pointer" onClick={() => toggle(mandate.id)}>
                  <rect
                    x={BOOK_MANDATE.x}
                    y={row.y}
                    width={BOOK_MANDATE.w}
                    height={BOOK_MANDATE.h}
                    rx={11}
                    className="fill-cockpit-surface stroke-cockpit-line transition-colors group-hover:stroke-cockpit-edge"
                    strokeWidth={1}
                  />
                  <text
                    x={BOOK_MANDATE.x + MANDATE_PAD}
                    y={row.y + 25}
                    className="fill-cockpit-text text-[13px] font-semibold"
                  >
                    {clip(mandate.title, 38)}
                  </text>
                  <text
                    x={BOOK_MANDATE.x + MANDATE_PAD}
                    y={row.y + 44}
                    className="fill-cockpit-faint font-mono text-[11px]"
                  >
                    {mandateCaption(mandate.client, mandate.cards.length, fit)}
                  </text>
                  <circle
                    cx={BOOK_MANDATE.x + BOOK_MANDATE.w - 52}
                    cy={row.y + BOOK_MANDATE.h / 2}
                    r={4}
                    className={DOT[tone]}
                  />
                  <text
                    x={BOOK_MANDATE.x + BOOK_MANDATE.w - 38}
                    y={row.y + BOOK_MANDATE.h / 2 + 4}
                    className="fill-cockpit-faint font-mono text-[12px]"
                  >
                    {shown ? '▾' : '▸'}
                  </text>
                </g>
                {onOpenMandate && (
                  <g
                    className="cursor-pointer"
                    onClick={() => onOpenMandate(mandate.id)}
                  >
                    <title>Mandat öffnen</title>
                    <rect
                      x={BOOK_MANDATE.x + BOOK_MANDATE.w - 26}
                      y={row.y + BOOK_MANDATE.h / 2 - 11}
                      width={22}
                      height={22}
                      rx={6}
                      className="fill-transparent stroke-cockpit-line hover:stroke-cockpit-edge"
                      strokeWidth={1}
                    />
                    <text
                      x={BOOK_MANDATE.x + BOOK_MANDATE.w - 19}
                      y={row.y + BOOK_MANDATE.h / 2 + 4}
                      className="fill-cockpit-dim font-mono text-[12px]"
                    >
                      ›
                    </text>
                  </g>
                )}
              </g>
            )
          }

          const { card } = row
          const tone = toneOf(card)
          const fit = card.assessment?.fitScore
          const node = (
            <>
              <rect
                x={BOOK_CAND.x}
                y={row.y}
                width={BOOK_CAND.w}
                height={BOOK_CAND.h}
                rx={11}
                className="fill-cockpit-inset stroke-cockpit-line transition-colors group-hover:stroke-cockpit-edge"
                strokeWidth={1}
              />
              <circle
                cx={BOOK_CAND.x + CAND_PAD + 4}
                cy={row.y + BOOK_CAND.h / 2}
                r={4}
                className={DOT[tone]}
              />
              <text
                x={BOOK_CAND.x + CAND_TEXT}
                y={row.y + 26}
                className="fill-cockpit-text text-[13.5px] font-semibold"
              >
                {clip(card.candidateName, 34)}
              </text>
              <text
                x={BOOK_CAND.x + CAND_TEXT}
                y={row.y + 45}
                className="fill-cockpit-faint font-mono text-[11px]"
              >
                {fitMono(standing(card), CAND_LINE, 11)}
              </text>
              <text
                x={BOOK_CAND.x + BOOK_CAND.w - CAND_PAD}
                y={row.y + BOOK_CAND.h / 2 + 6}
                textAnchor="end"
                className={cn('font-mono text-[16px] font-semibold', TEXT[tone])}
              >
                {fit == null ? '—' : `${fit}/10`}
              </text>
            </>
          )
          return card.candidateId ? (
            <a
              key={card.id}
              href={`#kandidaten/${card.candidateId}`}
              className="group cursor-pointer"
              aria-label={`${card.candidateName}, Passung ${fit ?? 'nicht bewertet'} — Kandidatenakte öffnen`}
            >
              {node}
            </a>
          ) : (
            <g key={card.id}>{node}</g>
          )
        })}
      </svg>
    </div>
  )
}
