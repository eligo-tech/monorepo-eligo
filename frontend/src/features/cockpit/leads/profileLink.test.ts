import { describe, expect, it } from 'vitest'

import { parseProfileLink } from './profileLink'

// ELI-77: a contact from a pasted LinkedIn/XING profile link. The name is read
// from the link alone — nothing is fetched — and only where the slug says it
// plainly. Real-world shapes below.

const name = (url: string) => parseProfileLink(url)?.name ?? null

describe('the name from a LinkedIn link', () => {
  it('drops the trailing id and capitalises', () => {
    expect(name('https://www.linkedin.com/in/anna-berg-1a2b3c')).toBe('Anna Berg')
    expect(name('https://www.linkedin.com/in/anna-berg-87654321/')).toBe('Anna Berg')
    expect(name('https://www.linkedin.com/in/anna-berg')).toBe('Anna Berg')
    expect(name('https://www.linkedin.com/in/anna-maria-berg-b1234a56')).toBe('Anna Maria Berg')
  })

  it('reads a country subdomain, no scheme, query strings and fragments', () => {
    expect(name('https://de.linkedin.com/in/anna-berg-1a2b3c?originalSubdomain=de')).toBe('Anna Berg')
    expect(name('linkedin.com/in/anna-berg/')).toBe('Anna Berg')
    expect(name('https://www.linkedin.com/in/anna-berg-1a2b3c/?trk=public_profile#experience')).toBe('Anna Berg')
    expect(name('https://m.linkedin.com/in/anna-berg')).toBe('Anna Berg')
  })

  it('reads the legacy /pub/ shape', () => {
    expect(name('http://de.linkedin.com/pub/anna-berg/12/345/678')).toBe('Anna Berg')
  })

  it('keeps umlauts as written and does not guess them from ae/oe/ue', () => {
    expect(name('https://www.linkedin.com/in/j%C3%B6rg-m%C3%BCller-12ab')).toBe('Jörg Müller')
    expect(name('https://www.linkedin.com/in/joerg-mueller-12ab')).toBe('Joerg Mueller')
    expect(name('https://www.linkedin.com/in/uwe-kuehn')).toBe('Uwe Kuehn')
  })

  it('keeps particles lower-case, writes titles, drops degrees', () => {
    expect(name('https://www.linkedin.com/in/anna-von-berg-1a2b')).toBe('Anna von Berg')
    expect(name('https://www.linkedin.com/in/dr-anna-berg')).toBe('Dr. Anna Berg')
    expect(name('https://www.linkedin.com/in/anna-berg-mba')).toBe('Anna Berg')
  })

  it('a single word is not guessed into first and last name', () => {
    expect(name('https://www.linkedin.com/in/annaberg')).toBeNull()
    expect(name('https://www.linkedin.com/in/annaberg-123456')).toBeNull()
    expect(parseProfileLink('https://www.linkedin.com/in/annaberg')?.network).toBe('linkedin')
  })

  it('a digit inside the name is not a name', () => {
    expect(name('https://www.linkedin.com/in/anna2-berg')).toBeNull()
  })
})

describe('the name from a XING link', () => {
  it('reads Anna_Berg, with or without the trailing number', () => {
    expect(name('https://www.xing.com/profile/Anna_Berg')).toBe('Anna Berg')
    expect(name('https://www.xing.com/profile/Anna_Berg2/cv')).toBe('Anna Berg')
    expect(name('xing.com/profile/Joerg_Mueller?sc_o=da980_e')).toBe('Joerg Mueller')
  })
})

describe('one spelling per profile', () => {
  it('normalises host, query and trailing slash', () => {
    expect(parseProfileLink('https://de.linkedin.com/in/anna-berg-1a2b3c/?trk=x')?.url).toBe(
      'https://www.linkedin.com/in/anna-berg-1a2b3c',
    )
    expect(parseProfileLink('xing.com/profile/Anna_Berg/cv')?.url).toBe('https://www.xing.com/profile/Anna_Berg')
  })

  it('agrees with the server on odd links', () => {
    // Credentials: not a profile, whatever host the text names.
    expect(parseProfileLink('https://u:p@www.linkedin.com/in/anna')).toBeNull()
    expect(parseProfileLink('https://www.linkedin.com:pw@evil.com/in/x')).toBeNull()
    // Path tricks are not a person.
    expect(parseProfileLink('linkedin.com/in/../company/acme')).toBeNull()
    // The kind is case-insensitive, like the host.
    expect(parseProfileLink('https://www.linkedin.com/IN/anna-berg')?.url).toBe('https://www.linkedin.com/in/anna-berg')
  })

  it('anything else is not a profile', () => {
    for (const url of [
      '',
      'https://www.linkedin.com/company/nordlicht',
      'https://www.linkedin.com/jobs/view/123',
      'https://www.xing.com/jobs/hamburg-java-123',
      'https://www.stepstone.de/stellenangebote--Java-123.html',
      'https://notlinkedin.com/in/anna-berg',
      'ftp://linkedin.com/in/anna-berg',
    ])
      expect(parseProfileLink(url)).toBeNull()
  })
})
