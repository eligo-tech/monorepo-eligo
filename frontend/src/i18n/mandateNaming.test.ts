import { describe, expect, it } from 'vitest'

import { EN } from './en'

// ELI-29 renamed the screen "Jobs" to "Mandate"; ELI-27 found copy that still
// sent people to "Jobs". A single job ad is still a job — the screen is not.
describe('the Mandate screen is never called Jobs', () => {
  it('in German or in English', () => {
    const stale = Object.entries(EN).filter(
      ([de, en]) => /\bJobs\b/.test(de) || /\bJobs\b/.test(en),
    )
    expect(stale).toEqual([])
  })
})
