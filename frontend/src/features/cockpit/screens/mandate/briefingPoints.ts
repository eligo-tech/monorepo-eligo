// Briefing-Bewertung (ELI-47) — names for the ten points, and the form.
//
// WHICH points are geklärt is the backend's decision (`app/domain/jobs/
// briefing.py`, returned as `JobDTO.briefing`). This module only says what
// each key is called, where its field sits, and how the form becomes a PATCH.
// Nothing here re-scores a mandate: two definitions of "geklärt" would
// disagree the first time one of them changed.

import { t } from '@/i18n'

import type { BriefingScoreDTO, JobDTO, JobUpdatePayload } from '@/api/types'

/** The backend's keys, in its order — `briefingPoints.test.ts` pins both. */
export const BRIEFING_KEYS = [
  'tasks',
  'must_have',
  'nice_to_have',
  'salary',
  'location',
  'start',
  'team_size',
  'contact',
  'interview_process',
  'vacancy_reason',
] as const

/** A point's name. `t()` runs per call, never at module scope (see i18n). */
export function pointLabel(key: string): string {
  switch (key) {
    case 'tasks':
      return t('Aufgaben')
    case 'must_have':
      return t('Muss-Kriterien')
    case 'nice_to_have':
      return t('Kann-Kriterien')
    case 'salary':
      return t('Gehaltsrahmen')
    case 'location':
      return t('Standort/Remote')
    case 'start':
      return t('Startdatum')
    case 'team_size':
      return t('Teamgröße')
    case 'contact':
      return t('Ansprechpartner beim Kunden')
    case 'interview_process':
      return t('Prozess beim Kunden')
    case 'vacancy_reason':
      return t('Grund der Vakanz')
    default:
      // A point a newer backend added: its key beats an empty row.
      return key
  }
}

export function missingLabel(key: string): string {
  return t('{point} fehlt', { point: pointLabel(key) })
}

export function scoreLine(score: BriefingScoreDTO): string {
  return t('{done} von {total} Punkten geklärt', { done: score.done, total: score.total })
}

/** Where a missing point is filled in. The contact is chosen among the
 *  client's people in the Stammdaten; everything else is a field below. */
export function pointTarget(key: string): { field: string } | { section: string } {
  switch (key) {
    case 'contact':
      return { section: 'section-stammdaten' }
    case 'must_have':
      return { field: 'must_have_skills' }
    case 'nice_to_have':
      return { field: 'nice_to_have_skills' }
    case 'salary':
      return { field: 'salary_min' }
    case 'start':
      return { field: 'start_date' }
    default:
      return { field: key }
  }
}

export interface BriefingDraft {
  tasks: string
  must_have_skills: string[]
  nice_to_have_skills: string[]
  salary_min: string
  salary_max: string
  location: string
  start_date: string
  team_size: string
  interview_process: string
  vacancy_reason: string
}

const num = (v?: number | null) => (v == null ? '' : String(v))

export function briefingDraft(job: JobDTO): BriefingDraft {
  return {
    tasks: job.tasks ?? '',
    must_have_skills: [...(job.must_have_skills ?? [])],
    nice_to_have_skills: [...(job.nice_to_have_skills ?? [])],
    salary_min: num(job.salary_min),
    salary_max: num(job.salary_max),
    location: job.location ?? '',
    start_date: job.start_date ?? '',
    team_size: job.team_size ?? '',
    interview_process: job.interview_process ?? '',
    vacancy_reason: job.vacancy_reason ?? '',
  }
}

const TEXT_FIELDS = [
  'tasks',
  'location',
  'start_date',
  'team_size',
  'interview_process',
  'vacancy_reason',
] as const

const LIST_FIELDS = ['must_have_skills', 'nice_to_have_skills'] as const

/** '' → null; anything that is not a whole non-negative number is refused
 *  rather than sent — a cap of 0 would exclude every candidate. */
function money(raw: string): number | null | undefined {
  const s = raw.trim()
  if (s === '') return null
  const n = Number(s)
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : undefined
}

const sameList = (a: string[], b: string[]) =>
  a.length === b.length && a.every((v, i) => v === b[i])

const clean = (list: string[]) => list.map((s) => s.trim()).filter(Boolean)

/** The PATCH for what the recruiter changed — measured against `base`, the
 *  draft as the form opened, NOT against the job as it is now. The job can
 *  change under an open form (a Muss-Kriterium added from the Suchprofil's
 *  chips), and diffing against it would send the stale draft value back and
 *  silently undo that edit — on a hard filter. Only what changed is sent,
 *  because every field sent leaves a receipt. */
export function briefingPatch(
  base: BriefingDraft,
  d: BriefingDraft,
): { ok: true; patch: JobUpdatePayload } | { ok: false; error: string } {
  const patch: JobUpdatePayload = {}
  for (const f of TEXT_FIELDS) {
    const next = d[f].trim() || null
    if (next !== (base[f].trim() || null)) patch[f] = next
  }
  for (const f of LIST_FIELDS) {
    const next = clean(d[f])
    if (!sameList(next, clean(base[f]))) patch[f] = next
  }
  const min = money(d.salary_min)
  const max = money(d.salary_max)
  if (min === undefined || max === undefined) {
    return { ok: false, error: t('Gehalt muss eine positive Zahl sein.') }
  }
  if (min !== null && max !== null && min > max) {
    return { ok: false, error: t('Gehalt von liegt über Gehalt bis.') }
  }
  if (d.salary_min.trim() !== base.salary_min.trim()) patch.salary_min = min
  if (d.salary_max.trim() !== base.salary_max.trim()) patch.salary_max = max
  return { ok: true, patch }
}
