import { beforeEach, describe, expect, it } from 'vitest'

import { setLang } from '@/i18n'

import {
  CONNECTION_NOTE_LIMIT,
  cleanTitle,
  draftMessage,
  linkedInPeopleSearchUrl,
  searchKeywords,
  suggestTerms,
  xingPeopleSearchUrl,
} from './linkedinSearch'

// ELI-51: a mandate's own record becomes a LinkedIn people search the
// recruiter opens in their own browser, and a message they send themselves.
// Every term says which field of the mandate it came from.

beforeEach(() => setLang('de'))

const mandate = {
  title: 'Senior Java Entwickler (m/w/d)',
  mustHave: ['Java', 'Spring Boot', 'Kubernetes', 'PostgreSQL'],
  certifications: ['AWS Solutions Architect'],
  location: '80331 München, Bayern',
}

describe('suggested search terms', () => {
  it('derive from title, Muss-Kriterien, certifications and Ort — each with its source', () => {
    const terms = suggestTerms(mandate)
    expect(terms.map((term) => [term.text, term.source])).toEqual([
      ['Senior Java Entwickler', 'title'],
      ['Spring Boot', 'must'],
      ['Kubernetes', 'must'],
      ['PostgreSQL', 'must'],
      ['AWS Solutions Architect', 'cert'],
      ['München', 'location'],
    ])
  })

  it('drop a skill the title already names, case-insensitively', () => {
    const terms = suggestTerms(mandate)
    expect(terms.some((term) => term.text === 'Java')).toBe(false)
  })

  it('select the title, the first two Muss-Kriterien and the Ort by default', () => {
    const selected = suggestTerms(mandate)
      .filter((term) => term.selected)
      .map((term) => term.text)
    expect(selected).toEqual(['Senior Java Entwickler', 'Spring Boot', 'Kubernetes', 'München'])
  })

  it('split a title that names alternatives into separate title terms', () => {
    const terms = suggestTerms({ title: 'Elektroniker / Mechatroniker (w/m/d)', mustHave: [] })
    expect(terms.map((term) => term.text)).toEqual(['Elektroniker', 'Mechatroniker'])
    expect(terms.every((term) => term.source === 'title')).toBe(true)
  })

  it('drop a skill only when the title names it as a whole word', () => {
    const terms = suggestTerms({ title: 'JavaScript Developer', mustHave: ['Java', 'C', 'R'] })
    expect(terms.map((term) => term.text)).toEqual(['JavaScript Developer', 'Java', 'C', 'R'])
  })

  it('keep the town when the Ort also says Remote', () => {
    const terms = suggestTerms({ title: 'Data Engineer', mustHave: [], location: 'München / Remote' })
    expect(terms.map((term) => term.text)).toEqual(['Data Engineer', 'München'])
  })

  it('leave Remote and an empty Ort out', () => {
    expect(suggestTerms({ title: 'Data Engineer', mustHave: [], location: 'Remote' })).toHaveLength(1)
    expect(suggestTerms({ title: 'Data Engineer', mustHave: [], location: null })).toHaveLength(1)
  })

  it('never invent a term for an empty mandate', () => {
    expect(suggestTerms({ title: '  ', mustHave: [' '], location: '' })).toEqual([])
  })
})

describe('cleanTitle', () => {
  it.each([
    ['Buchhalter (m/w/d)', 'Buchhalter'],
    ['Buchhalter m/w/d', 'Buchhalter'],
    ['Buchhalter (all genders)', 'Buchhalter'],
    ['Buchhalter*in (gn)', 'Buchhalter'],
    ['Buchhalter (w/m/divers)', 'Buchhalter'],
  ])('%s → %s', (raw, clean) => {
    expect(cleanTitle(raw)).toBe(clean)
  })
})

describe('the LinkedIn keywords', () => {
  it('quote multi-word terms and OR the title alternatives together', () => {
    const terms = suggestTerms({
      title: 'Elektroniker / Mechatroniker (w/m/d)',
      mustHave: ['SPS Programmierung'],
      location: 'Stuttgart',
    })
    expect(searchKeywords(terms)).toBe(
      '(Elektroniker OR Mechatroniker) "SPS Programmierung" Stuttgart',
    )
  })

  it('quote a term with brackets or a boolean word, so it cannot act as an operator', () => {
    const terms = suggestTerms({ title: 'Berater', mustHave: ['SAP(FI)', 'OR'] }).map((term) => ({
      ...term,
      selected: true,
    }))
    expect(searchKeywords(terms)).toBe('Berater "SAP(FI)" "OR"')
  })

  it('use only the selected terms', () => {
    const terms = suggestTerms(mandate).map((term) => ({
      ...term,
      selected: term.source === 'title',
    }))
    expect(searchKeywords(terms)).toBe('"Senior Java Entwickler"')
  })

  it('open LinkedIn and Xing people search with the keywords url-encoded', () => {
    expect(linkedInPeopleSearchUrl('"Java Entwickler" München')).toBe(
      'https://www.linkedin.com/search/results/people/?keywords=%22Java%20Entwickler%22%20M%C3%BCnchen',
    )
    expect(xingPeopleSearchUrl('Java')).toBe('https://www.xing.com/search/members?keywords=Java')
  })
})

describe('the drafted message', () => {
  it('names the role, the Ort and the first Muss-Kriterien, with a name to fill in', () => {
    const text = draftMessage(mandate, { form: 'Sie', length: 'short' })
    expect(text).toContain('Senior Java Entwickler')
    expect(text).toContain('München')
    expect(text).toContain('Java')
    expect(text).toContain('[Name]')
    expect(text).not.toContain('(m/w/d)')
  })

  it('fits a LinkedIn connection note even for a long mandate', () => {
    const long = {
      title: 'Leiter Qualitätsmanagement und Regulatory Affairs Medizintechnik Europa (m/w/d)'.repeat(3),
      mustHave: Array.from({ length: 12 }, (_, i) => `Sehr lange Qualifikation Nummer ${i}`),
      location: 'Garmisch-Partenkirchen',
    }
    for (const form of ['Sie', 'Du'] as const) {
      const text = draftMessage(long, { form, length: 'short' })
      expect(text.length).toBeLessThanOrEqual(CONNECTION_NOTE_LIMIT)
      expect(text).toContain('[')
    }
  })

  it('stays German in an English UI — it goes to a German-speaking candidate', () => {
    setLang('en')
    for (const length of ['short', 'long'] as const) {
      const text = draftMessage(mandate, { form: 'Sie', length })
      expect(text).toContain('Guten Tag [Name]')
      expect(text).toContain('Viele Grüße')
    }
  })

  it('never exceeds the limit, even with an absurd title and nothing else', () => {
    for (const title of ['X'.repeat(400), 'X'.repeat(299), '']) {
      const text = draftMessage({ title, mustHave: ['Y'.repeat(200)], location: 'Z'.repeat(100) }, {
        form: 'Sie',
        length: 'short',
      })
      expect(text.length).toBeLessThanOrEqual(CONNECTION_NOTE_LIMIT)
    }
  })

  it('speaks Du when asked', () => {
    const text = draftMessage(mandate, { form: 'Du', length: 'short' })
    expect(text).toContain('[Vorname]')
    expect(text).toMatch(/\bdu\b|\bdein/i)
  })

  it('has a longer variant that lists the Muss-Kriterien', () => {
    const text = draftMessage(mandate, { form: 'Sie', length: 'long' })
    expect(text.length).toBeGreaterThan(draftMessage(mandate, { form: 'Sie', length: 'short' }).length)
    for (const skill of mandate.mustHave) expect(text).toContain(skill)
  })
})
