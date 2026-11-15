// ELI-26: taking Markt ads into Jobs as leads, and saying why it failed.
//
// In production the request created the company and the lead, and the answer
// never reached the browser: the screen said "Übernahme fehlgeschlagen." about
// a lead that existed. `POST /hub/postings/adopt` is idempotent — an ad already
// taken comes back as `existing` — so a lost answer is recovered by asking once
// more. A request the server ANSWERED with an error is not repeated.

import { ApiError } from '@/api/client'
import type { AdoptPostingsResultDTO } from '@/api/types'
import { t } from '@/i18n'

/** Run the adopt call; one more time if no answer came back at all. */
export async function adoptLeads(
  call: () => Promise<AdoptPostingsResultDTO>,
): Promise<{ result: AdoptPostingsResultDTO; retried: boolean }> {
  try {
    return { result: await call(), retried: false }
  } catch (e) {
    if (e instanceof ApiError) throw e
    return { result: await call(), retried: true }
  }
}

/** The line under the ads. After a retry, what the unanswered first attempt
 *  took comes back as `existing` — it was taken just now, not before. */
export function leadSummary(result: AdoptPostingsResultDTO, retried: boolean): string {
  const taken = result.created + (retried ? result.existing : 0)
  const before = retried ? 0 : result.existing
  const parts: string[] = []
  if (taken) parts.push(t('{n} als Lead in Jobs übernommen', { n: String(taken) }))
  if (before) parts.push(t('{n} waren schon da', { n: String(before) }))
  if (result.skipped)
    parts.push(t('{n} übersprungen (Agentur oder nicht mehr vorhanden)', { n: String(result.skipped) }))
  return parts.join(' · ')
}

/** FastAPI's `detail`: a sentence, or a validation error list. */
function serverReason(body: string): string | null {
  try {
    const detail: unknown = JSON.parse(body)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d: unknown) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : null))
        .filter(Boolean)
      return msgs.length ? msgs.join('; ') : null
    }
  } catch {
    // Not JSON: no reason worth showing.
  }
  return null
}

export function leadError(e: unknown): string {
  if (!(e instanceof ApiError))
    return t('Keine Antwort vom Server. Bitte erneut versuchen — schon übernommene Anzeigen werden nicht doppelt angelegt.')
  if (e.status === 401) return t('Sitzung abgelaufen — bitte neu anmelden.')
  if (e.status === 403) return t('Keine Berechtigung in diesem Workspace.')
  if (e.status === 429) return t('Zu viele Anfragen — bitte kurz warten und erneut versuchen.')
  const reason = e.status < 500 ? serverReason(e.message) : null
  if (reason) return t('Übernahme abgelehnt: {reason}', { reason })
  return t('Übernahme fehlgeschlagen (Serverfehler {status}).', { status: String(e.status) })
}
