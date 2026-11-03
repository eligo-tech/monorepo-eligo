import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'

import { ReaddDeclined, registerReaddAsker, withReaddConfirm } from './readd'

const suppressed = new ApiError(409, JSON.stringify({ detail: { code: 'suppressed', requested_on: '2026-11-01' } }))

let unregister: (() => void) | null = null
afterEach(() => unregister?.())

describe('withReaddConfirm', () => {
  it('sends once without the override when nothing is refused', async () => {
    const run = vi.fn(async (o: boolean) => o)
    expect(await withReaddConfirm(run)).toBe(false)
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('asks with the date, and retries with the override on yes', async () => {
    const ask = vi.fn(async () => true)
    unregister = registerReaddAsker(ask)
    const run = vi.fn(async (o: boolean) => {
      if (!o) throw suppressed
      return 'created'
    })
    expect(await withReaddConfirm(run)).toBe('created')
    expect(ask).toHaveBeenCalledWith('2026-11-01')
    expect(run.mock.calls.map((c) => c[0])).toEqual([false, true])
  })

  it('creates nothing on no', async () => {
    unregister = registerReaddAsker(async () => false)
    const run = vi.fn(async () => {
      throw suppressed
    })
    await expect(withReaddConfirm(run)).rejects.toBeInstanceOf(ReaddDeclined)
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('treats a missing dialog as no, never as yes', async () => {
    const run = vi.fn(async () => {
      throw suppressed
    })
    await expect(withReaddConfirm(run)).rejects.toBeInstanceOf(ReaddDeclined)
  })

  it('passes every other error through untouched', async () => {
    const stale = new ApiError(409, JSON.stringify({ detail: { code: 'stale' } }))
    await expect(withReaddConfirm(async () => Promise.reject(stale))).rejects.toBe(stale)
  })
})
