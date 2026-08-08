// The 01 Umsatz gauge: a 270° ring split at actual/target, amber behind the
// split and mint ahead of it (the headroom the potential can still fill).
// Pure SVG — no chart library, matching src/features/reporting/PieChart.tsx.

import { cn } from '@/lib/cn'
import type { Figure as FigureModel } from '../data/types'
import { Money, ProvenanceMark } from './primitives'

// Degrees run clockwise from 12 o'clock (0 = top, 90 = right, 225 = bottom-left).
// Starting bottom-left and sweeping 270° puts the ring's gap at the bottom and
// the target tick at bottom-right, as drawn in the mockups.
const SWEEP = 270
const START = 225

const polar = (cx: number, cy: number, r: number, deg: number) => {
  const rad = ((deg - 90) * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

/** SVG arc path from `fromDeg` to `toDeg`, clockwise. */
function arc(cx: number, cy: number, r: number, fromDeg: number, toDeg: number): string {
  const a = polar(cx, cy, r, fromDeg)
  const b = polar(cx, cy, r, toDeg)
  const large = Math.abs(toDeg - fromDeg) > 180 ? 1 : 0
  return `M ${a.x} ${a.y} A ${r} ${r} 0 ${large} 1 ${b.x} ${b.y}`
}

export function Gauge({
  actual,
  potential,
  target,
  caption,
  className,
}: {
  actual: FigureModel
  potential: FigureModel
  target: FigureModel
  caption: string
  className?: string
}) {
  const size = 340
  const c = size / 2
  const r = 132
  const stroke = 15

  const ratio = target.value > 0 ? Math.min(actual.value / target.value, 1) : 0
  const split = START + SWEEP * ratio
  const pct = Math.round(ratio * 100)

  return (
    <div className={cn('relative', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <defs>
          <filter id="gauge-glow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Track */}
        <path
          d={arc(c, c, r, START, START + SWEEP)}
          fill="none"
          stroke="#1c1d18"
          strokeWidth={stroke + 8}
          strokeLinecap="round"
        />

        {/* Headroom ahead of the split */}
        <path
          d={arc(c, c, r, split, START + SWEEP)}
          fill="none"
          stroke="#a9d6b4"
          strokeWidth={stroke}
          strokeLinecap="round"
          opacity={0.85}
          filter="url(#gauge-glow)"
        />

        {/* Achieved */}
        {ratio > 0.001 && (
          <path
            d={arc(c, c, r, START, split)}
            fill="none"
            stroke="#e3a75c"
            strokeWidth={stroke}
            strokeLinecap="round"
            filter="url(#gauge-glow)"
          />
        )}

        {/* Tick at the split — where we stand against target */}
        <line
          {...(() => {
            const inner = polar(c, c, r - stroke, split)
            const outer = polar(c, c, r + stroke, split)
            return { x1: inner.x, y1: inner.y, x2: outer.x, y2: outer.y }
          })()}
          stroke="#f4f4ef"
          strokeWidth={2.5}
          strokeLinecap="round"
        />

        {/* Target tick at the end of the sweep */}
        <line
          {...(() => {
            const inner = polar(c, c, r - stroke * 0.6, START + SWEEP)
            const outer = polar(c, c, r + stroke * 0.6, START + SWEEP)
            return { x1: inner.x, y1: inner.y, x2: outer.x, y2: outer.y }
          })()}
          stroke="#f4f4ef"
          strokeWidth={2}
          strokeLinecap="round"
          opacity={0.5}
        />
      </svg>

      {/* Centre readout */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
        <Money
          figure={actual}
          compact
          className="text-[46px] font-medium leading-none tracking-tight text-cockpit-text"
        />
        <div className="font-mono text-[15px] text-gold-400">
          {pct}% Ziel
          <ProvenanceMark provenance={target.provenance} source={target.source} />
        </div>
        <div className="font-mono text-[15px] text-gold-400">
          + <Money figure={potential} compact /> Boost
        </div>
        <div className="mt-1 font-mono text-[12px] uppercase tracking-[0.18em] text-cockpit-faint">
          {caption}
        </div>
      </div>
    </div>
  )
}

/** Small percentage ring — top-left of each process card. */
export function ProgressRing({
  figure,
  size = 46,
}: {
  figure: FigureModel
  size?: number
}) {
  const r = (size - 6) / 2
  const circumference = 2 * Math.PI * r
  const filled = (Math.max(0, Math.min(100, figure.value)) / 100) * circumference

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#22241d" strokeWidth={3} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="#86c69a"
          strokeWidth={3}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-[12px] text-mint-400">
        {Math.round(figure.value)}%
        <ProvenanceMark provenance={figure.provenance} source={figure.source} />
      </span>
    </div>
  )
}
