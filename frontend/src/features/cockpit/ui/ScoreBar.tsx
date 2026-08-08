// One row of "02 Jobscoring": mandate label, fill bar, score, delta, manager chance.

import { cn } from '@/lib/cn'
import type { JobScore } from '../data/types'
import { Figure, ProvenanceMark } from './primitives'

/** Score thresholds — mint is fillable, gold needs work, coral is at risk. */
export function scoreTone(score: number): 'mint' | 'gold' | 'coral' {
  if (score >= 70) return 'mint'
  if (score >= 50) return 'gold'
  return 'coral'
}

const BAR = { mint: 'bg-mint-400', gold: 'bg-gold-400', coral: 'bg-coral-400' } as const
const TEXT = { mint: 'text-mint-400', gold: 'text-gold-400', coral: 'text-coral-400' } as const

export function ScoreBar({ row }: { row: JobScore }) {
  const tone = scoreTone(row.score.value)

  return (
    <div className="flex items-center gap-4 py-1.5">
      <span className="w-[236px] shrink-0 truncate text-[15px] text-cockpit-text">
        <span className="font-mono text-cockpit-dim">{row.mandateRef}</span>
        <span className="text-cockpit-faint"> · </span>
        {row.title}
      </span>

      <div className="h-[7px] min-w-0 flex-1 overflow-hidden rounded-full bg-[#2c2e22]">
        <div
          className={cn('h-full rounded-full', BAR[tone])}
          style={{ width: `${Math.max(0, Math.min(100, row.score.value))}%` }}
        />
      </div>

      <Figure
        figure={row.score}
        className={cn('w-9 shrink-0 text-right text-[17px]', TEXT[tone])}
      />

      {/* Change since the last data run — "—" when nothing has learned it yet. */}
      <span className="w-9 shrink-0 text-right font-mono text-[13px] text-cockpit-faint">
        {row.delta === null ? (
          <span title="Kein Signal-Store — Veränderung noch nicht gelernt">—</span>
        ) : (
          <>
            {row.delta.value > 0 ? '+' : ''}
            {row.delta.value}
            <ProvenanceMark provenance={row.delta.provenance} source={row.delta.source} />
          </>
        )}
      </span>

      <span className="w-[70px] shrink-0 text-right font-mono text-[13px] text-cockpit-faint">
        {row.managerChance === null ? (
          <span title="Deal-Chance beim Manager — noch nicht gelernt">M —</span>
        ) : (
          <>
            M {row.managerChance.value}%
            <ProvenanceMark
              provenance={row.managerChance.provenance}
              source={row.managerChance.source}
            />
          </>
        )}
      </span>
    </div>
  )
}
