import { describe, expect, it } from 'vitest'

// Switching workspace left a black screen until a manual refresh.
//
// Given an `after…OrganizationUrl`, Clerk's `setActive` puts the session into
// a transition state (user and organization `undefined`, so `<SignedIn>` and
// `<SignedOut>` both render nothing) and waits for the navigation to that URL
// to finish it. Every URL we gave was a hash route on the same page
// (`/#cockpit`, `/#Kandidaten`). A hash change never reloads, so the
// transition never ended. Reproduced on production 2026-11-10: `#root` empty,
// `Clerk.user === undefined`, no error thrown. The same `setActive` without a
// redirect re-rendered the cockpit with the new workspace's data.
//
// Without the prop the switch is a plain state change, and `AdmissionGate`
// remounts the app for the new organization. This test keeps the props out.
const sources = import.meta.glob('../**/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const REDIRECT_PROPS = /after(Select|Create|Leave)OrganizationUrl/

describe('workspace switch', () => {
  it('never hands Clerk a redirect URL for an organization change', () => {
    const offenders = Object.entries(sources)
      .filter(([, text]) => REDIRECT_PROPS.test(text))
      .map(([file]) => file)
    expect(offenders).toEqual([])
  })

  it('actually reads the sources it checks', () => {
    // A glob that matched nothing would make the test above pass for nothing.
    expect(Object.keys(sources).some((f) => f.endsWith('CommandBar.tsx'))).toBe(true)
  })
})
