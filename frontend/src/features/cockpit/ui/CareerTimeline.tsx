// The career timeline: one bar per station on a shared year axis, so a
// recruiter sees at a glance what the list below can only be read for —
// how long each tenure was, which roles overlapped, and where the holes are.
//
// Hand-rolled SVG, like ui/Gauge.tsx. Percentage x-coordinates rather than a
// viewBox, so the bars reflow with the drawer and nothing is stretched.
//
// It draws only what the dates support: `buildTimeline` returns null when
// fewer than two stations carry a readable date, and the caption prints what
// it could not place. A career chart is read as a fact about a person, so a
// bar inferred from a date nobody wrote down would be worse than no chart.

import { useMemo } from 'react'

import { t } from '@/i18n'
import type { RoleEntry } from '@/data/types'
import { cn } from '@/lib/cn'
import { BENIGN_GAP_MONTHS, buildTimeline, pct } from './careerSpans'

/** Row pitch and bar thickness, in px. The bar is thin on purpose: the chart
 *  is a reading aid above the list, not the section's centrepiece. */
const ROW = 20
const BAR = 8

/** A one-month tenure on a thirty-year axis is 0.28% — a hairline nobody
 *  sees. The floor is a rendering minimum, not a claim about duration; it
 *  moves the bar's right edge by at most a few months of axis. */
const MIN_WIDTH = 0.4

export function CareerTimeline({
  roles,
  className,
}: {
  roles: RoleEntry[]
  className?: string
}) {
  const tl = useMemo(() => buildTimeline(roles), [roles])
  if (!tl) return null

  const x = (months: number) => pct(months, tl.from, tl.to)
  const height = tl.spans.length * ROW
  const lastYear = tl.openEnded ? t('heute') : String(tl.to / 12 - 1)

  return (
    <figure className={cn('select-none', className)}>
      <div className="relative mb-1.5 h-3">
        {tl.ticks.map((year) => (
          <span
            key={year}
            className="absolute top-0 font-mono text-[10px] tabular-nums text-cockpit-faint"
            style={{ left: `${x(year * 12)}%`, transform: shift(x(year * 12)) }}
          >
            {year}
          </span>
        ))}
      </div>

      <svg width="100%" height={height} aria-hidden>
        {tl.ticks.map((year) => (
          <rect
            key={year}
            x={`${x(year * 12)}%`}
            y={0}
            width={1}
            height={height}
            className="fill-cockpit-line"
          />
        ))}

        {tl.gaps.map((gap) => (
          <rect
            key={gap.from}
            x={`${x(gap.from)}%`}
            y={0}
            width={`${x(gap.to) - x(gap.from)}%`}
            height={height}
            opacity={0.55}
            className="fill-coral-800"
          >
            <title>{t('Lücke: {n} Monate', { n: gap.months })}</title>
          </rect>
        ))}

        {tl.spans.map((span, i) => (
          <rect
            key={i}
            x={`${x(span.from)}%`}
            y={i * ROW + (ROW - BAR) / 2}
            width={`${Math.max(MIN_WIDTH, x(span.to) - x(span.from))}%`}
            height={BAR}
            rx={2}
            // Mint 500 is the cockpit's "live" tone; a finished station is
            // the same hue stepped back, so the current job reads first.
            className={span.open ? 'fill-mint-500' : 'fill-mint-700'}
          >
            <title>{label(span.role)}</title>
          </rect>
        ))}
      </svg>

      <figcaption className="mt-2 font-mono text-[11px] text-cockpit-faint">
        <span>{t('{n} Stationen', { n: tl.spans.length })}</span>
        <span aria-hidden> · </span>
        <span className="tabular-nums">{`${tl.from / 12}–${lastYear}`}</span>
        {/* What the chart cannot vouch for goes on its own line rather than
            into the run of separators, where a wrap leaves a dangling `·`. */}
        {(tl.gaps.length > 0 || tl.undated > 0) && (
          <span className="mt-0.5 block">
            {tl.gaps.length > 0 && (
              <span className="text-coral-300">
                {tl.gaps.length === 1
                  ? t('Eine Lücke > {m} Monate', { m: BENIGN_GAP_MONTHS })
                  : t('{n} Lücken > {m} Monate', { n: tl.gaps.length, m: BENIGN_GAP_MONTHS })}
              </span>
            )}
            {tl.gaps.length > 0 && tl.undated > 0 && <span aria-hidden> · </span>}
            {tl.undated > 0 && (
              <span className="text-gold-300">
                {tl.undated === 1
                  ? t('Eine Station ohne verwertbare Daten, nicht abgebildet')
                  : t('{n} Stationen ohne verwertbare Daten, nicht abgebildet', { n: tl.undated })}
              </span>
            )}
          </span>
        )}
      </figcaption>
    </figure>
  )
}

/** The hover text for a bar: the role as the source wrote it, including its
 *  own date strings — the chart measures those, it does not restate them. */
function label(role: RoleEntry): string {
  return [role.title, role.company, role.period].filter(Boolean).join(' · ')
}

/** Keep the first and last year label inside the box instead of centring it
 *  on a tick that sits on the edge. */
const shift = (x: number): string =>
  x < 4 ? 'none' : x > 96 ? 'translateX(-100%)' : 'translateX(-50%)'
