// A 429 from the per-user request limits (review 2026-10-31 #5 C): how long
// to wait, so a screen can say so instead of printing the raw JSON.

import { ApiError } from '@/api/client'
import { t } from '@/i18n'

/** Seconds to wait when the server refused for rate; otherwise null. */
export function retryAfter(e: unknown): number | null {
  if (!(e instanceof ApiError) || e.status !== 429) return null
  try {
    const body = JSON.parse(e.message) as { detail?: { retry_after?: number } }
    return Math.max(1, Math.round(body.detail?.retry_after ?? 60))
  } catch {
    return 60
  }
}

/** The sentence a screen shows, or null when this was not a rate refusal. */
export function rateLimitMessage(e: unknown): string | null {
  const s = retryAfter(e)
  return s === null ? null : t('Zu viele Anfragen in kurzer Zeit — bitte {s} Sekunden warten.', { s: String(s) })
}
