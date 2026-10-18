// Does the copy reach `t()` at all?
//
// `dictionary.test.ts` answers a different question: every `t('…')` has an
// English entry. It cannot see a string that was never wrapped, and that is
// exactly how the first bilingual pass shipped German to an English session.
// The codemod that did the wrapping matched JSX text with `[^<>{}\n]*?` —
// single line, no embedded expressions — so
//
//     <p>
//       Weitere Pipeline +<Money … /> möglich · gewichtet{' '}
//     </p>
//
// was invisible to it, as was every template literal. ~110 strings across 35
// files stayed German, the suite was green, and the switch looked finished.
//
// This test reads the sources and enumerates the positions that are
// user-facing BY CONSTRUCTION — JSX text, and the props and object keys whose
// value is rendered — then requires each one to be either a `t()` call or
// listed in ALLOWED below. It does not try to detect German: "Eigene
// Datenbank" has no umlaut and no function word, and a detector that misses
// it is worse than none, because it reads as a check.

import { describe, expect, it } from 'vitest'

/** Props and object keys whose value a person reads. */
const KEYS =
  'label|name|title|text|hint|note|placeholder|caption|tag|desc|description|' +
  'reason|summary|heading|subtitle|message|tooltip|alt|aria-label|legend|' +
  'unit|suffix|empty|cta|blurb|why|detail'

const ATTR = new RegExp(`\\b(${KEYS})\\s*=\\s*(["'])((?:[^\\\\\\n]|\\\\.)*?)\\2`, 'g')
const ATTR_EXPR = new RegExp(
  `\\b(${KEYS})\\s*=\\s*\\{\\s*(['"\`])((?:[^\\\\\\n]|\\\\.)*?)\\2\\s*\\}`,
  'g',
)
const PROP = new RegExp(`\\b(${KEYS})\\s*:\\s*(['"\`])((?:[^\\\\\\n]|\\\\.)*?)\\2`, 'g')
/** A JSX text run: after a closing `>` or a `}`, up to the next `<` or `{`.
 *  Newlines are allowed on purpose — copy broken across lines is the case
 *  the original codemod could not see. `=>` and `->` are excluded so an
 *  arrow body is not read as text. */
const JSX_TEXT = /(?<![=\-])>([^<>{}]+)[<{]/g
/** A template literal, captured whole so its static chunks can be split out
 *  of it. Nested backticks are not supported and do not occur here. */
const TEMPLATE = /`((?:[^`\\]|\\.)*)`/g

/** Strings that are deliberately not copy, or read the same in both
 *  languages. Listed rather than detected: adding one is a decision somebody
 *  made and a reviewer can see. */
const ALLOWED = new Set([
  // Brands, products and proper nouns.
  'LinkedIn',
  'LinkedIn / Xing',
  'Xing',
  'Facebook',
  'Stepstone',
  'Arbeitsagentur',
  'aiFind',
  'Parsed CV',
  'Dossier 360',
  'Trade Republic, Celonis',
  'Java, Jakarta EE, WildFly, JPA/Hibernate',
  'Head of IT',
  'Dillenburg',
  'IT-Administrator produktionsnahe IT / OT (m/w/d)',
  // Same word in both languages.
  'Manager',
  'Business Dev.',
  'Deals',
  'Offer',
  'Art. 14',
  'E-Mail',
  'Jet',
  'Mono',
  'Heli',
  'Download',
  'Export',
  'Filter',
  'Section',
  'Freelance',
  // `name` on an Error, not copy.
  'ApiError',
  // Demo job titles in the mock floor — the names of roles, which a
  // recruiter reads as data, not as interface copy.
  'VP Engineering',
  'Head of Data Engineering',
  'Team Lead Frontend',
  'Interim CFO',
  'Interim CTO',
  'Senior Architect',
  'DevOps Engineer',
  'Head of Sales',
])

const sources = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** Not translated on purpose — see frontend/CLAUDE.md. Parked surfaces are
 *  compiled but unrouted; the landing page carries its own `L(de, en)`
 *  pairs; `api/types.ts` is type literals, not copy. */
const EXCLUDED = [
  '/i18n/',
  '/landing/',
  '/features/matching/',
  '/features/pipeline/',
  '/features/reporting/',
  '/components/Sidebar.tsx',
  '/components/TopNav.tsx',
  '/api/types.ts',
  // Feeds the parked pipeline and reporting views only.
  '/data/pipeline.ts',
  '/data/reporting.ts',
]

/** Tailwind class strings, ids, routes, enum values and type syntax — the
 *  things that sit in the same syntactic position as copy without being it. */
const TAILWIND =
  /(^|\s)(bg|text|border|flex|grid|rounded|p|px|py|pt|pb|pl|pr|m|mt|mb|ml|mr|mx|my|gap|w|h|min|max|absolute|relative|fixed|sticky|font|tracking|leading|shadow|hover|focus|group|space|items|justify|inline|overflow|whitespace|truncate|cursor|opacity|transition|ring|outline|z|top|left|right|bottom|sm|md|lg|xl|2xl|aspect|col|row|order|self|place)-/
const CODE =
  /\b(const|let|var|function|export|import|interface|type|return|Record|Promise|Set|Map|Array|void|null|undefined|string|number|boolean|readonly|extends|implements|keyof|typeof|React|JSX|useState|useMemo|useEffect|if|else|for|while|switch|case|try|catch|throw|new|await|async)\b/

function isCopy(raw: string): boolean {
  const s = raw.split(/\s+/).join(' ').trim()
  if (s.length < 2 || !/[A-Za-zÄÖÜäöüß]{2}/.test(s)) return false
  if (TAILWIND.test(s) || CODE.test(s)) return false
  if (/^[/#.@?=]|:\/\//.test(s) || s.startsWith('http')) return false
  if (/^[a-z0-9_.-]+$/.test(s)) return false // ids, keys, enum values
  // Routes, storage keys and table names: one token, no spaces, with a
  // dot or a slash in it. `eligo.processCard.` and `cockpit/` are not copy.
  if (!/\s/.test(s) && /^[A-Za-z0-9_./-]+$/.test(s) && /[./]/.test(s)) return false
  if (/^[A-Z0-9_]+$/.test(s)) return false // CONSTANTS
  if (/^[A-Z][A-Za-z0-9]*$/.test(s)) return false // bare identifier
  if (/^[,;)\]]\s/.test(s) || /[=;{}`$]|&&|\|\|/.test(s)) return false
  // Parentheses are NOT a code smell on their own — "CSV (auch mit Umlauten)"
  // is copy, and rejecting it for the brackets is how that sentence shipped
  // in German. Unbalanced ones are a fragment, and `name(` is a call.
  const opens = (s.match(/\(/g) ?? []).length
  const closes = (s.match(/\)/g) ?? []).length
  if (opens !== closes || /\w\(/.test(s)) return false
  if (/^[[\]\s]*[a-zA-Z]+\s*:/.test(s)) return false // object / type fragment
  return true
}

interface Finding {
  path: string
  kind: string
  value: string
}

function scan(): Finding[] {
  const found: Finding[] = []
  for (const [path, src] of Object.entries(sources)) {
    if (path.includes('.test.') || path.startsWith('./')) continue
    if (EXCLUDED.some((frag) => path.includes(frag))) continue

    // Comments are prose about the code, not copy in it.
    const clean = src
      .replace(/\/\*[\s\S]*?\*\//g, (m) => '\n'.repeat((m.match(/\n/g) ?? []).length))
      .replace(/^[ \t]*\/\/.*$/gm, '')

    const seen = new Set<string>()
    const add = (kind: string, value: string) => {
      const s = value.split(/\s+/).join(' ').trim()
      if (!isCopy(s) || ALLOWED.has(s) || seen.has(kind + s)) return
      seen.add(kind + s)
      found.push({ path, kind, value: s })
    }

    for (const rx of [ATTR, ATTR_EXPR, PROP]) {
      rx.lastIndex = 0
      for (const m of clean.matchAll(rx)) {
        // `t('…')` reaches here as the call, not as a bare literal.
        if (/\bt\(\s*['"]?$/.test(clean.slice(Math.max(0, m.index - 12), m.index + m[0].indexOf(m[3])))) continue
        add(m[1], m[3])
      }
    }
    if (path.endsWith('.tsx')) {
      JSX_TEXT.lastIndex = 0
      for (const m of clean.matchAll(JSX_TEXT)) add('jsx', m[1])
    }

    // Template literals. A `${...}` cannot be part of a dictionary key, so
    // copy in one is copy that never reached `t()` — which is how
    // "· nach bester Passung" survived the pass above and was found by a
    // browser instead. Only the static chunks are read; separators like
    // " · " have no letters and fall out of `isCopy` on their own.
    TEMPLATE.lastIndex = 0
    for (const m of clean.matchAll(TEMPLATE)) {
      for (const chunk of m[1].split(/\$\{[^{}]*\}/)) add('template', chunk)
    }
  }
  return found
}

describe('translation coverage', () => {
  it('routes every user-facing string through t()', () => {
    const leftovers = scan().map((f) => `${f.path}  [${f.kind}]  ${f.value}`)
    expect(leftovers).toEqual([])
  })

  it('lists nothing in ALLOWED that no longer appears in the source', () => {
    const all = Object.entries(sources)
      .filter(([p]) => !p.includes('.test.'))
      .map(([, s]) => s)
      .join('\n')
    const stale = [...ALLOWED].filter((s) => !all.includes(s))
    expect(stale).toEqual([])
  })
})
