// The admission gate has exactly one decision worth testing, and it is the
// one that can lock a working user out of a working product: which failures
// of `GET /me` mean "this organization has no workspace".
//
// Only 403 does. Everything else has to let the app through, because the
// alternative is a full-screen "your workspace is not set up" in front of a
// recruiter whose connection dropped for a second — a confident, wrong, and
// unrecoverable-looking message where the honest answer is the cockpit's own
// per-section degradation.

import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { admissionAfterFailure } from './AuthGate'

describe('admissionAfterFailure', () => {
  it('refuses on 403 — the backend only 403s an organization it was never told to admit', () => {
    expect(admissionAfterFailure(new ApiError(403, 'kein Arbeitsbereich'))).toBe('refused')
  })

  it('does not refuse on 401 — an unrefreshed token is not a missing workspace', () => {
    expect(admissionAfterFailure(new ApiError(401, 'missing bearer token'))).toBe('unreachable')
  })

  it.each([500, 502, 503, 504, 429, 404])('does not refuse on %i', (status) => {
    expect(admissionAfterFailure(new ApiError(status, ''))).toBe('unreachable')
  })

  it('does not refuse when the request never arrived', () => {
    // What `fetch` throws when the network is gone: not an ApiError at all.
    expect(admissionAfterFailure(new TypeError('Failed to fetch'))).toBe('unreachable')
  })

  it('does not refuse on something that is not an Error', () => {
    for (const thrown of [undefined, null, 'forbidden', 403, { status: 403 }]) {
      expect(admissionAfterFailure(thrown)).toBe('unreachable')
    }
  })
})
