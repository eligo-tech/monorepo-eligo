import { describe, expect, it } from 'vitest'

import { MIN_INTERVAL_MS, shouldRefresh } from './useRefreshOnFocus'

/** The event wiring needs a DOM and this repo has none; the decision does
 *  not, and the decision is the part that can be wrong in a way a user
 *  notices — either a pool re-fetched three times for one alt-tab, or a
 *  screen that sits on yesterday's data because the guard was too wide. */
describe('shouldRefresh', () => {
  it('refreshes when the tab has been away longer than the interval', () => {
    const now = 1_000_000
    expect(shouldRefresh(now - MIN_INTERVAL_MS - 1, now)).toBe(true)
  })

  it('refreshes exactly on the boundary', () => {
    const now = 1_000_000
    expect(shouldRefresh(now - MIN_INTERVAL_MS, now)).toBe(true)
  })

  it('collapses a burst of focus events into one refresh', () => {
    // Alt-tabbing through three windows fires visibilitychange three times.
    const now = 1_000_000
    expect(shouldRefresh(now - 200, now)).toBe(false)
    expect(shouldRefresh(now - 900, now)).toBe(false)
  })

  it('does not refresh on a focus event in the same millisecond', () => {
    expect(shouldRefresh(1_000_000, 1_000_000)).toBe(false)
  })

  it('leaves the interval short enough that a real trip away refreshes', () => {
    // A minute away from the tab is an ordinary interruption — a call, a
    // Slack thread — and must always come back to current data.
    expect(shouldRefresh(0, 60_000)).toBe(true)
    expect(MIN_INTERVAL_MS).toBeLessThanOrEqual(30_000)
  })
})
