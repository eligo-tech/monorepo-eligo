// Sprachkenntnisse with a level (ELI-56).
//
// Stored as before — a list of strings — with the level written into the
// entry: "Englisch (Verhandlungssicher)". An entry without one ("Deutsch",
// from an import or an older CV) stays valid and shows without a level.
// Mirrors `app/domain/candidates/languages.py`; the backend normalises on save.
//
// The scale is LinkedIn's five steps, in German. The stored value is data and
// stays German in both UI languages; only its label is translated.

import { t } from '@/i18n'

export const LANGUAGE_LEVELS = [
  'Muttersprache',
  'Verhandlungssicher',
  'Fließend',
  'Erweiterte Grundkenntnisse',
  'Grundkenntnisse',
] as const

export type LanguageLevel = (typeof LANGUAGE_LEVELS)[number]

const SYNONYMS: Record<string, LanguageLevel> = Object.fromEntries([
  ...['muttersprache', 'muttersprachlich', 'zweisprachig', 'bilingual', 'native', 'native speaker', 'native or bilingual', 'native or bilingual proficiency'].map((w) => [w, 'Muttersprache']),
  ...['verhandlungssicher', 'business fluent', 'full professional', 'full professional proficiency'].map((w) => [w, 'Verhandlungssicher']),
  ...['fließend', 'fliessend', 'fluent', 'gute kenntnisse', 'sehr gute kenntnisse', 'fließend / gute kenntnisse', 'professional working', 'professional working proficiency'].map((w) => [w, 'Fließend']),
  ...['erweiterte grundkenntnisse', 'limited working', 'limited working proficiency'].map((w) => [w, 'Erweiterte Grundkenntnisse']),
  ...['grundkenntnisse', 'basiskenntnisse', 'elementary', 'elementary proficiency'].map((w) => [w, 'Grundkenntnisse']),
])

const PAREN = /^(.+?)\s*\(([^()]+)\)\s*$/
const DASH = /^(.+?)\s*(?:\s[-–—]\s|:)\s*(.+?)\s*$/

const norm = (s: string) => s.normalize('NFKC').toLowerCase().split(/\s+/).filter(Boolean).join(' ')

export interface LanguageEntry {
  name: string
  level: LanguageLevel | null
}

/** "Englisch (fließend)" → Englisch + Fließend. Anything not plainly a step
 *  ("Englisch (C1)") is kept whole, without a level — never guessed. */
export function splitLanguage(entry: string): LanguageEntry {
  const text = entry.trim()
  for (const re of [PAREN, DASH]) {
    const m = re.exec(text)
    if (m) {
      const level = SYNONYMS[norm(m[2])]
      if (level && m[1].trim()) return { name: m[1].trim(), level }
    }
  }
  return { name: text, level: null }
}

export function joinLanguage({ name, level }: LanguageEntry): string {
  const n = name.trim()
  return level ? `${n} (${level})` : n
}

/** The label a step shows under, LinkedIn's wording in German. Built inside
 *  a function: `t()` at import time would freeze the start-up language. */
export function languageLevelLabel(level: LanguageLevel): string {
  switch (level) {
    case 'Muttersprache':
      return t('Muttersprache / zweisprachig')
    case 'Verhandlungssicher':
      return t('Verhandlungssicher')
    case 'Fließend':
      return t('Fließend / gute Kenntnisse')
    case 'Erweiterte Grundkenntnisse':
      return t('Erweiterte Grundkenntnisse')
    case 'Grundkenntnisse':
      return t('Grundkenntnisse')
  }
}

/** Strongest first, then as entered — "Deutsch (Muttersprache)" before
 *  "Spanisch (Grundkenntnisse)"; entries without a level keep their place
 *  after the ranked ones. */
export function rankLanguages(entries: readonly string[]): LanguageEntry[] {
  const rank = (e: LanguageEntry) => (e.level ? LANGUAGE_LEVELS.indexOf(e.level) : LANGUAGE_LEVELS.length)
  return entries
    .map(splitLanguage)
    .map((e, i) => ({ e, i }))
    .sort((a, b) => rank(a.e) - rank(b.e) || a.i - b.i)
    .map(({ e }) => e)
}
