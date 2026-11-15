import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { AdoptPostingsResultDTO } from '@/api/types'
import { setLang } from '@/i18n'
import { adoptLeads, leadError, leadSummary } from './leadAdopt'

// ELI-26: "Als Lead übernehmen" said "Übernahme fehlgeschlagen." while the
// server had created the company AND the lead — the answer never reached the
// browser (production log: the request's writes, then no response line).
// The endpoint is idempotent, so the answer is to ask once more.

beforeEach(() => setLang('de'))

const ok = (over: Partial<AdoptPostingsResultDTO> = {}): AdoptPostingsResultDTO => ({
  created: 1,
  existing: 0,
  skipped: 0,
  results: [{ posting_id: 'p1', created: true, job_id: 'j1', company_id: 'c1', skipped: null }],
  ...over,
})

describe('taking ads as leads', () => {
  it('asks once more when the answer was lost on the way', async () => {
    const call = vi
      .fn<() => Promise<AdoptPostingsResultDTO>>()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(ok({ created: 0, existing: 1 }))
    const { result, retried } = await adoptLeads(call)
    expect(call).toHaveBeenCalledTimes(2)
    expect(retried).toBe(true)
    expect(result.existing).toBe(1)
  })

  it('does not repeat a request the server answered with an error', async () => {
    const call = vi.fn<() => Promise<AdoptPostingsResultDTO>>().mockRejectedValue(new ApiError(500, 'Internal Server Error'))
    await expect(adoptLeads(call)).rejects.toBeInstanceOf(ApiError)
    expect(call).toHaveBeenCalledTimes(1)
  })

  it('reports what the first, unanswered attempt took as taken — not as "already there"', () => {
    expect(leadSummary(ok({ created: 0, existing: 1 }), true)).toBe('1 als Lead in Mandate übernommen')
    expect(leadSummary(ok({ created: 0, existing: 1 }), false)).toBe('1 waren schon da')
    expect(leadSummary(ok({ created: 2, existing: 0, skipped: 1 }), false)).toBe(
      '2 als Lead in Mandate übernommen · 1 übersprungen (Agentur oder nicht mehr vorhanden)',
    )
  })
})

describe('why taking ads failed', () => {
  it('says the outcome is unknown when no answer came, and that retrying is safe', () => {
    expect(leadError(new TypeError('Failed to fetch'))).toBe(
      'Keine Antwort vom Server. Bitte erneut versuchen — schon übernommene Anzeigen werden nicht doppelt angelegt.',
    )
  })

  it('names an expired session, a missing permission and the rate limit', () => {
    expect(leadError(new ApiError(401, ''))).toBe('Sitzung abgelaufen — bitte neu anmelden.')
    expect(leadError(new ApiError(403, ''))).toBe('Keine Berechtigung in diesem Workspace.')
    expect(leadError(new ApiError(429, ''))).toBe('Zu viele Anfragen — bitte kurz warten und erneut versuchen.')
  })

  it("shows the server's own reason for a refused request", () => {
    expect(leadError(new ApiError(422, JSON.stringify({ detail: 'posting_ids: too many' })))).toBe(
      'Übernahme abgelehnt: posting_ids: too many',
    )
  })

  it('gives the status of a server failure instead of a bare "failed"', () => {
    expect(leadError(new ApiError(500, 'Internal Server Error'))).toBe('Übernahme fehlgeschlagen (Serverfehler 500).')
  })
})
