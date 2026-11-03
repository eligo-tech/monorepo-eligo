import { describe, expect, it } from 'vitest'

// The runner has no browser, so `preferredLang()` resolves to English: these
// read the English copy. The German source is pinned by the dictionary tests.

import type { AgencyReasonDTO } from '@/api/types'
import { probeAgencyFinder, reasonText, verdictTone, withAgencyScreen } from './agencyCopy'

const r = (code: string, evidence: Record<string, unknown> = {}, points?: number): AgencyReasonDTO => ({
  code,
  evidence,
  points: points ?? null,
})

describe('every reason reads as a sentence with its evidence', () => {
  it('names the word in the name that marks a staffing firm', () => {
    expect(reasonText(r('name', { name: 'Zebrafink Personalberatung' }))).toBe('Name: Zebrafink Personalberatung')
  })
  it('counts the ads that speak of a client', () => {
    expect(reasonText(r('client_phrase', { postings: 2 }))).toBe('“Unser Mandant” or similar in 2 ads')
  })
  it('lists the matching mail domains', () => {
    expect(reasonText(r('mail_domain', { domains: ['dis-ag.com'] }))).toBe('Contact domain: dis-ag.com')
  })
  it('scores carry their points', () => {
    expect(reasonText(r('size', { open_postings: 4 }, 3))).toBe('+3 · 4 open ads')
    expect(reasonText(r('hiring_recruiters', { postings: 1, posting_ids: ['p'] }, 2))).toBe('+2 · hiring recruiters itself (1)')
  })
  it('client signals read as such', () => {
    expect(reasonText(r('also_employer'))).toBe('also in the corpus as an employer')
    expect(reasonText(r('public_body', { name: 'Stadt Frankfurt' }))).toBe('public body: Stadt Frankfurt')
  })
  it('an unknown code from a newer backend still shows, never crashes', () => {
    expect(reasonText(r('something_new', { x: 1 }))).toBe('something_new')
  })
})

describe('verdict tones', () => {
  it('agency is mint, unclear is gold, client has no tone', () => {
    expect(verdictTone('agency')).toBe('mint')
    expect(verdictTone('unclear')).toBe('gold')
    expect(verdictTone('client')).toBeUndefined()
  })
})

describe('who sees the Agenturen tab', () => {
  const fetchWith = (status: number) => async () => new Response('{}', { status })

  it('appears when the server answers', async () => {
    expect(await probeAgencyFinder(fetchWith(200))).toBe(true)
  })
  it.each([404, 401, 500])('stays hidden on %i', async (status) => {
    expect(await probeAgencyFinder(fetchWith(status))).toBe(false)
  })
  it('stays hidden when the network fails', async () => {
    expect(
      await probeAgencyFinder(async () => {
        throw new TypeError('offline')
      }),
    ).toBe(false)
  })
  it('is inserted after Projekte only when allowed', () => {
    const screens = [
      { key: 'markt' as const, label: 'Markt' },
      { key: 'projekte' as const, label: 'Projekte' },
      { key: 'jobs' as const, label: 'Jobs' },
    ]
    expect(withAgencyScreen(screens, false).map((s) => s.key)).toEqual(['markt', 'projekte', 'jobs'])
    expect(withAgencyScreen(screens, true).map((s) => s.key)).toEqual(['markt', 'projekte', 'agenturen', 'jobs'])
  })
})

describe('adopting with a contact', () => {
  it('sends a source the backend accepts, and the ad as provenance', async () => {
    const { contactPayload } = await import('./agencyCopy')
    const payload = contactPayload({
      key: 'beispiel',
      full_name: 'Jana Beispiel',
      salutation: 'Frau',
      first_name: 'Jana',
      last_name: 'Beispiel',
      role_title: null,
      email: 'j.beispiel@zebrafink-personal.de',
      phone: null,
      mention_count: 1,
      manager_id: null,
      evidence: [{ posting_id: 'p1', url: 'https://www.arbeitsagentur.de/jobsuche/jobdetail/1' } as never],
    })
    // The backend's ConfidenceSource enum; "third_party" was a 422 (2026-11-03).
    expect(['document_extraction', 'third_party_source', 'public_web', 'human_verified', 'self_reported']).toContain(payload.source)
    expect(payload.source).toBe('public_web')
    expect(payload.source_detail).toBe('https://www.arbeitsagentur.de/jobsuche/jobdetail/1')
  })
})

describe('loading pages without mixing answers', () => {
  it('only the newest request may write', async () => {
    const { latestOnly } = await import('./agencyCopy')
    const gate = latestOnly()
    const older = gate.next()
    const newer = gate.next()
    expect(gate.isCurrent(older)).toBe(false)
    expect(gate.isCurrent(newer)).toBe(true)
  })
  it('appending a page drops rows already shown', async () => {
    const { appendPage } = await import('./agencyCopy')
    const a = { id: 'a' }, b = { id: 'b' }, c = { id: 'c' }
    expect(appendPage([a, b], [b, c], 2).map((x) => x.id)).toEqual(['a', 'b', 'c'])
    expect(appendPage([a, b], [c], 0).map((x) => x.id)).toEqual(['c'])
  })
  it('no verdict selected means nothing to ask for', async () => {
    const { nothingSelected } = await import('./agencyCopy')
    expect(nothingSelected([])).toBe(true)
    expect(nothingSelected(['client'])).toBe(false)
  })
})

describe('the probe tolerates one hiccup', () => {
  it('a 503 then a 200 shows the tab', async () => {
    const answers = [503, 200]
    expect(await probeAgencyFinder(async () => new Response('{}', { status: answers.shift()! }), 0)).toBe(true)
  })
  it('a 404 is final — no second ask', async () => {
    let calls = 0
    const ok = await probeAgencyFinder(async () => {
      calls += 1
      return new Response('{}', { status: 404 })
    }, 0)
    expect([ok, calls]).toEqual([false, 1])
  })
})
