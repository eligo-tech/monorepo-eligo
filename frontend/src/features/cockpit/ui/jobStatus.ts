// Where a mandate stands — one list, because it was three.
//
// The Jobs screen had four filters, the Suchprofil editor had the same four
// hardcoded again, and the backend validated against a third copy. All three
// agreed on open · on_hold · filled · cancelled, and all three were wrong
// about the data: no workspace had a single on_hold, filled or cancelled row,
// while 18 live mandates carried `closed`, written by the aiFind importer
// from its `is_open` boolean, which none of the three allowed.
//
// What that cost, beyond a grey chip spelling out a raw column value: no
// filter could show those 18, and the editor sends `status` on every save —
// so opening a closed mandate's Suchprofil, changing the salary band and
// saving it came back HTTP 422, "unknown status 'closed'". Eighteen of
// seventy-nine mandates could not be edited at all.
//
// `active` is the new one and the point of ELI-7: sixty-one mandates are
// open, and a recruiter needs to say which of them they are working now.
// Filled and cancelled are not here because they are *reasons* a mandate
// closed rather than states it sits in, and the one place that distinction
// matters — "this one was filled, open the next" — reads it off the pipeline,
// where the placement actually happened.

import { t } from '@/i18n'
import type { Tone } from './primitives'

/** The three states, in the order they happen. */
export const JOB_STATUSES = ['open', 'active', 'closed'] as const

export type JobStatus = (typeof JOB_STATUSES)[number]

export const JOB_STATUS_TONE: Record<string, Tone | undefined> = {
  open: 'lav',
  active: 'mint',
  // Closed keeps the neutral chip: it is the one state that is not news.
  closed: undefined,
}

/** German is the source language, so the label IS the dictionary key.
 *
 *  Called rather than looked up in a constant, so the strings are read at
 *  render time: a map built at module scope freezes whichever language the
 *  page was opened in. */
export function jobStatusLabel(value: string): string {
  if (value === 'open') return t('Offen')
  if (value === 'active') return t('Aktiv')
  if (value === 'closed') return t('Geschlossen')
  // A value the backend grew and this screen has not learned yet. Showing it
  // raw is ugly on purpose — better than a label that quietly says "Offen"
  // about something that is not.
  return value
}
