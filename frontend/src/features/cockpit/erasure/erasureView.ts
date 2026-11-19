// Pure helpers for erasure (GDPR Art. 17/21): what the server refused, whether
// a typed name matches, and how to say what an erasure did.

import { ApiError } from '@/api/client'
import type { ErasureConfirmation } from '@/api/types'
import { t } from '@/i18n'

interface Refusal {
  code: string | null
  requested_on?: string
}

/** The server's coded refusal, if the error carries one. */
export function refusal(e: unknown): Refusal | null {
  if (!(e instanceof ApiError)) return null
  try {
    const body = JSON.parse(e.message) as { detail?: { code?: string; requested_on?: string } }
    return { code: body.detail?.code ?? null, requested_on: body.detail?.requested_on }
  } catch {
    return null
  }
}

/** The day the person asked to be erased, when the server refused to create
 *  or edit someone for that reason; otherwise null. A 409 for a concurrent
 *  edit is NOT this — only the code decides. */
export function suppressedOn(e: unknown): string | null {
  const r = refusal(e)
  return r?.code === 'suppressed' && r.requested_on ? r.requested_on : null
}

/** Same fold as the server: whitespace collapsed, case ignored. */
export function namesMatch(typed: string, actual: string | null | undefined): boolean {
  const fold = (v: string) => v.split(/\s+/).filter(Boolean).join(' ').toLocaleLowerCase('de')
  return !!actual && fold(typed) === fold(actual)
}

/** Today in Berlin as YYYY-MM-DD — the default for "asked on". */
export function todayIso(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Berlin' }).format(now)
}

/** Nothing could be fingerprinted — no e-mail and no import id — so nothing
 *  stops this person being imported or added again. Must be said out loud. */
export function unprotected(counts: Record<string, number>): boolean {
  return (counts.suppressions_written ?? 0) === 0
}

/** "4 Datensätze gelöscht · 7 Quittungen geschwärzt" — numbers only. */
export function summary(counts: Record<string, number>): string {
  const removed = Object.entries(counts)
    .filter(([k]) => k !== 'receipts_blacked_out' && k !== 'suppressions_written')
    .reduce((n, [, v]) => n + v, 0)
  const receipts = counts.receipts_blacked_out ?? 0
  const rows = removed === 1 ? t('1 Datensatz gelöscht') : t('{n} Datensätze gelöscht', { n: String(removed) })
  const blacked =
    receipts === 1 ? t('1 Quittung geschwärzt') : t('{n} Quittungen geschwärzt', { n: String(receipts) })
  return `${rows} · ${blacked}`
}

/** ELI-32: what became of the confirmation the erasure was asked to send —
 *  said out loud, never swallowed. Null when none was asked for. */
export function confirmationNote(
  c: ErasureConfirmation | null | undefined,
): { tone: 'mint' | 'gold' | 'coral'; text: string } | null {
  switch (c) {
    case 'sent':
      return { tone: 'mint', text: t('Bestätigung an die Person gesendet.') }
    case 'not_configured':
      return { tone: 'gold', text: t('Keine Bestätigung gesendet: E-Mail-Versand ist auf diesem Server nicht eingerichtet.') }
    case 'no_email':
      return { tone: 'gold', text: t('Keine Bestätigung gesendet: Es war keine E-Mail-Adresse hinterlegt.') }
    case 'failed':
      return { tone: 'coral', text: t('Die Bestätigung konnte nicht gesendet werden — der E-Mail-Dienst hat sie abgelehnt.') }
    default:
      return null
  }
}

/** ELI-32: why "Bestätigung senden" did not send. */
export function describeConfirmationError(e: unknown): string {
  switch (refusal(e)?.code) {
    case 'email_not_configured':
      return t('E-Mail-Versand ist auf diesem Server nicht eingerichtet. Bitte den Betreiber informieren.')
    case 'no_email':
      return t('Für diese Person ist keine E-Mail-Adresse hinterlegt.')
    case 'email_rejected':
      return t('Der E-Mail-Dienst hat die Nachricht abgelehnt.')
    case 'not_marked':
      return t('Diese Person ist nicht als „Nicht mehr kontaktieren“ markiert.')
  }
  return t('Senden fehlgeschlagen.')
}

export function describeEraseError(e: unknown): string {
  switch (refusal(e)?.code) {
    case 'name_mismatch':
      return t('Der eingegebene Name stimmt nicht mit dem Datensatz überein.')
    case 'not_found':
      return t('Diesen Datensatz gibt es in diesem Workspace nicht mehr.')
    case 'erasure_not_configured':
      return t('Löschen ist auf diesem Server noch nicht eingerichtet. Bitte den Betreiber informieren.')
  }
  if (e instanceof ApiError && e.status === 403) return t('Nur Administratoren dürfen Personen löschen.')
  return t('Fehlgeschlagen — nichts gelöscht.')
}
