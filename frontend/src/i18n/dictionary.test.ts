import { afterEach, describe, expect, it, vi } from 'vitest'

import { EN } from './en'
import { serverCopyValues } from './serverCopy.support'
import { preferredLang, setLang, STORAGE_KEY, t } from './index'

/** Every `t('…')` in the app, read from SOURCE rather than at runtime.
 *
 *  Source, because the key and the call have to match character for
 *  character — `' · ohne Bewertung'` and `'· ohne Bewertung'` are different
 *  keys, and the second one silently renders German inside an English
 *  screen, which looks like a decision rather than a bug. Comparing the two
 *  sides at the same level of escaping is the only way to see that. */
const SAME_IN_BOTH = new Set([
  'aiFind (ATS)',
  'Arbeitsagentur',
  'Briefing',
  'Business Development',
  'CSV / Excel',
  'Cockpit',
  'Demo',
  'Feedback',
  'Institution',
  'Job',
  'Jobscoring',
  'Jobs',
  'Know-how',
  'Mail',
  'Minimum',
  'Name (A–Z)',
  'Workspace',
  'Skills',
  'optional',
  'max. 20 MB',
  'Name',
  'Manager',
  'Manager via LinkedIn',
  'LinkedIn',
  'Position',
  'Region',
  'Status',
  'Xing',
  'in {place}',
])

const CALL = /\bt\(\s*'((?:[^'\\]|\\.)*)'/g

/** What JavaScript makes of a literal the regex captured as source text.
 *
 *  This is the whole reason the test exists in this shape: `t('a\nb')` in a
 *  file is six characters, and the key it looks up at runtime is five. A
 *  comparison at the wrong level passes while the app falls back to German,
 *  which is invisible precisely because German is what it used to show. */
function unescape(literal: string): string {
  return literal.replace(/\\(u[0-9a-fA-F]{4}|.)/g, (_, esc: string) => {
    if (esc[0] === 'u') return String.fromCharCode(parseInt(esc.slice(1), 16))
    return { n: '\n', t: '\t', r: '\r', '\\': '\\', "'": "'", '"': '"' }[esc] ?? esc
  })
}

// Vite reads the sources, so this needs no node types and no path walking,
// and it cannot drift from what the bundler actually compiles.
const sources = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const callsites = new Map<string, string[]>()
for (const [path, src] of Object.entries(sources)) {
  // Siblings of this test glob as './index.ts', so the i18n module itself
  // is excluded by both spellings — its doc comments quote `t('Suchprofil')`
  // as an example, and an example is not a call site.
  if (path.includes('.test.') || path.includes('/i18n/') || path.startsWith('./'))
    continue
  for (const m of src.matchAll(CALL)) {
    const key = unescape(m[1])
    callsites.set(key, [...(callsites.get(key) ?? []), path])
  }
}

const dictionaryKeys = new Set(Object.keys(EN))

describe('the English dictionary', () => {
  it('covers every string the app asks it to translate', () => {
    const missing = [...callsites.keys()]
      .filter((k) => !dictionaryKeys.has(k))
      .map((k) => `${k}  ←  ${callsites.get(k)![0]}`)
    expect(missing).toEqual([])
  })

  it('has no entry nothing asks for', () => {
    // A string the BACKEND sends reaches `t()` as a variable — `t(f.label)`
    // — so it has no literal call site and would look unused. It is not:
    // `backend-copy.test.ts` requires an entry for every one of them.
    const dynamic = serverCopyValues()
    const orphans = [...dictionaryKeys].filter(
      (k) => !callsites.has(k) && !dynamic.has(k),
    )
    expect(orphans).toEqual([])
  })

  it('translates — no entry is still the German it came from', () => {
    const untouched = Object.entries(EN)
      .filter(([de, en]) => de === en)
      // Words that really are the same in both languages. Listed rather
      // than detected, so adding one is a decision somebody made.
      .filter(([de]) => !SAME_IN_BOTH.has(de))
      .map(([de]) => de)
    expect(untouched).toEqual([])
  })

  it('renders its escapes as characters, not as the escape text', () => {
    // A rewrite of this file once turned `\u00d8 9 d to offer` into
    // `\\u00d8 9 d to offer`, and "Ø 9 d to offer" shipped as the literal
    // six characters next to a fee. Nothing compares dictionary VALUES, so
    // only a browser saw it. A lone backslash in a value is almost always
    // this mistake.
    const suspect = Object.entries(EN)
      .filter(([, en]) => /\\/.test(en))
      .map(([de, en]) => `${de}  →  ${en}`)
    expect(suspect).toEqual([])
  })

  it('keeps every {placeholder} the German had', () => {
    const PLACEHOLDER = /\{(\w+)\}/g
    const broken: string[] = []
    for (const [de, en] of Object.entries(EN)) {
      const a = [...de.matchAll(PLACEHOLDER)].map((m) => m[1]).sort()
      const b = [...en.matchAll(PLACEHOLDER)].map((m) => m[1]).sort()
      if (a.join() !== b.join()) broken.push(de)
    }
    expect(broken).toEqual([])
  })
})

describe('t()', () => {
  it('falls back to the German rather than showing a key', () => {
    expect(t('eine Zeile die es nicht gibt')).toBe('eine Zeile die es nicht gibt')
  })

  it('substitutes placeholders', () => {
    expect(t('{n} von {m}', { n: 3, m: 8 })).toBe('3 von 8')
  })

  it('leaves a placeholder it was given no value for alone', () => {
    expect(t('{n} von {m}', { n: 3 })).toBe('3 von {m}')
  })

  it('opens in German for a German browser and English for anyone else', () => {
    stubStorage(null)
    for (const [language, expected] of [
      ['de', 'de'],
      ['de-AT', 'de'],
      ['DE-CH', 'de'],
      ['en-GB', 'en'],
      ['fr-FR', 'en'],
      ['', 'en'],
    ] as const) {
      vi.stubGlobal('navigator', { language })
      expect(preferredLang(), language).toBe(expected)
    }
  })

  it('prefers what this browser chose last over what it asks for', () => {
    vi.stubGlobal('navigator', { language: 'en-GB' })
    stubStorage('de')
    expect(preferredLang()).toBe('de')
  })

  it('ignores a stored value that is not a language we have', () => {
    vi.stubGlobal('navigator', { language: 'de-DE' })
    stubStorage('klingon')
    expect(preferredLang()).toBe('de')
  })

  it('initialises the stored key before the call that reads it', () => {
    // The regression, and why it is asserted against the source: the
    // module-level `current = preferredLang()` reads `STORAGE_KEY`, which
    // was declared below it. `const` is in its temporal dead zone until
    // its own line runs, so the read threw a ReferenceError, the catch
    // meant for blocked storage swallowed it, and the stored language was
    // ignored in every session — stored "en", rendered German, no error.
    //
    // `vi.resetModules()` cannot show this: the module is already
    // evaluated by the time a test runs, so `preferredLang()` called by
    // hand afterwards always works. The order is the fact.
    // Vite normalises a same-directory glob key to './index.ts', not
    // '../i18n/index.ts'.
    const source = sources['./index.ts']
    expect(source, 'i18n/index.ts not in the glob').toBeTypeOf('string')
    expect(source.indexOf('STORAGE_KEY =')).toBeGreaterThan(-1)
    expect(source.indexOf('STORAGE_KEY =')).toBeLessThan(
      source.indexOf('let current: Lang = preferredLang()'),
    )
  })

  it('works where there is no localStorage at all, which CI is', () => {
    // Not the same as storage throwing: the identifier does not exist, so
    // reading it is a ReferenceError. The first run of this guard re-threw
    // that and took the whole suite down on CI while passing locally.
    vi.stubGlobal('navigator', { language: 'de-DE' })
    vi.stubGlobal('localStorage', undefined)
    expect(preferredLang()).toBe('de')
    expect(() => setLang('en')).not.toThrow()
  })

  it('still renders when storage throws, which private mode does', () => {
    vi.stubGlobal('navigator', { language: 'de-DE' })
    vi.stubGlobal('localStorage', {
      getItem() {
        throw new Error('access denied')
      },
      setItem() {
        throw new Error('access denied')
      },
    })
    expect(preferredLang()).toBe('de')
    expect(() => setLang('en')).not.toThrow()
  })
})

/** The runner has no DOM, so storage is whatever we say it is. Stubbing it
 *  outright beats clearing a global that may not exist. */
function stubStorage(stored: string | null): void {
  let value = stored
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => (key === STORAGE_KEY ? value : null),
    setItem: (key: string, v: string) => {
      if (key === STORAGE_KEY) value = v
    },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  setLang('de')
})
