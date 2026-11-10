// Where a mandate stands — two words, because the recruiters have two.
//
// ELI-7 asks for `aktiv` and `inaktiv`, and adds the part that makes it a
// rule rather than a label: **inaktiv kann nicht wieder geöffnet werden, muss
// neu angelegt werden.** So this file is not just a label map — `isLive` is
// what every count on every screen reads, and `canReopen` is false forever.
//
// It was open · aktiv · geschlossen for a day, and open · on_hold · filled ·
// cancelled before that. Four filters could show none of the 18 mandates the
// aiFind importer had written as "closed", and the Suchprofil editor sends
// `status` on every save — so opening one of those, changing the salary band
// and saving came back HTTP 422, "unknown status 'closed'". 18 of 79 mandates
// could not be edited at all.
//
// Which is why the retired spellings still have labels here. The backend
// normalises them (`normalise_job_status`) and migration 0039 rewrites the
// rows, but this build may be talking to a backend that has not deployed
// yet — and a chip reading the raw word "closed" in a German cockpit is how
// the recruiters find out about our deployment pipeline.

import { t } from '@/i18n'
import type { Tone } from './primitives'

/** The states, in the order they happen. Inactive is final.
 *
 *  `lead` (ELI-22): an ad taken from Markt — business development, not a
 *  mandate. Not live business (`isLive` is false), it becomes `active` when the
 *  contract is won or `inactive` when it is not, and nothing goes back to it. */
export const JOB_STATUSES = ['lead', 'active', 'inactive'] as const

export type JobStatus = (typeof JOB_STATUSES)[number]

/** What the API may still serve → what it means now. Mirrors
 *  `app.domain.common.enums._STORED_JOB_STATUSES`. */
const RETIRED: Record<string, JobStatus> = {
  open: 'active',
  closed: 'inactive',
}

/** Today's word for whatever arrived. Unknown values pass through, so a state
 *  the backend grows is visible rather than quietly relabelled. */
export function jobStatus(value: string | null | undefined): string {
  if (!value) return 'active'
  return RETIRED[value.toLowerCase()] ?? value.toLowerCase()
}

/** Live business — on the books, whether or not anyone is pushing it today.
 *
 *  Every "how much is running" figure goes through this. Comparing against a
 *  literal is what made the cockpit count `status === 'open'` and silently
 *  leave out every mandate somebody had marked as actively worked. */
export function isLive(value: string | null | undefined): boolean {
  return jobStatus(value) === 'active'
}

export const JOB_STATUS_TONE: Record<string, Tone | undefined> = {
  lead: 'gold',
  active: 'mint',
  // Inactive keeps the neutral chip: it is the one state that is not news.
  inactive: undefined,
  open: 'mint',
  closed: undefined,
}

/** German is the source language, so the label IS the dictionary key.
 *
 *  Called rather than looked up in a constant, so the strings are read at
 *  render time: a map built at module scope freezes whichever language the
 *  page was opened in. */
export function jobStatusLabel(value: string): string {
  const canonical = jobStatus(value)
  if (canonical === 'lead') return t('Lead')
  if (canonical === 'active') return t('Aktiv')
  if (canonical === 'inactive') return t('Inaktiv')
  // A value the backend grew and this screen has not learned yet. Showing it
  // raw is ugly on purpose — better than a label that quietly says "Aktiv"
  // about something that is not.
  return value
}

/** The statuses a job in `value` may be set to — the backend's rules
 *  (`jobs.service.update_job`): a lead may be won or dropped, a mandate may
 *  finish, a finished one stays finished, and nothing goes back to lead. */
export function statusChoices(value: string | null | undefined): JobStatus[] {
  const current = jobStatus(value)
  if (current === 'lead') return ['lead', 'active', 'inactive']
  if (current === 'inactive') return ['inactive']
  return ['active', 'inactive']
}
