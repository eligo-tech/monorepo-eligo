import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'

// ELI-27: Markt's two new filters reach the server as the route expects them.
async function sent(params: Parameters<typeof api.hubSearch>[0]): Promise<URLSearchParams> {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ items: [], total: 0, next_cursor: null, corrections: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
  await api.hubSearch(params)
  const url = String((fetchMock.mock.calls[0] as unknown[])[0])
  return new URL(url, 'http://x').searchParams
}

afterEach(() => vi.unstubAllGlobals())

describe('hubSearch filters', () => {
  it('asks to leave out agencies only when told to', async () => {
    expect((await sent({ q: 'pflege', excludeAgencies: true })).get('exclude_agencies')).toBe('true')
    expect((await sent({ q: 'pflege' })).has('exclude_agencies')).toBe(false)
  })

  it('sends each size bucket as its own param', async () => {
    expect((await sent({ q: 'pflege', sizes: ['s', 'xl'] })).getAll('size')).toEqual(['s', 'xl'])
    expect((await sent({ q: 'pflege' })).has('size')).toBe(false)
  })
})
