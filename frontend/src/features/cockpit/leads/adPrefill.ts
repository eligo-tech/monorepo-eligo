// ELI-73: "+ Lead" filled from a job ad. The server reads an ad Markt holds
// (looked up by its own reference, never opened) or the pasted ad text, and
// proposes; this decides what of the proposal lands in the form. A field is
// the proposal's to fill while it is empty or still holds what the LAST fill
// put there — never one the recruiter typed. Nothing is saved until
// "Lead anlegen".

import type { LeadPrefillDTO } from '@/api/types'

import type { LeadForm } from './manualLead'

/** The fields a fill may write. */
export const PREFILL_FIELDS = ['jobTitle', 'companyName', 'sourceUrl', 'fullName', 'roleTitle', 'email', 'phone'] as const
type Field = (typeof PREFILL_FIELDS)[number]

/** The form with the proposal in its free fields. `person` is the index of
 *  the person the recruiter picked when the ad names several, or null.
 *  `previous` holds the values the last fill wrote (see `filledBy`). */
export function applyPrefill(
  form: LeadForm,
  p: LeadPrefillDTO,
  person: number | null,
  previous: Partial<Pick<LeadForm, Field>> = {},
): LeadForm {
  const c = person !== null ? p.contacts[person] : undefined
  const proposed: Record<Field, string | null | undefined> = {
    jobTitle: p.job_title,
    companyName: p.company_name,
    // The ad's own page — what the lead records as where it came from. A
    // pasted text has none: the link already there stays.
    sourceUrl: p.source_url ?? form.sourceUrl,
    fullName: c?.full_name,
    roleTitle: c?.role_title,
    email: c?.email,
    phone: c?.phone,
  }
  const next = { ...form, fromPastedText: p.found === 'text' }
  for (const f of PREFILL_FIELDS) {
    const ours = !form[f].trim() || (previous[f] !== undefined && form[f] === previous[f])
    if (ours) next[f] = proposed[f] ?? ''
  }
  return next
}

/** What a fill wrote: the fields it changed, with their new values. Passed
 *  back as `previous`, so the next fill or person pick may replace exactly
 *  these — and nothing typed before or since. */
export function filledBy(before: LeadForm, after: LeadForm): Partial<Pick<LeadForm, Field>> {
  const out: Partial<Pick<LeadForm, Field>> = {}
  for (const f of PREFILL_FIELDS) if (after[f] !== before[f]) out[f] = after[f]
  return out
}

/** The person to take at once: the ad's only one; with several, the
 *  recruiter picks. */
export const defaultPerson = (p: LeadPrefillDTO): number | null => (p.contacts.length === 1 ? 0 : null)
