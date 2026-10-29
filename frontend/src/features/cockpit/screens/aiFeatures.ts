// What one row of "KI-Funktionen" offers. Pure, so it is tested without a DOM.
//
// The role only decides what the screen OFFERS. The server checks the same
// token and refuses a non-admin's consent with 403 — a hidden button is a
// courtesy, not the control (see useMe.ts).

import type { FeatureStatusDTO } from '@/api/types'

export type FeatureAction = 'hidden' | 'accept' | 'wait-for-admin' | 'revoke' | 'none'

export function featureAction(f: FeatureStatusDTO, admin: boolean): FeatureAction {
  // Not released by the operator: nothing to decide here, and a list of
  // things you cannot have is noise on a settings page.
  if (!f.available) return 'hidden'
  if (f.enabled) return admin ? 'revoke' : 'none'
  return admin ? 'accept' : 'wait-for-admin'
}
