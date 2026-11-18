// How a call to a contact ended — ELI-22's call list. Mirrors
// `app.domain.common.enums.CallOutcome`, in the same order, which is roughly
// the order a cold call can go.

import { t } from '@/i18n'
import type { Tone } from './primitives'

export const CALL_OUTCOMES = [
  'not_reached',
  'call_back',
  'wrong_person',
  'not_interested',
  'meeting_booked',
  'mandate',
] as const

export type CallOutcome = (typeof CALL_OUTCOMES)[number]

/** Read at render time, like every label: a module-scope map would freeze
 *  the language the page was opened in. */
export function callOutcomeLabel(value: string): string {
  switch (value) {
    case 'not_reached':
    // ELI-35: Mailbox is the same as not reached — no longer offered, and
    // calls stored with it read as what they were.
    case 'voicemail':
      return t('Nicht erreicht')
    case 'call_back':
      return t('Rückruf vereinbart')
    case 'wrong_person':
      return t('Falsche Person / nicht mehr da')
    case 'not_interested':
      return t('Kein Interesse')
    case 'meeting_booked':
      return t('Termin vereinbart')
    case 'mandate':
      return t('Mandat')
    default:
      return value
  }
}

export const CALL_OUTCOME_TONE: Record<string, Tone | undefined> = {
  call_back: 'gold',
  meeting_booked: 'mint',
  mandate: 'mint',
  not_interested: 'coral',
  wrong_person: 'coral',
}

/** A call-back without a date never comes due — the backend refuses it. */
export const needsDate = (outcome: string) => outcome === 'call_back'

/** ELI-35: the next call is a DAY ("Uhrzeit ist nicht relevant"): due from
 *  the start of that day in the recruiter's calendar. */
export function nextCallInstant(day: string): string | null {
  if (!day) return null
  const [y, m, d] = day.split('-').map(Number)
  return new Date(y, m - 1, d).toISOString()
}

/** An outcome is all a call needs — "Nicht erreicht" asks for no text (ELI-35);
 *  only a call-back needs its day. */
export function canSaveCall(outcome: string, nextAt: string): boolean {
  if (!outcome) return false
  return !needsDate(outcome) || nextAt.trim() !== ''
}
