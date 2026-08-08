// "02 Jobscoring" — how fillable each mandate is, two columns of score rows.

import { ScoreBar, scoreTone } from '../ui/ScoreBar'
import { SectionHeader } from '../ui/primitives'
import type { JobScore } from '../data/types'

export function JobScoringSection({ rows, isLive }: { rows: JobScore[]; isLive: boolean }) {
  const half = Math.ceil(rows.length / 2)
  const columns = [rows.slice(0, half), rows.slice(half)]

  // Summary stats are computed, not stated, so they can never drift from the rows.
  const average = rows.length
    ? Math.round(rows.reduce((sum, r) => sum + r.score.value, 0) / rows.length)
    : 0
  const strong = rows.filter((r) => r.score.value > 70).length
  const critical = rows.filter((r) => scoreTone(r.score.value) === 'coral').length

  return (
    <section className="space-y-5">
      <SectionHeader
        id="section-02"
        index="02"
        title="Jobscoring"
        hint={
          isLive
            ? 'Besetzbarkeit aus dem Matching · Deal-Chance noch nicht gelernt'
            : 'Besetzbarkeit & Deal-Chance · gelernt'
        }
      />

      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 font-mono text-[13px] text-cockpit-faint">
        <span>
          Ø <span className="text-cockpit-text">{average}</span>
        </span>
        <span>
          <span className="text-cockpit-text">{strong}</span> über 70
        </span>
        <span>
          <span className="text-coral-400">{critical}</span> kritisch
        </span>
        <span>M = Deal-Chance beim Manager</span>
      </div>

      <div className="grid gap-x-12 gap-y-1 lg:grid-cols-2">
        {columns.map((column, i) => (
          <div key={i} className="min-w-0">
            {column.map((row) => (
              <ScoreBar key={row.id} row={row} />
            ))}
          </div>
        ))}
      </div>
    </section>
  )
}
