import { useEffect, useRef } from 'react'

/** Ignore a return that follows the last refresh too closely.
 *
 *  Alt-tabbing through three windows fires `visibilitychange` three times in
 *  a second, and a pool of several hundred candidates is not worth fetching
 *  three times to answer the same question. Long enough to collapse that,
 *  short enough that a real trip away from the tab always refreshes. */
export const MIN_INTERVAL_MS = 10_000

/** Pure so it can be tested without a DOM — this repo has no jsdom, and the
 *  part worth pinning is the decision, not the event wiring. */
export function shouldRefresh(
  lastAt: number,
  now: number,
  minIntervalMs: number = MIN_INTERVAL_MS,
): boolean {
  return now - lastAt >= minIntervalMs
}

/**
 * Re-run `refresh` when the user comes back to the tab.
 *
 * The cockpit has no realtime transport — no socket, no polling — so a screen
 * left open shows whatever the list held when it mounted. For a workspace
 * with one user that is invisible; with two it means a colleague's correction
 * never arrives, and the first sign of it is a phone call to a number that
 * was fixed an hour ago.
 *
 * Returning to the tab is the cheap, honest refresh point: it is when a
 * recruiter looks at the data again, it costs one request, and it needs no
 * infrastructure. It is deliberately NOT a substitute for live updates —
 * nothing arrives while the tab simply sits in front of somebody.
 *
 * `enabled` exists so a caller can hold the refresh off while something must
 * not be disturbed. Pass `false` and the listener still runs but does
 * nothing, which keeps the hook order stable.
 */
export function useRefreshOnFocus(refresh: () => void, enabled = true): void {
  //: `refresh` is usually an inline arrow, so a new identity every render.
  //: Kept in a ref the effect can read, or the listener would be torn down
  //: and rebuilt on every keystroke in the search box.
  const latest = useRef(refresh)
  latest.current = refresh

  const lastAt = useRef(Date.now())
  const on = useRef(enabled)
  on.current = enabled

  useEffect(() => {
    function onVisible() {
      if (document.visibilityState !== 'visible') return
      if (!on.current) return
      const now = Date.now()
      if (!shouldRefresh(lastAt.current, now)) return
      lastAt.current = now
      latest.current()
    }
    document.addEventListener('visibilitychange', onVisible)
    //: Switching between two windows of the same browser fires `focus`
    //: without ever hiding the document, so `visibilitychange` alone misses
    //: the commonest way of coming back on a desktop.
    window.addEventListener('focus', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
    }
  }, [])
}
