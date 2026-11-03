import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'

import { rateLimitMessage, retryAfter } from './rateLimit'

describe('retryAfter', () => {
  it('reads the wait from the 429 body', () => {
    const e = new ApiError(429, JSON.stringify({ detail: { code: 'rate_limited', retry_after: 17 } }))
    expect(retryAfter(e)).toBe(17)
    expect(rateLimitMessage(e)).toContain('17')
  })
  it('falls back to a minute when the body is not JSON', () => {
    expect(retryAfter(new ApiError(429, 'Too Many Requests'))).toBe(60)
  })
  it('is null for every other error', () => {
    expect(retryAfter(new ApiError(409, '{}'))).toBeNull()
    expect(rateLimitMessage(new Error('x'))).toBeNull()
  })
})
