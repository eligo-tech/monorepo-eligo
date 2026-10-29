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

// A renamed file makes this import fail to resolve, which fails the suite.
import src from './LandingPage.tsx?raw'

describe('landing page claims', () => {
  const forbidden: [string, RegExp][] = [
    ['invented stat: time-to-shortlist', /[−-]\s?48\s?%/],
    ['invented stat: match accuracy', /Match-Genauigkeit|Match accuracy/i],
    ['invented stat: 24/7', /24\/7/],
    ['testimonial from a non-customer', /Maren Kaltenbach|Peer Ventures/i],
    ['"Trusted by" logos of non-customers', /Trusted by|Im Einsatz bei|\bN26\b|Doctolib|Celonis|Bitpanda/i],
    ['certification we do not hold', /ISO\s?27001|SOC\s?2|certified|zertifiziert/i],
    ['"GDPR compliant" (ARCHITECTURE.md forbids it)', /GDPR[\s-]?compliant|DSGVO[\s-]?konform|Built for GDPR|Für die DSGVO gebaut/i],
    ['unmeasured onboarding time', /15\s?minutes|15\s?Minuten/i],
    ['sourcing agent is not built', /Sourcing-Agent|sources, verifies and matches/i],
    ['enrichment agent is not built', /Fills gaps in contact/i],
    ['EU hosting is unverified for the backend', /EU[\s-]?hosted|EU[\s-]?gehostet|hosted in the EU|in der EU gehostet|stays in the EU|bleiben in der EU/i],
    ['receipts are hash-chained, not signed', /cryptographic(ally)?\s+sign|kryptografisch|Signatur\b/i],
    // Verification commits automatically; human review is only a flag.
    ['no human approval step exists', /human approval|menschliche Freigabe|people decide|Menschen entscheiden/i],
    ['verification does not cover imports or manual edits', /Before every write|Vor jedem Schreibvorgang/i],
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
