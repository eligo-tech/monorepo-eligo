import { describe, expect, it } from 'vitest'

import { toStoredLanguages } from './LanguageListEditor'

// ELI-56 review: editing one language must not rewrite the others.
describe('LanguageListEditor', () => {
  it('keeps an untouched row exactly as stored, writes an edited one canonically, drops an unnamed one', () => {
    expect(
      toStoredLanguages([
        { name: 'Englisch', level: 'Fließend', stored: 'Englisch – fließend' },
        { name: 'Deutsch', level: 'Muttersprache' },
        { name: ' ', level: 'Grundkenntnisse' },
      ]),
    ).toEqual(['Englisch – fließend', 'Deutsch (Muttersprache)', ''])
  })
})
