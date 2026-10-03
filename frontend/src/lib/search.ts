// Hybrid search for the small lists the cockpit holds in memory (mandates,
// candidates — hundreds of rows, not millions).
//
// "Hybrid" means several signals, strongest first: an exact word beats a
// prefix, a prefix beats a substring, and only then does a typo-tolerant
// comparison get a say. That ordering is the point — a fuzzy-only search
// answers "GE" with everything containing a g and an e, which is worse than
// no search at all. Fields carry weights, so a hit in the title outranks the
// same hit in a status.
//
// Every token must hit somewhere (AND), so adding a word always narrows.

/** A searchable piece of a row, with how much a hit in it counts. */
export interface SearchField {
  text: string
  weight: number
}

const UMLAUT: Record<string, string> = { ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss' }

/** Lowercase, German-folded, punctuation-collapsed. "München" and "Muenchen"
 *  must be the same string before anything else is decided; "munchen" is then
 *  one edit away and left to the fuzzy pass. */
export function fold(value: string): string {
  return value
    .toLowerCase()
    .replace(/[äöüß]/g, (c) => UMLAUT[c])
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9#]+/g, ' ')
    .trim()
}

/** How many edits a token of this length may be off by. Three characters get
 *  none: at that length one edit reaches half the alphabet. */
function tolerance(length: number): number {
  if (length <= 3) return 0
  if (length <= 5) return 1
  return 2
}

/** Optimal string alignment distance — Levenshtein plus transposition, so
 *  "sofwtare" is one edit from "software", not two. Gives up at `cap`. */
export function editDistance(a: string, b: string, cap: number): number {
  if (a === b) return 0
  if (Math.abs(a.length - b.length) > cap) return cap + 1
  if (a.length === 0 || b.length === 0) return Math.max(a.length, b.length)

  let twoBack: number[] = []
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j)
  let row: number[] = []

  for (let i = 1; i <= a.length; i += 1) {
    row = new Array(b.length + 1)
    row[0] = i
    let best = row[0]
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      let v = Math.min(row[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
      if (
        i > 1 &&
        j > 1 &&
        a[i - 1] === b[j - 2] &&
        a[i - 2] === b[j - 1]
      ) {
        v = Math.min(v, twoBack[j - 2] + cost)
      }
      row[j] = v
      if (v < best) best = v
    }
    if (best > cap) return cap + 1
    twoBack = prev
    prev = row
  }
  return prev[b.length]
}

const EXACT = 1
const PREFIX = 0.9
const INFIX = 0.72
const GLUED = 0.66
const INITIALS = 0.5
const FUZZY_BEST = 0.58
const FUZZY_STEP = 0.12

/** Below this a candidate match is noise, not a near miss. */
const HIT = 0.45

/** The best score one token reaches in one field, 0 if it does not hit. */
function tokenInField(field: string, token: string): number {
  if (!field) return 0
  const words = field.split(' ').filter(Boolean)

  let best = 0
  for (const word of words) {
    if (word === token) return EXACT
    if (word.startsWith(token)) best = Math.max(best, PREFIX)
    else if (word.includes(token)) best = Math.max(best, INFIX)
  }
  if (best >= PREFIX) return best

  // "backendentwickler" for "Backend-Entwickler": the separator is noise.
  if (token.length > 4 && field.replace(/ /g, '').includes(token)) {
    best = Math.max(best, GLUED)
  }

  // "sbe" for "Senior Backend-Entwickler".
  if (token.length >= 2 && words.length >= token.length) {
    const initials = words.map((w) => w[0]).join('')
    if (initials.startsWith(token)) best = Math.max(best, INITIALS)
  }

  if (best > 0) return best

  // Last: a typo. Compared per word, and against the word's head as well, so
  // "entwickl" is still a near miss for "entwickler" rather than six edits.
  const cap = tolerance(token.length)
  if (cap === 0) return 0
  for (const word of words) {
    let d = editDistance(word, token, cap)
    if (d > cap && word.length > token.length) {
      d = editDistance(word.slice(0, token.length), token, cap)
    }
    if (d <= cap) {
      best = Math.max(best, FUZZY_BEST - FUZZY_STEP * (d - 1))
    }
  }
  return best
}

/**
 * Score a row against a query. 0 means "does not match" — the caller drops it;
 * anything above is a ranking, highest first. An empty query matches
 * everything with the same score, which keeps the caller's own order.
 */
export function searchScore(fields: SearchField[], query: string): number {
  const tokens = fold(query).split(' ').filter(Boolean)
  if (tokens.length === 0) return 1

  const folded = fields.map((f) => ({ text: fold(f.text), weight: f.weight }))

  let total = 0
  for (const token of tokens) {
    let best = 0
    for (const field of folded) {
      const hit = tokenInField(field.text, token)
      if (hit >= HIT) best = Math.max(best, hit * field.weight)
    }
    if (best === 0) return 0 // every word has to land somewhere
    total += best
  }
  return total / tokens.length
}
