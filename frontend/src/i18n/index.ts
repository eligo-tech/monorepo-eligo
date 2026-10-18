// Two languages, one source of truth.
//
// The dictionary is keyed by the GERMAN string, not by an invented
// identifier. `t('Suchprofil')` rather than `t('mandate.searchProfile')`,
// for three reasons that matter more here than the convention does:
//
//  * the call site still reads as the sentence it renders, so a German
//    speaker reviewing a diff sees the copy and not a key;
//  * a missing translation degrades to German — the language this product
//    was written in and the one its first customers read — instead of
//    showing a raw key to somebody mid-mandate;
//  * 484 strings across 60 files is a codemod, and inventing 484 names is
//    not. The names would be worse than the sentences anyway.
//
// The cost is that two German strings that happen to be identical cannot
// take different English words. That has bitten exactly once: "Firmen" is a
// count noun on Projekte ("3 companies") and an entity name in the import
// picker ("Companies"), and German capitalises both the same way, so only
// the English looked wrong. `FileImportPanel.entityLabel` fixes the case at
// the one site that needs a name rather than inventing a second key. If a
// pair ever needs genuinely different WORDS, give the contexts different
// German keys — that is the escape hatch, and it is cheaper than it looks.

import { EN } from './en'

export type Lang = 'de' | 'en'

export const LANGS: readonly Lang[] = ['de', 'en'] as const

// Everything from here to `current` is declared BEFORE it on purpose:
// `current` is initialised by calling `preferredLang()`, which reads all of
// it. They used to sit below, and a `const` is in its temporal dead zone
// until its own line runs — so the call threw a ReferenceError, the catch
// that exists for blocked storage swallowed it, and every session fell back
// to the browser's language. Stored "en", rendered German, nothing logged.
// Twice, for two different names. `dictionary.test.ts` asserts the order.

export const STORAGE_KEY = 'eligo.lang'

const isLang = (v: string | null | undefined): v is Lang =>
  v === 'de' || v === 'en'

/** The language to open in: what this browser chose last, else what it asks
 *  for. A German browser gets German; everyone else gets English, because
 *  the alternative is a stranger's first impression being a language they
 *  did not ask for. */
export function preferredLang(): Lang {
  // `typeof` rather than a bare reference: there is no `localStorage` at all
  // under the test runner, and reading an identifier that does not exist is
  // a ReferenceError, not a storage error. That distinction is the point of
  // the catch below.
  if (typeof localStorage !== 'undefined') {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (isLang(stored)) return stored
    } catch (err) {
      // Private mode and blocked site data throw here, and falling through
      // to the browser's own preference is right for those.
      //
      // A ReferenceError past the guard above is NOT one of those: it means
      // this ran before something it needs was initialised, which is the bug
      // this catch once hid — `STORAGE_KEY` and `isLang` were declared below
      // the module-level call that reads them, so the stored language was
      // ignored in every session and nothing anywhere said so. Let it through.
      if (err instanceof ReferenceError) throw err
    }
  }
  const asked = typeof navigator === 'undefined' ? '' : navigator.language
  return asked.toLowerCase().startsWith('de') ? 'de' : 'en'
}

/** Read by every `t()` call. Module-level rather than a React context
 *  because a large share of the copy lives in plain functions and
 *  module-level constants — `standing()`, the adapters, the demo floor in
 *  `mock.ts` — none of which can call a hook, and the last of which is
 *  evaluated once at import whatever the renderer does. */
//  Resolved HERE, at module load, not from a hook in a component. Modules
//  that call `t()` while they are being imported — the demo floor in
//  `mock.ts` does it 33 times — would otherwise bake in the default before
//  any component had rendered. Everything that calls `t` imports this file,
//  so this runs first by construction.
let current: Lang = preferredLang()

export const getLang = (): Lang => current

/** Switch language by RELOADING, not by re-rendering.
 *
 *  A remount would miss the two places that matter most: module-level
 *  constants, which are evaluated once at import and hold 25 strings of the
 *  demo floor alone, and the fourteen files that memoise. Both would keep
 *  the old language until something unrelated invalidated them, which is
 *  the kind of bug that shows up in a sales demo and nowhere else.
 *
 *  A reload is correct by construction, and the cost is right: the hash
 *  route survives it, the bundle is warm, and nobody switches language
 *  twice in a session. */
export function setLang(lang: Lang): void {
  if (typeof localStorage !== 'undefined') {
    try {
      localStorage.setItem(STORAGE_KEY, lang)
    } catch {
      // Blocked storage: the switch still applies for this page, it just
      // will not be remembered. Better than refusing to change language.
    }
  }
  current = lang
  // Guarded because this module is also loaded without a DOM — by the test
  // runner, and by anything that renders on a server later. There, setting
  // the language is all that is wanted.
  if (typeof window !== 'undefined') window.location.reload()
}

/** Tell the document which language it is in — for screen readers, for
 *  hyphenation, and for `:lang()` rules. The value is already decided. */
export function initLang(): Lang {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = current
  }
  return current
}


/** Placeholders are `{name}` and are substituted after the lookup, so a
 *  translation may move them: "{n} candidates" ↔ "{n} Kandidaten". */
function interpolate(text: string, vars?: Record<string, string | number>): string {
  if (!vars) return text
  return text.replace(/\{(\w+)\}/g, (whole, key: string) =>
    key in vars ? String(vars[key]) : whole,
  )
}

/** Translate one string. The argument IS the German copy. */
export function t(source: string, vars?: Record<string, string | number>): string {
  if (current === 'de') return interpolate(source, vars)
  return interpolate(EN[source] ?? source, vars)
}

/** The language names, in their own language — the only honest way to label
 *  a switch somebody cannot currently read. */
export const LANG_LABEL: Record<Lang, string> = {
  de: 'Deutsch',
  en: 'English',
}
