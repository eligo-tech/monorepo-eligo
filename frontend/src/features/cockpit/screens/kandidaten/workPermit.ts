// Arbeitserlaubnis — one list for every candidate form.
//
// The VALUES are the backend's `WorkPermitStatus` and are stored; only the
// labels are translated. Work permit is a deterministic hard filter in
// matching (`matching/service.apply_hard_filters`): `unknown` fails a mandate
// that requires a permit, so turning it into anything else is a statement
// about a person, made by a recruiter — never by a default on an edit form.

import { t } from '@/i18n'

export const WORK_PERMITS: { value: string; label: string }[] = [
  { value: 'unknown', label: t('Unbekannt') },
  { value: 'citizen', label: t('Staatsbürger') },
  { value: 'permanent', label: t('Unbefristet') },
  { value: 'work_visa', label: t('Arbeitsvisum') },
  { value: 'requires_sponsorship', label: t('Sponsoring nötig') },
  { value: 'none', label: t('Keine') },
]

/** ELI-28: "wir arbeiten nur mit Staatsbürgern oder Arbeitserlaubnis" — a new
 *  candidate starts as Staatsbürger; the recruiter changes it when it is not. */
export const NEW_CANDIDATE_WORK_PERMIT = 'citizen'

/** An existing record is shown as it is stored, `unknown` included. */
export function workPermitForEdit(stored: string | null | undefined): string {
  return stored || 'unknown'
}
