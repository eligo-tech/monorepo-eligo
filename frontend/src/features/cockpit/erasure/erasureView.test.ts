import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { t } from '@/i18n'

import {
  confirmationNote,
  describeConfirmationError,
  namesMatch,
  suppressedOn,
  summary,
  todayIso,
  unprotected,
} from './erasureView'

const err = (status: number, detail: unknown) => new ApiError(status, JSON.stringify({ detail }))

describe('suppressedOn', () => {
  it('returns the date only for the suppression refusal', () => {
    expect(suppressedOn(err(409, { code: 'suppressed', requested_on: '2026-11-01' }))).toBe('2026-11-01')
  })
  it('ignores the other 409 — somebody else edited the record', () => {
    expect(suppressedOn(err(409, { code: 'stale' }))).toBeNull()
    expect(suppressedOn(new ApiError(409, 'plain text'))).toBeNull()
  })
})

describe('namesMatch', () => {
  it('ignores case and extra spaces, as the server does', () => {
    expect(namesMatch('  erika   MUSTER ', 'Erika Muster')).toBe(true)
  })
  it('refuses a different name and an empty record name', () => {
    expect(namesMatch('Erika', 'Erika Muster')).toBe(false)
    expect(namesMatch('x', null)).toBe(false)
  })
})

describe('the result', () => {
  it('flags a person nothing can stop coming back', () => {
    expect(unprotected({ suppressions_written: 0 })).toBe(true)
    expect(unprotected({ suppressions_written: 2 })).toBe(false)
  })
  it('counts rows, not the bookkeeping entries', () => {
    const s = summary({ candidates: 1, applications: 2, receipts_blacked_out: 5, suppressions_written: 2 })
    expect(s).toContain('3')
    expect(s).toContain('5')
  })
  it('says one record, not one records', () => {
    expect(summary({ candidates: 1, receipts_blacked_out: 1 })).not.toMatch(/1 (records|Datensätze|receipts|Quittungen)\b/)
  })
  it('gives today in Berlin, not UTC', () => {
    // 23:30 UTC on 1 Nov is already 2 Nov in Berlin.
    expect(todayIso(new Date('2026-11-01T23:30:00Z'))).toBe('2026-11-02')
  })
})

// ELI-32: the confirmation to the person. Compared through `t()`: another
// test file may have switched the language for the run.
describe('confirmationNote', () => {
  it('says what became of the erasure confirmation', () => {
    expect(confirmationNote('sent')).toEqual({ tone: 'mint', text: t('Bestätigung an die Person gesendet.') })
    expect(confirmationNote('not_configured')).toEqual({
      tone: 'gold',
      text: t('Keine Bestätigung gesendet: E-Mail-Versand ist auf diesem Server nicht eingerichtet.'),
    })
    expect(confirmationNote('no_email')?.text).toBe(
      t('Keine Bestätigung gesendet: Es war keine E-Mail-Adresse hinterlegt.'),
    )
    expect(confirmationNote('failed')?.tone).toBe('coral')
    expect(confirmationNote(null)).toBeNull()
    expect(confirmationNote(undefined)).toBeNull()
  })
})

describe('describeConfirmationError', () => {
  it('names the refusal instead of failing silently', () => {
    expect(describeConfirmationError(err(503, { code: 'email_not_configured' }))).toBe(
      t('E-Mail-Versand ist auf diesem Server nicht eingerichtet. Bitte den Betreiber informieren.'),
    )
    expect(describeConfirmationError(err(409, { code: 'no_email' }))).toBe(
      t('Für diese Person ist keine E-Mail-Adresse hinterlegt.'),
    )
    expect(describeConfirmationError(err(502, { code: 'email_rejected' }))).toBe(
      t('Der E-Mail-Dienst hat die Nachricht abgelehnt.'),
    )
    expect(describeConfirmationError(new Error('x'))).toBe(t('Senden fehlgeschlagen.'))
  })
})
