// How to reach a contact besides phone and e-mail (ELI-23): LinkedIn and XING.
// A stored profile wins; otherwise the same people search Markt offers — the
// recruiter opens it, checks the profile, and the match is a human judgement
// (neither network has an API that returns contact details, and scraping
// breaks both sites' terms).

/** "Nicole Lauchner STW" — the person and the company without its legal form. */
export function searchTerms(name: string, company: string): string {
  return encodeURIComponent(
    [name, company.replace(/\b(GmbH|AG|SE|KG|& Co\.?|KGaA|mbH|e\.V\.)\b/g, '')]
      .filter(Boolean)
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim(),
  )
}

export const linkedInSearchUrl = (name: string, company: string) =>
  `https://www.linkedin.com/search/results/people/?keywords=${searchTerms(name, company)}`
export const xingSearchUrl = (name: string, company: string) =>
  `https://www.xing.com/search/members?keywords=${searchTerms(name, company)}`

export interface NetworkLinkTarget {
  href: string
  /** True for a stored profile, false for a people search. */
  profile: boolean
}

export function networkLinks(c: {
  full_name: string
  company_name: string
  linkedin_url: string | null
  xing_url: string | null
}): { linkedin: NetworkLinkTarget; xing: NetworkLinkTarget } {
  return {
    linkedin: c.linkedin_url
      ? { href: c.linkedin_url, profile: true }
      : { href: linkedInSearchUrl(c.full_name, c.company_name), profile: false },
    xing: c.xing_url
      ? { href: c.xing_url, profile: true }
      : { href: xingSearchUrl(c.full_name, c.company_name), profile: false },
  }
}
