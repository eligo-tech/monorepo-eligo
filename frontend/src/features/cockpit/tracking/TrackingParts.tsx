// The pieces of the tracking surface (ELI-64): one KPI tile, the shared and
// dated goals, the Prozess funnel. Presentational — the screen and the
// Cockpit section fetch, these only draw.
//
// Two rules from ELI-15 hold for every piece: a number names its source, and
// a number nothing measures (or a step nobody was in) is a blank, never 0.

import { t } from '@/i18n'
import { date, num } from '@/i18n/format'

import type { ConsultantDTO, FunnelStepDTO, GoalDTO, KpiDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Panel } from '../ui/primitives'
import {
  daysLabel,
  formatValue,
  goalName,
  milestone,
  paceTone,
  progress,
  ratioLabel,
} from './trackingMath'

const BAR: Record<ReturnType<typeof paceTone>, string> = {
  mint: 'bg-mint-500',
  gold: 'bg-gold-500',
  coral: 'bg-coral-500',
}
const TEXT: Record<ReturnType<typeof paceTone>, string> = {
  mint: 'text-mint-300',
  gold: 'text-gold-300',
  coral: 'text-coral-300',
}

function Bar({ ist, ziel }: { ist: number; ziel: number }) {
  const share = progress(ist, ziel)
  return (
    <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-cockpit-inset">
      <div
        className={cn('h-full rounded-full transition-[width] duration-500', BAR[paceTone(share)])}
        style={{ width: `${share * 100}%` }}
      />
    </div>
  )
}

/** One KPI: Ist, Ziel if one is set, and where the number comes from. */
export function KpiTile({ kpi, compact = false }: { kpi: KpiDTO; compact?: boolean }) {
  if (!kpi.available || kpi.ist === null) {
    return (
      <Panel className="p-5">
        <p className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">{t(kpi.label)}</p>
        <p className="mt-3 text-[28px] font-semibold leading-none text-cockpit-faint">—</p>
        <p className="mt-3 text-[12px] leading-relaxed text-cockpit-dim">{t(kpi.unavailable_because)}</p>
      </Panel>
    )
  }
  const tone = paceTone(progress(kpi.ist, kpi.ziel))
  return (
    <Panel className={cn(compact ? 'p-4' : 'p-5')}>
      <p className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">{t(kpi.label)}</p>
      <div className="mt-3 flex flex-wrap items-baseline gap-2">
        <span
          className={cn(
            'font-mono text-[28px] font-semibold leading-none tabular-nums',
            kpi.ziel !== null ? TEXT[tone] : 'text-cockpit-text',
          )}
        >
          {formatValue(kpi.ist, kpi.unit)}
        </span>
        {kpi.ziel !== null && (
          <span className="font-mono text-[13px] text-cockpit-faint">
            / {formatValue(kpi.ziel, kpi.unit)}
          </span>
        )}
      </div>
      {kpi.ziel !== null ? (
        <Bar ist={kpi.ist} ziel={kpi.ziel} />
      ) : (
        !compact && <p className="mt-3 text-[12px] text-cockpit-faint">{t('Kein Ziel hinterlegt')}</p>
      )}
      {kpi.missing > 0 && (
        <p className="mt-2 text-[12px] text-gold-300">
          {kpi.missing === 1
            ? t('1 Deal ohne Honorar')
            : t('{n} Deals ohne Honorar', { n: num(kpi.missing) })}
        </p>
      )}
      <p className="mt-3 font-mono text-[11px] leading-relaxed text-cockpit-faint">
        {t('Quelle')}: {t(kpi.source)}
      </p>
    </Panel>
  )
}

/** The goals that belong to people — shared ("Jonas & Tobias") or one
 *  person's, possibly starting later ("ab 01.01.2027"). */
export function GoalsList({
  goals,
  kpi,
  people,
}: {
  goals: GoalDTO[]
  kpi: KpiDTO
  people: ConsultantDTO[]
}) {
  const mine = goals.filter((g) => g.kpi === kpi.key)
  if (mine.length === 0) return null
  return (
    <div className="space-y-2">
      {mine.map((goal) => (
        <Panel key={goal.id} className="p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-[14px] font-medium text-cockpit-text">
              {goalName(goal, people)}
              {goal.shared && (
                <span className="ml-2 font-mono text-[11px] uppercase tracking-wide text-cockpit-faint">
                  {t('gemeinsames Ziel')}
                </span>
              )}
            </span>
            <span className="font-mono text-[14px] tabular-nums text-cockpit-text">
              {formatValue(goal.ist, kpi.unit)}
              {goal.ziel !== null && (
                <span className="text-cockpit-faint"> / {formatValue(goal.ziel, kpi.unit)}</span>
              )}
            </span>
          </div>
          {goal.ziel !== null ? (
            <Bar ist={goal.ist} ziel={goal.ziel} />
          ) : (
            goal.valid_from && (
              <p className="mt-2 text-[12px] text-cockpit-faint">
                {t('Ziel gilt ab {date}', { date: date(goal.valid_from) })}
              </p>
            )
          )}
        </Panel>
      ))}
    </div>
  )
}

/** "Das Verhältnis … und die Zeit zwischen jedem einzelnen Schritt". */
export function FunnelPanel({ funnel }: { funnel: FunnelStepDTO[] }) {
  return (
    <Panel className="p-5">
      <div className="space-y-3">
        {funnel.map((step) => (
          <div
            key={`${step.from_key}-${step.to_key}`}
            className="grid grid-cols-1 items-baseline gap-1 border-b border-cockpit-line pb-3 last:border-0 last:pb-0 sm:grid-cols-[1fr_auto_auto] sm:gap-6"
          >
            <span className="text-[14px] text-cockpit-text">
              {milestone(step.from_key, step.from_label)}
              <span className="px-2 text-cockpit-faint">→</span>
              {milestone(step.to_key, step.to_label)}
            </span>
            <span className="font-mono text-[13px] tabular-nums text-cockpit-text">{ratioLabel(step)}</span>
            <span className="font-mono text-[13px] tabular-nums text-cockpit-dim">
              {daysLabel(step.median_days)}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-4 font-mono text-[11px] leading-relaxed text-cockpit-faint">
        {t('Quelle')}: {t('Prozess · Schrittdaten (erledigt, sonst geplant). Kohorte: Prozesse, deren erster Schritt im Zeitraum liegt. 2. Interview = Interviewtermin 2+ oder ein eigener Schritt „… Interview“.')}
      </p>
    </Panel>
  )
}
