// The vocabulary for a Gesprächsnotiz — one list, two audiences (ELI-9).
//
// There were three of these before: the backend enum, the strings the aiFind
// import wrote ("BD Call", "N/A", "Meeting Notes"), and the list the
// recruiters actually use. The backend now normalises every stored spelling
// onto the third on the way out, so this file only has to label what arrives
// — and label it in the recruiters' own words, which are English terms
// inside a German UI because that is what they call them.
//
// The same shape as `jobStatus.ts`: the vocabulary, the tone and the label
// live together, so adding a kind is one edit rather than three.

import { t } from '@/i18n'

/** What may be filed against a MANAGER, in the order ELI-9 lists them. */
export const MANAGER_INTERACTION_KINDS = [
  'meeting',
  'client_call',
  'business_call',
  'message',
  'na',
  'note',
] as const

/** What may be filed against a CANDIDATE. Shorter: a candidate has no
 *  business calls and no client calls. */
export const CANDIDATE_INTERACTION_KINDS = [
  'candidate_call',
  'message',
  'na',
  'note',
] as const

export type InteractionKind =
  | (typeof MANAGER_INTERACTION_KINDS)[number]
  | (typeof CANDIDATE_INTERACTION_KINDS)[number]

/** Label for one stored kind.
 *
 *  Built inside a function, not a module constant: `t()` read once at import
 *  time freezes the language the page started in.
 *
 *  An unrecognised value is returned AS IS. That is the point — "Job Spec"
 *  and "Client Canvas" are on neither list and 44 real notes still carry
 *  them, so they show under their own name instead of being relabelled into
 *  something they are not. */
export function interactionLabel(value: string): string {
  switch (value) {
    case 'meeting':
      return t('Meeting Notes')
    case 'client_call':
      return t('Client Call')
    case 'business_call':
      return t('Business Call')
    case 'candidate_call':
      return t('Candidate Call')
    case 'message':
      return t('Message')
    case 'na':
      return t('NA (nicht erreicht)')
    case 'note':
      return t('Notiz')
    // Retired before ELI-9, still on older rows.
    case 'call':
      return t('Anruf')
    case 'email':
      return t('E-Mail')
    case 'briefing':
      return t('Briefing')
    case 'feedback':
      return t('Feedback')
    default:
      return value
  }
}

/** Whether a kind means somebody was actually reached.
 *
 *  Mirrors `CONTACT_INTERACTION_KINDS` in the backend and exists for the
 *  same reason: an unanswered call must not look like contact. Used only to
 *  move "letzter Kontakt" optimistically — the server decides for real. */
const NOT_CONTACT = new Set(['na', 'note', 'feedback'])

export function isContact(value: string): boolean {
  return !NOT_CONTACT.has(value)
}
