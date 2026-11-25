// ELI-33: Unternehmen — every company of the workspace, cut by kind and search.
// Kunde = at least one manager; Lead = at least one new contact from Markt.
// A client with new contacts is both. (Not `is_client`: imports set it on all.)
// ELI-31: a company taken from Markt with "Übernehmen" and no contact yet
// (`markt_lead`) is a Lead too — the Markt card says "✓ Lead".

// ELI-43: a person can set Lead / Kunde ("+ Unternehmen", the company page);
// that decision then decides both filters.

import type { CompanyOverviewRowDTO, CompanyStatus, NewCompanyPayload } from '@/api/types'

/** `review`: Markt sites of the same name wait for a person (ELI-33 2b). */
export type CompanyKind = 'all' | 'clients' | 'leads' | 'review'

const fold = (s: string) =>
  s.toLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')

type Counted = Pick<CompanyOverviewRowDTO, 'managers' | 'leads'> & {
  to_review?: number
  markt_lead?: boolean
  status?: CompanyStatus | null
}

// ELI-43: where a person set Lead / Kunde (`status`), that decision wins —
// the same rule as the backend's `overview()`.
const isClient = (r: Counted) => (r.status ? r.status === 'client' : r.managers > 0)
const isLead = (r: Counted) => r.leads > 0 || (r.status ? r.status === 'lead' : !!r.markt_lead)

const isKind = (r: Counted, kind: CompanyKind) =>
  kind === 'all' ||
  (kind === 'clients' ? isClient(r) : kind === 'leads' ? isLead(r) : (r.to_review ?? 0) > 0)

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

/** ELI-78: that page with the "+ Lead" form open — for a person the ads do
 *  not name but the recruiter knows. */
export const companyLeadHref = (id: string) => `#companies/${id}/lead`

/** The adopt route answers 409 "already adopted as company <id>" — the
 *  company is already here; this is its id, so the card can link to it. */
export function alreadyAdoptedId(detail: string): string | null {
  const m = /already adopted as company ([0-9a-f-]{36})/i.exec(detail)
  return m ? m[1] : null
}

export interface NewCompanyForm {
  name: string
  location: string
  website: string
  status: CompanyStatus
}

export const EMPTY_COMPANY_FORM: NewCompanyForm = { name: '', location: '', website: '', status: 'lead' }

/** ELI-43 "+ Unternehmen": what is sent, or null while the name is missing. */
export function newCompanyPayload(form: NewCompanyForm): NewCompanyPayload | null {
  const name = form.name.trim()
  if (!name) return null
  return {
    name,
    location: form.location.trim() || null,
    website: form.website.trim() || null,
    status: form.status,
    is_client: form.status === 'client',
  }
}

/** The create route answers 409 "company exists as <id>" — it is already
 *  here; this is its id, so the form can offer to open it. */
export function existingCompanyId(detail: string): string | null {
  const m = /company exists as ([0-9a-f-]{36})/i.exec(detail)
  return m ? m[1] : null
}

export const kindCounts =(rows: Counted[]) => ({
  all: rows.length,
  clients: rows.filter((r) => isKind(r, 'clients')).length,
  leads: rows.filter((r) => isKind(r, 'leads')).length,
  review: rows.filter((r) => isKind(r, 'review')).length,
})
