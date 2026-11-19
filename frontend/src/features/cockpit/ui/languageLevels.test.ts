import { describe, expect, it } from 'vitest'

import { LANGUAGE_LEVELS, joinLanguage, languageLevelLabel, rankLanguages, splitLanguage } from './languageLevels'

// ELI-56: languages carry LinkedIn's level, in German, inside the same list
// of strings — so entries without one stay valid.
describe('language levels', () => {
  it('reads a stated level and keeps an entry without one as it is', () => {
    expect(splitLanguage('Deutsch')).toEqual({ name: 'Deutsch', level: null })
    expect(splitLanguage('Deutsch (Muttersprache)')).toEqual({ name: 'Deutsch', level: 'Muttersprache' })
    expect(splitLanguage('Englisch (verhandlungssicher)')).toEqual({ name: 'Englisch', level: 'Verhandlungssicher' })
    expect(splitLanguage('Englisch – fluent')).toEqual({ name: 'Englisch', level: 'Fließend' })
    expect(splitLanguage('Spanisch: Grundkenntnisse')).toEqual({ name: 'Spanisch', level: 'Grundkenntnisse' })
  })

  it('never guesses a step from something that is not one', () => {
    expect(splitLanguage('Englisch (C1)')).toEqual({ name: 'Englisch (C1)', level: null })
  })

  it('writes the canonical form the backend stores, and round-trips', () => {
    expect(joinLanguage({ name: ' Englisch ', level: 'Fließend' })).toBe('Englisch (Fließend)')
    expect(joinLanguage({ name: 'Deutsch', level: null })).toBe('Deutsch')
    for (const level of LANGUAGE_LEVELS) {
      expect(splitLanguage(joinLanguage({ name: 'Polnisch', level }))).toEqual({ name: 'Polnisch', level })
    }
  })

  it('labels every step and ranks the strongest first', () => {
    for (const level of LANGUAGE_LEVELS) expect(languageLevelLabel(level)).toBeTruthy()
    expect(rankLanguages(['Spanisch (Grundkenntnisse)', 'Italienisch', 'Deutsch (Muttersprache)']).map((e) => e.name)).toEqual([
      'Deutsch',
      'Spanisch',
      'Italienisch',
    ])
  })
})
