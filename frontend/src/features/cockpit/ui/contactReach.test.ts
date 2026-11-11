import { describe, expect, it } from 'vitest'
import { networkLinks } from './contactReach'

// ELI-23: a contact without a phone must still be reachable — the profile if
// one is stored, otherwise the same people search Markt offers.
describe('network links of a contact', () => {
  it('use a stored profile when there is one', () => {
    const links = networkLinks({
      full_name: 'Nicole Lauchner',
      company_name: 'STW GmbH',
      linkedin_url: 'https://www.linkedin.com/in/nicole-lauchner',
      xing_url: null,
    })
    expect(links.linkedin).toEqual({ href: 'https://www.linkedin.com/in/nicole-lauchner', profile: true })
    expect(links.xing.profile).toBe(false)
  })

  it('otherwise search the person at the company, without the legal form', () => {
    const links = networkLinks({ full_name: 'Nicole Lauchner', company_name: 'STW GmbH', linkedin_url: null, xing_url: null })
    expect(links.linkedin.href).toBe('https://www.linkedin.com/search/results/people/?keywords=Nicole%20Lauchner%20STW')
    expect(links.xing.href).toBe('https://www.xing.com/search/members?keywords=Nicole%20Lauchner%20STW')
  })
})
