// ELI-51 "LinkedIn-Suche": the mandate's own record, turned into a people
// search the recruiter runs in THEIR browser, with THEIR account, and a
// message they send themselves.
//
// Eligo never talks to LinkedIn or Xing. There is no request, no crawl and
// nothing stored — a link is built here and opened in a new tab, and what the
// recruiter finds there stays there until they decide to add someone by hand.
// That is what keeps this inside ARCHITECTURE.md rule 1 (no outbound fetch
// from a user action) and inside both networks' terms.
//
// Everything is deterministic: each suggested term carries the field it came
// from, so the chip can say "aus Titel" rather than asking to be trusted.

import { t } from '@/i18n'

/** LinkedIn caps the note on a connection request at 300 characters. */
export const CONNECTION_NOTE_LIMIT = 300

export type TermSource = 'title' | 'must' | 'cert' | 'location' | 'own'

export interface SearchTerm {
  /** Stable key for React and for toggling. */
  key: string
  text: string
  source: TermSource
  selected: boolean
}

export interface MandateFacts {
  title: string
  mustHave: string[]
  certifications?: string[]
  location?: string | null
}

/** "aus Titel" — where a chip came from, shown on the chip. */
export function sourceLabel(source: TermSource): string {
  switch (source) {
    case 'title':
      return t('aus Titel')
    case 'must':
      return t('aus Muss-Kriterien')
    case 'cert':
      return t('aus Zertifizierungen')
    case 'location':
      return t('aus Ort')
    case 'own':
      return t('eigener Begriff')
  }
}

const GENDER = '(?:[mwdfxi]|div(?:ers)?)'
const GENDER_PARENS = new RegExp(
  `\\s*\\(\\s*(?:all\\s+genders?|alle(?:\\s+geschlechter)?|gn|${GENDER}(?:\\s*[/,|]\\s*${GENDER})*)\\s*\\)`,
  'gi',
)
const GENDER_BARE = new RegExp(`\\s+${GENDER}(?:\\s*/\\s*${GENDER})+(?=\\s|$|[,.;])`, 'gi')

/** "Buchhalter*in (m/w/d)" → "Buchhalter". A gender tag is not a skill, and
 *  quoted into a LinkedIn search it matches nobody's headline. */
export function cleanTitle(title: string): string {
  return title
    .replace(GENDER_PARENS, '')
    .replace(GENDER_BARE, '')
    .replace(/([a-zäöüß])[*:_]in(?:nen)?\b/gi, '$1')
    .replace(/\s+/g, ' ')
    .replace(/[\s,;–-]+$/, '')
    .trim()
}

const NOT_A_PLACE = /\b(remote|home\s*-?office|bundesweit|deutschlandweit|europaweit|mobil)\b/i

/** "80331 München, Bayern" → "München". The town is what a profile names. */
export function placeName(location: string | null | undefined): string | null {
  if (!location) return null
  // Split first: "München / Remote" still names a town.
  for (const part of location.split(/[,;/]|\s[–-]\s/)) {
    if (NOT_A_PLACE.test(part)) continue
    const town = part
      .replace(/\b\d{4,5}\b/g, '')
      .replace(/\(.*?\)/g, '')
      .replace(/\s+/g, ' ')
      .trim()
    if (town) return town
  }
  return null
}

/** How many Muss-Kriterien start ticked: every term narrows a LinkedIn
 *  search (they are ANDed), and five of them usually leave nobody. */
const MUST_SELECTED = 2

export function suggestTerms(m: MandateFacts): SearchTerm[] {
  const out: SearchTerm[] = []
  const seen = new Set<string>()
  const add = (text: string, source: TermSource, selected: boolean) => {
    const clean = text.replace(/\s+/g, ' ').trim()
    const folded = clean.toLowerCase()
    if (!clean || seen.has(folded)) return
    seen.add(folded)
    out.push({ key: `${source}:${folded}`, text: clean, source, selected })
  }

  const titles = cleanTitle(m.title).split(/\s+[/|]\s+/)
  for (const title of titles) add(title, 'title', true)
  const titleText = titles.join(' ').toLowerCase()
  /** A skill the title already says adds nothing but an AND. Whole words
   *  only: "Java" is not in "JavaScript Developer", and "C" is in nothing. */
  const inTitle = (s: string) => {
    const word = s.trim().toLowerCase()
    if (!word) return false
    const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return new RegExp(`(^|[^\\p{L}\\p{N}])${escaped}($|[^\\p{L}\\p{N}])`, 'u').test(titleText)
  }

  let must = 0
  for (const skill of m.mustHave) {
    if (inTitle(skill) || !skill.trim()) continue
    add(skill, 'must', must < MUST_SELECTED)
    must += 1
  }
  for (const cert of m.certifications ?? []) {
    if (!inTitle(cert)) add(cert, 'cert', false)
  }
  const place = placeName(m.location)
  if (place) add(place, 'location', true)
  return out
}

/** Quoted when it has a space, a bracket, or IS a boolean word — otherwise
 *  "SAP(FI)" breaks the OR group and a skill called "OR" becomes one. */
const quote = (text: string) => {
  const bare = text.replace(/"/g, '')
  return /[\s()]/.test(bare) || /^(AND|OR|NOT)$/.test(bare) ? `"${bare}"` : bare
}

/** The keywords box of LinkedIn's people search. Title alternatives are
 *  ORed — "Elektroniker / Mechatroniker" is either, not both — and every
 *  other term narrows. Multi-word terms are quoted so "Spring Boot" is a
 *  phrase and not two words. */
export function searchKeywords(terms: SearchTerm[]): string {
  const on = terms.filter((term) => term.selected && term.text.trim())
  const titles = on.filter((term) => term.source === 'title').map((term) => quote(term.text))
  const rest = on.filter((term) => term.source !== 'title').map((term) => quote(term.text))
  const head =
    titles.length > 1 ? `(${titles.join(' OR ')})` : titles.length === 1 ? titles[0] : null
  return [head, ...rest].filter(Boolean).join(' ')
}

export const linkedInPeopleSearchUrl = (keywords: string) =>
  `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(keywords)}`

export const xingPeopleSearchUrl = (keywords: string) =>
  `https://www.xing.com/search/members?keywords=${encodeURIComponent(keywords)}`

export interface DraftOptions {
  form: 'Sie' | 'Du'
  /** `short` fits a connection note; `long` is an InMail or a message. */
  length: 'short' | 'long'
}

function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`
}

/** A first message about the mandate. A draft, never sent by Eligo: the
 *  recruiter fills in the name, edits it and sends it from their own
 *  account. Only the mandate's own fields go in — nothing about the
 *  person, because Eligo knows nothing about them.
 *
 *  Always German, in an English UI too: it goes to a candidate in a
 *  German-speaking market, and the Sie/Du switch only means anything in
 *  German. The panel around it is translated; the message is not — so
 *  these strings deliberately do not go through `t()`. */
export function draftMessage(m: MandateFacts, { form, length }: DraftOptions): string {
  const du = form === 'Du'
  const title = cleanTitle(m.title) || 'eine spannende Position'
  const place = placeName(m.location)
  const skills = m.mustHave.map((s) => s.trim()).filter(Boolean)
  const greet = du ? 'Hallo [Vorname],' : 'Guten Tag [Name],'
  const close = du
    ? 'Hast du Lust auf einen kurzen Austausch?'
    : 'Hätten Sie Interesse an einem kurzen Austausch?'
  const sign = 'Viele Grüße'

  const role = (roleTitle: string, at: string | null) =>
    'ich besetze gerade eine Stelle als ' + roleTitle + (at ? ' in ' + at : '') + '.'

  if (length === 'long') {
    const lines = [greet, '', role(title, place)]
    if (skills.length > 0) {
      lines.push('', 'Wichtig für die Rolle:', ...skills.map((s) => '– ' + s))
    }
    const certs = (m.certifications ?? []).map((c) => c.trim()).filter(Boolean)
    if (certs.length > 0) lines.push('Zertifizierung: ' + certs.join(', '))
    lines.push(
      '',
      du
        ? 'Wenn das für dich interessant klingt, erzähle ich dir gern mehr — telefonisch oder hier per Nachricht.'
        : 'Wenn das für Sie interessant klingt, erzähle ich Ihnen gern mehr — telefonisch oder hier per Nachricht.',
      close,
      '',
      sign,
    )
    return lines.join('\n')
  }

  // Short: drop detail until it fits the connection-note limit — skills
  // first, then the place, and only then shorten the title.
  const compose = (n: number, at: string | null, roleTitle: string) =>
    [
      greet,
      role(roleTitle, at),
      n > 0 ? 'Gefragt sind ' + skills.slice(0, n).join(', ') + '.' : null,
      close,
      sign,
    ]
      .filter(Boolean)
      .join(' ')

  for (let n = Math.min(MUST_SELECTED, skills.length); n >= 0; n -= 1) {
    const text = compose(n, place, title)
    if (text.length <= CONNECTION_NOTE_LIMIT) return text
  }
  // `room` can be ≤ 1 only if the fixed sentences alone outgrow the limit;
  // then the title goes and the whole note is clipped, never overrun.
  const room = CONNECTION_NOTE_LIMIT - compose(0, null, '').length
  const text = room > 1 ? compose(0, null, clip(title, room)) : compose(0, null, '')
  return clip(text, CONNECTION_NOTE_LIMIT)
}
