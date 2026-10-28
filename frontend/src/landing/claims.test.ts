// Every claim on the landing page must be one we can back up.
//
// This product sells "every claim is checked against a real source". The page
// selling it shipped invented numbers (−48% time-to-shortlist, 94% match
// accuracy), a testimonial from a person who is not a customer, a "Trusted by"
// row of companies that are not customers, an ISO 27001 chip we do not hold,
// and "GDPR-compliant", which ARCHITECTURE.md forbids until its gaps close.
// A made-up testimonial or logo is also misleading advertising under the UWG.
//
// The test reads the source, so a claim cannot come back in either language.

import { describe, expect, it } from 'vitest'

const src = Object.values(
  import.meta.glob('./LandingPage.tsx', { query: '?raw', import: 'default', eager: true }),
)[0] as string

describe('landing page claims', () => {
  const forbidden: [string, RegExp][] = [
    ['invented stat: time-to-shortlist', /−48%|-48%/],
    ['invented stat: match accuracy', /Match-Genauigkeit|Match accuracy/],
    ['invented stat: 24/7', /24\/7/],
    ['testimonial from a non-customer', /Maren Kaltenbach|Peer Ventures/],
    ['"Trusted by" logos of non-customers', /Trusted by|Im Einsatz bei|Doctolib|Celonis|Bitpanda/],
    ['certification we do not hold', /ISO 27001/],
    ['"GDPR-compliant" (ARCHITECTURE.md forbids it)', /GDPR-compliant|DSGVO-konform/],
    ['unmeasured onboarding time', /15 minutes|15 Minuten/],
    ['sourcing agent is not built', /Sourcing-Agent|sources, verifies and matches/],
    ['enrichment agent is not built', /Fills gaps in contact/],
    ['EU hosting is unverified for the backend', /EU-hosted|EU-gehostet|stays in the EU|bleiben in der EU/],
  ]
  it.each(forbidden)('does not claim: %s', (_name, re) => {
    expect(src).not.toMatch(re)
  })

  // Lantern-style structure: each section exists and is reachable by anchor.
  it.each(['how-it-works', 'platform', 'workflows', 'controls', 'faq'])(
    'has a #%s section',
    (id) => {
      expect(src).toContain(`id="${id}"`)
    },
  )

  it('states independence in the hero', () => {
    expect(src).toMatch(/Bootstrapped/)
    expect(src).toMatch(/Built in Germany/)
  })

  it('labels illustrative workflows as not customer results', () => {
    expect(src).toMatch(/not a customer result/)
  })
})
