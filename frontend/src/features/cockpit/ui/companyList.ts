// ELI-33: Unternehmen — every company of the workspace, cut by kind and search.
// Kunde = at least one manager; Lead = at least one new contact from Markt.
// A client with new contacts is both. (Not `is_client`: imports set it on all.)
// ELI-31: a company taken from Markt with "Übernehmen" and no contact yet
// (`markt_lead`) is a Lead too — the Markt card says "✓ Lead".

import type { CompanyOverviewRowDTO } from '@/api/types'

/** `review`: Markt sites of the same name wait for a person (ELI-33 2b). */
export type CompanyKind = 'all' | 'clients' | 'leads' | 'review'

const fold = (s: string) =>
  s.toLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')

type Counted = Pick<CompanyOverviewRowDTO, 'managers' | 'leads'> & { to_review?: number; markt_lead?: boolean }

const isKind = (r: Counted, kind: CompanyKind) =>
  kind === 'all' ||
  (kind === 'clients' ? r.managers > 0 : kind === 'leads' ? r.leads > 0 || !!r.markt_lead : (r.to_review ?? 0) > 0)

export function filterCompanies<R extends Pick<CompanyOverviewRowDTO, 'name' | 'location'> & Counted>(
  rows: R[],
  kind: CompanyKind,
  q: string,
): R[] {
  const needle = fold(q.trim())
  return rows.filter(
    (r) => isKind(r, kind) && (!needle || fold(`${r.name} ${r.location ?? ''}`).includes(needle)),
  )
}

/** A company's own page under Unternehmen (ELI-31: where "Übernehmen" lands). */
export const companyHref = (id: string) => `#companies/${id}`

/** The adopt route answers 409 "already adopted as company <id>" — the
 *  company is already here; this is its id, so the card can link to it. */
export function alreadyAdoptedId(detail: string): string | null {
  const m = /already adopted as company ([0-9a-f-]{36})/i.exec(detail)
  return m ? m[1] : null
}

export const kindCounts =(rows: Counted[]) => ({
  all: rows.length,
  clients: rows.filter((r) => isKind(r, 'clients')).length,
  leads: rows.filter((r) => isKind(r, 'leads')).length,
  review: rows.filter((r) => isKind(r, 'review')).length,
})
