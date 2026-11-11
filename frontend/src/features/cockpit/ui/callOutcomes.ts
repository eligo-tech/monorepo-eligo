// How a call to a contact ended — ELI-22's call list. Mirrors
// `app.domain.common.enums.CallOutcome`, in the same order, which is roughly
// the order a cold call can go.

import { t } from '@/i18n'
import type { Tone } from './primitives'

export const CALL_OUTCOMES = [
  'not_reached',
  'voicemail',
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
      return t('Nicht erreicht')
    case 'voicemail':
      return t('Mailbox')
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

export function canSaveCall(outcome: string, nextAt: string): boolean {
  if (!outcome) return false
  return !needsDate(outcome) || nextAt.trim() !== ''
}
