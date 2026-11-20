// The arithmetic and wording of the tracking numbers (ELI-15, ELI-64).
//
// Kept apart from the components because every rule here is one that can be
// wrong in a way nobody notices on screen: a goal of 0 divides, a funnel step
// nobody was in must not read as 0 %, and "2 von 3" has to stay visible next
// to the percentage so a small number is not mistaken for a trend.

import { t } from '@/i18n'
import { money, num } from '@/i18n/format'
import type { ConsultantDTO, FunnelStepDTO, GoalDTO, KpiDTO } from '@/api/types'

/** Where a figure sits against its goal, as a share of the bar (0–1). */
export function progress(ist: number | null, ziel: number | null): number {
  if (ist === null || ziel === null || ziel <= 0) return 0
  return Math.max(0, Math.min(1, ist / ziel))
}

/** Three bands rather than a gradient, so the bar and the figure agree. */
export function paceTone(share: number): 'mint' | 'gold' | 'coral' {
  if (share >= 0.9) return 'mint'
  if (share >= 0.6) return 'gold'
  return 'coral'
}

/** A KPI value in its unit — euros for Umsatz, a count otherwise. */
export function formatValue(value: number, unit: KpiDTO['unit']): string {
  return unit === 'eur' ? money(value) : num(value)
}

/** "2 von 3 · 67 %", or "—" when nobody was in the step at all. */
export function ratioLabel(step: Pick<FunnelStepDTO, 'reached' | 'of' | 'ratio'>): string {
  if (step.of === 0 || step.ratio === null) return '—'
  return t('{n} von {m} · {pct} %', {
    n: num(step.reached),
    m: num(step.of),
    pct: num(Math.round(step.ratio * 100)),
  })
}

/** "Ø 7 Tage" (median), or "—" when no pair of dates could be measured. */
export function daysLabel(days: number | null): string {
  if (days === null) return '—'
  const rounded = Math.round(days * 10) / 10
  return rounded === 1 ? t('Median 1 Tag') : t('Median {d} Tage', { d: num(rounded) })
}

/** The funnel's milestones, named here so the copy is translatable. */
export const MILESTONE_LABEL: Record<string, () => string> = {
  vorgestellt: () => t('CV gesendet'),
  interview_1: () => t('1. Interview'),
  interview_2: () => t('2. Interview'),
  final: () => t('Final Interview'),
  offer: () => t('Angebot'),
  deal: () => t('Deal'),
}

export const milestone = (key: string, fallback: string): string =>
  MILESTONE_LABEL[key]?.() ?? fallback

/** Who a goal belongs to: its label, else the people's names. */
export function goalName(goal: Pick<GoalDTO, 'label' | 'members'>, people: ConsultantDTO[]): string {
  if (goal.label) return goal.label
  const names = new Map(people.map((p) => [p.actor_user_id, p.name]))
  return goal.members.map((m) => names.get(m) || m).join(' & ')
}

/** The tile keys a person can choose: every KPI, plus the funnel. */
export const PROCESS_TILE = 'process'
