// ELI-33: Unternehmen — every company of the workspace, cut by kind and search.
// Kunde = at least one manager; Lead = at least one new contact from Markt.
// A client with new contacts is both. (Not `is_client`: imports set it on all.)

import type { CompanyOverviewRowDTO } from '@/api/types'

export type CompanyKind = 'all' | 'clients' | 'leads'

const fold = (s: string) =>
  s.toLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')

const isKind = (r: Pick<CompanyOverviewRowDTO, 'managers' | 'leads'>, kind: CompanyKind) =>
  kind === 'all' || (kind === 'clients' ? r.managers > 0 : r.leads > 0)

export function filterCompanies<R extends Pick<CompanyOverviewRowDTO, 'name' | 'location' | 'managers' | 'leads'>>(
  rows: R[],
  kind: CompanyKind,
  q: string,
): R[] {
  const needle = fold(q.trim())
  return rows.filter(
    (r) => isKind(r, kind) && (!needle || fold(`${r.name} ${r.location ?? ''}`).includes(needle)),
  )
}

export const kindCounts = (rows: Pick<CompanyOverviewRowDTO, 'managers' | 'leads'>[]) => ({
  all: rows.length,
  clients: rows.filter((r) => isKind(r, 'clients')).length,
  leads: rows.filter((r) => isKind(r, 'leads')).length,
})
