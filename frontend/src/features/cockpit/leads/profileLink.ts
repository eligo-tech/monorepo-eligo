// ELI-77: a contact added from a pasted LinkedIn or XING profile link.
//
// Nothing is fetched — never a LinkedIn or XING request (ARCHITECTURE.md
// RULE 1). The name is read from the link's own slug, only where the slug
// says it plainly; what it cannot say is left for the person to type. The
// recruiter sees and edits the result before anything is saved.

export type ProfileNetwork = 'linkedin' | 'xing'

export interface ProfileLink {
  network: ProfileNetwork
  /** One spelling per profile: https, www host, no query, no trailing slash. */
  url: string
  /** "Anna Berg" — or null when the slug does not plainly give a name. */
  name: string | null
}

/** Degrees people put at the end of a LinkedIn slug — not a name. */
const DEGREES = new Set(['mba', 'msc', 'bsc', 'ma', 'ba', 'phd', 'llm', 'meng', 'beng', 'dipl'])
/** Lower-case inside a name ("Anna von Berg"); capitalised only first. */
const PARTICLES = new Set(['von', 'van', 'der', 'den', 'de', 'zu', 'vom', 'zum', 'zur', 'di', 'da', 'del', 'du', 'la', 'le'])
const TITLES: Record<string, string> = { dr: 'Dr.', prof: 'Prof.' }

function hostOf(raw: string): { host: string; path: string } | null {
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `https://${raw}`
  // Credentials (`user:pw@host`): what the text names as the host is not
  // where it points, and no profile link carries them. Same rule as the
  // server (`profiles._split`).
  const authority = withScheme.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '').split(/[/?#]/, 1)[0]
  if (authority.includes('@')) return null
  // "/in/../company/acme" is not a person; read before URL() resolves it.
  const rawPath = withScheme.replace(/^[a-z][a-z0-9+.-]*:\/\/[^/?#]*/i, '').split(/[?#]/, 1)[0]
  if (rawPath.split('/').some((p) => p === '.' || p === '..')) return null
  try {
    const u = new URL(withScheme)
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null
    return { host: u.hostname.toLowerCase(), path: u.pathname }
  } catch {
    return null
  }
}

const isNetworkHost = (host: string, domain: string) => host === domain || host.endsWith(`.${domain}`)

function decode(part: string): string {
  try {
    return decodeURIComponent(part)
  } catch {
    return part
  }
}

/** A slug token that is an id, not a name: any digit in it. */
const idLike = (token: string) => /\d/.test(token)

function capitalise(token: string): string {
  return token
    .split(/(['’])/)
    .map((p) => (p.length ? p[0].toLocaleUpperCase('de-DE') + p.slice(1).toLocaleLowerCase('de-DE') : p))
    .join('')
}

/** "anna-von-berg-1a2b3c" → "Anna von Berg"; null below two name words. */
export function nameFromSlug(slug: string, separators: RegExp): string | null {
  const tokens = decode(slug)
    .split(separators)
    .map((t) => t.trim())
    .filter(Boolean)
  // Trailing ids and degrees ("-1a2b3c", "-87654321", "-mba") are not the name.
  while (tokens.length && (idLike(tokens[tokens.length - 1]) || DEGREES.has(tokens[tokens.length - 1].toLowerCase())))
    tokens.pop()
  // A digit left inside the name, or anything but letters: not plainly a name.
  if (tokens.some((t) => !/^[\p{L}'’.]+$/u.test(t))) return null
  const words = tokens.filter((t) => !TITLES[t.toLowerCase().replace(/\.$/, '')])
  // One word ("annaberg") is first and last name run together, or only one
  // of them — which, the link cannot say. Not guessed.
  if (words.length < 2) return null
  return tokens
    .map((t, i) => {
      const lower = t.toLowerCase().replace(/\.$/, '')
      if (TITLES[lower]) return TITLES[lower]
      if (i > 0 && PARTICLES.has(lower)) return lower
      return capitalise(t)
    })
    .join(' ')
}

/** The profile a pasted link points at, or null if it is not a person's
 *  LinkedIn (`/in/<slug>`, legacy `/pub/<slug>/…`) or XING
 *  (`/profile/<Slug>`) profile. */
export function parseProfileLink(raw: string): ProfileLink | null {
  const text = raw.trim()
  if (!text) return null
  const at = hostOf(text)
  if (!at) return null
  const parts = at.path.split('/').filter(Boolean)
  const kind = (parts[0] ?? '').toLowerCase()
  const slug = parts[1]
  if (isNetworkHost(at.host, 'linkedin.com')) {
    if (!slug || (kind !== 'in' && kind !== 'pub')) return null
    const clean = encodeURIComponent(decode(slug))
    const url =
      kind === 'pub'
        ? `https://www.linkedin.com/pub/${[clean, ...parts.slice(2).map((p) => encodeURIComponent(decode(p)))].join('/')}`
        : `https://www.linkedin.com/in/${clean}`
    return { network: 'linkedin', url, name: nameFromSlug(slug, /-/) }
  }
  if (isNetworkHost(at.host, 'xing.com')) {
    if (kind !== 'profile' || !slug) return null
    // XING appends a number to a taken name: "Anna_Berg2".
    const name = nameFromSlug(decode(slug).replace(/\d+$/, ''), /_/)
    return { network: 'xing', url: `https://www.xing.com/profile/${encodeURIComponent(decode(slug))}`, name }
  }
  return null
}
