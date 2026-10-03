// The scorer decides what a recruiter sees when they type. Each case here is
// a query someone would actually type at this dataset.

import { describe, expect, it } from 'vitest'
import { editDistance, fold, searchScore } from './search'

/** A mandate row as JobsScreen builds it. */
const row = (title: string, client: string, location = '', status = 'open') => [
  { text: title, weight: 3 },
  { text: client, weight: 3 },
  { text: location, weight: 2 },
  { text: status, weight: 1 },
]

const GE = row(
  'Senior Backend-Entwickler mit Architekturkenntnissen (Position 1)',
  'GE Software',
  'München',
)
const CC = row('ServiceNow Entwickler', 'Computacenter AG & Co. oHG', 'Kerpen', 'filled')
const SIXT = row('COC Lead', 'Sixt', 'Pullach')

describe('fold', () => {
  it('folds German the way a German keyboard avoids it', () => {
    expect(fold('München')).toBe('muenchen')
    expect(fold('Muenchen')).toBe('muenchen')
    expect(fold('Groß-Gerau')).toBe('gross gerau')
  })

  it('keeps the mandate reference findable', () => {
    expect(fold('#A-7f3c')).toBe('#a 7f3c')
  })
})

describe('editDistance', () => {
  it('counts a transposition once', () => {
    expect(editDistance('sofwtare', 'software', 2)).toBe(1)
  })

  it('gives up at the cap instead of counting to the end', () => {
    expect(editDistance('architekt', 'sixt', 2)).toBeGreaterThan(2)
  })
})

describe('searchScore', () => {
  it('matches the exact company', () => {
    expect(searchScore(GE, 'GE Software')).toBeGreaterThan(0)
    expect(searchScore(CC, 'GE Software')).toBe(0)
  })

  it('survives a typo', () => {
    expect(searchScore(GE, 'Softwre')).toBeGreaterThan(0)
    expect(searchScore(GE, 'Entwickeler')).toBeGreaterThan(0)
  })

  it('finds München typed three ways', () => {
    for (const q of ['München', 'muenchen', 'munchen', 'Munchen']) {
      expect(searchScore(GE, q), q).toBeGreaterThan(0)
    }
  })

  it('ignores a separator the writer chose', () => {
    expect(searchScore(GE, 'Backendentwickler')).toBeGreaterThan(0)
  })

  it('requires every word to land somewhere', () => {
    expect(searchScore(GE, 'ge muenchen')).toBeGreaterThan(0)
    expect(searchScore(GE, 'ge hamburg')).toBe(0)
    expect(searchScore(SIXT, 'ge muenchen')).toBe(0)
  })

  it('does not fuzz a short token into everything', () => {
    // "ge" is one edit from "co", "ag", "de" … and must stay literal.
    expect(searchScore(SIXT, 'ge')).toBe(0)
  })

  it('ranks the exact hit above the near one', () => {
    const exact = searchScore(CC, 'Computacenter')
    const typo = searchScore(CC, 'Computacentre')
    expect(exact).toBeGreaterThan(typo)
    expect(typo).toBeGreaterThan(0)
  })

  it('ranks a title hit above the same word in a status', () => {
    const inTitle = searchScore(row('Open Source Engineer', 'Acme'), 'open')
    const inStatus = searchScore(row('COC Lead', 'Sixt', 'Pullach', 'open'), 'open')
    expect(inTitle).toBeGreaterThan(inStatus)
  })

  it('reads initials', () => {
    expect(searchScore(SIXT, 'cl')).toBeGreaterThan(0)
  })

  it('matches everything on an empty query, so the list keeps its order', () => {
    expect(searchScore(GE, '')).toBe(searchScore(SIXT, '   '))
  })

  it('returns nothing for a word that is in no field', () => {
    expect(searchScore(GE, 'Vertrieb')).toBe(0)
  })
})

describe('candidate rows', () => {
  // The shape KandidatenScreen builds: name · title · skills · company ·
  // location · contact.
  const person = (
    name: string,
    title: string,
    skills: string[],
    location = 'München',
  ) => [
    { text: name, weight: 3 },
    { text: title, weight: 3 },
    { text: skills.join(' '), weight: 2.5 },
    { text: 'Beispiel GmbH', weight: 2 },
    { text: location, weight: 2 },
    { text: 'kontakt@beispiel.invalid', weight: 1 },
  ]

  const architect = person('AnonymGE', 'Senior Software Architekt', [
    'Java',
    'Jakarta EE',
    'WildFly',
    'JPA',
  ])
  const generalist = person('Jana Beck', 'Projektleiterin', [
    'Java',
    'Scrum',
    'Jira',
    'Confluence',
    'SAP',
    'Excel',
  ])

  it('finds a skill that no title mentions', () => {
    expect(searchScore(architect, 'wildfly')).toBeGreaterThan(0)
    expect(searchScore(generalist, 'wildfly')).toBe(0)
  })

  it('ranks the role above a long skill list holding the same word', () => {
    // A profile listing thirty technologies must not outrank the person whose
    // JOB is the thing being searched for.
    expect(searchScore(person('A', 'Java Entwickler', ['Git']), 'java')).toBeGreaterThan(
      searchScore(generalist, 'java'),
    )
  })

  it('survives the typo a recruiter actually makes', () => {
    expect(searchScore(architect, 'architeckt')).toBeGreaterThan(0)
    expect(searchScore(architect, 'anonymge muenchen')).toBeGreaterThan(0)
  })

  it('still refuses a word the record does not carry', () => {
    expect(searchScore(architect, 'wildfly vertrieb')).toBe(0)
    expect(searchScore(architect, 'hamburg')).toBe(0)
  })
})
