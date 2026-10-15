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

type Tone = keyof typeof STROKE

/** The fit score decides the tone, on the same thresholds as everything else:
 *  `scoreTone` owns ≥70 mint / ≥50 gold / else coral, and the assessment is
 *  scored 0–10. An unassessed candidate has no tone, not a bad one. */
function toneOf(card: ProcessCard): Tone {
  const fit = card.assessment?.fitScore
  return fit === null || fit === undefined ? 'none' : scoreTone(fit * 10)
}

/** Where the process stands — the same line the collapsed card shows. */
function standing(card: ProcessCard): string {
  const out = card.steps.find((s) => s.state === 'out')
  if (out) return `abgesagt · ${out.label}`
  const current = card.steps.find((s) => s.state === 'current')
  if (current) return current.label
  const done = [...card.steps].reverse().find((s) => s.state === 'done')
  return done ? `${done.label} ✓` : 'noch kein Schritt'
}

/** Cut a label to fit its box. SVG does not wrap, and an ellipsis is more
 *  honest than a name that runs out of the panel. */
function clip(text: string, max: number): string {
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
