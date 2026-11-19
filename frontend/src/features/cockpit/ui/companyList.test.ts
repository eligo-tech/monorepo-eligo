import { describe, expect, it } from 'vitest'
import {
  alreadyAdoptedId,
  companyHref,
  existingCompanyId,
  filterCompanies,
  kindCounts,
  newCompanyPayload,
} from './companyList'

// ELI-33: Unternehmen lists every company — clients and lead companies.
const row = (name: string, managers: number, leads: number, location: string | null = null, to_review = 0) => ({
  id: name, name, location, managers, leads, mandates: 0, last_contact_at: null, to_review,
})
const rows = [
  row('Kurtz Holding GmbH', 2, 0, 'Kreuzwertheim'),
  row('Grimme Landmaschinen', 0, 3),
  row('Bergfreunde GmbH', 1, 1),
  row('Altkunde AG', 0, 0, null, 2),
]

describe('Unternehmen filter', () => {
  it('Kunden have a manager, Leads a new contact from Markt; a company can be both', () => {
    expect(filterCompanies(rows, 'clients', '').map((r) => r.name)).toEqual(['Kurtz Holding GmbH', 'Bergfreunde GmbH'])
    expect(filterCompanies(rows, 'leads', '').map((r) => r.name)).toEqual(['Grimme Landmaschinen', 'Bergfreunde GmbH'])
    expect(filterCompanies(rows, 'all', '')).toHaveLength(4)
  })

  it('searches name and place, ignoring case and umlauts', () => {
    expect(filterCompanies(rows, 'all', 'kreuzwert').map((r) => r.name)).toEqual(['Kurtz Holding GmbH'])
    expect(filterCompanies([row('Müller Bau', 1, 0)], 'all', 'mueller').map((r) => r.name)).toEqual(['Müller Bau'])
    expect(filterCompanies(rows, 'leads', 'kurtz')).toEqual([])
  })

  it('Zu prüfen: Markt sites of the same name wait for a yes or no (ELI-33 2b)', () => {
    expect(filterCompanies(rows, 'review', '').map((r) => r.name)).toEqual(['Altkunde AG'])
  })

  it('a company taken from Markt with no contact yet is a Lead (ELI-31)', () => {
    const taken = { ...row('Bayoonet AG', 0, 0), markt_lead: true }
    expect(filterCompanies([...rows, taken], 'leads', '').map((r) => r.name)).toEqual([
      'Grimme Landmaschinen', 'Bergfreunde GmbH', 'Bayoonet AG',
    ])
    expect(kindCounts([...rows, taken]).leads).toBe(3)
  })

  it('counts each filter', () => {
    expect(kindCounts(rows)).toEqual({ all: 4, clients: 2, leads: 2, review: 1 })
  })
})

// ELI-31: after "Übernehmen" the Markt card links to where the company landed.
describe('where an adopted company lives', () => {
  it('is its page under Unternehmen', () => {
    expect(companyHref('5f1c')).toBe('#companies/5f1c')
  })

  it('reads the existing company out of a 409 from the adopt route', () => {
    const id = '0b0c7d1e-2f3a-4b5c-8d9e-0f1a2b3c4d5e'
    expect(alreadyAdoptedId(`{"detail":"already adopted as company ${id}"}`)).toBe(id)
    expect(alreadyAdoptedId('{"detail":"no corpus company"}')).toBeNull()
  })
})

// ELI-43: "+ Unternehmen" — Lead or Kunde is a person's decision, and the
// filters go by it: a new Lead without a contact is under Leads, a new Kunde
// without a manager under Kunden, a company called Lead is no Kunde.
describe('a status set by a person', () => {
  it('decides the filters', () => {
    const lead = { ...row('Neulead GmbH', 0, 0), status: 'lead' as const }
    const kunde = { ...row('Neukunde AG', 0, 0), status: 'client' as const }
    const demoted = { ...row('Import KG', 3, 0), status: 'lead' as const }
    const all = [lead, kunde, demoted]
    expect(filterCompanies(all, 'leads', '').map((r) => r.name)).toEqual(['Neulead GmbH', 'Import KG'])
    expect(filterCompanies(all, 'clients', '').map((r) => r.name)).toEqual(['Neukunde AG'])
    expect(kindCounts(all)).toMatchObject({ clients: 1, leads: 2 })
  })
})

describe('the new-company form', () => {
  it('needs a name and sends trimmed fields, blank ones as null, Lead by default', () => {
    expect(newCompanyPayload({ name: '  ', location: 'Ulm', website: '', status: 'lead' })).toBeNull()
    expect(newCompanyPayload({ name: ' Neu GmbH ', location: ' ', website: ' neu.de ', status: 'lead' })).toEqual({
      name: 'Neu GmbH', location: null, website: 'neu.de', status: 'lead', is_client: false,
    })
    expect(newCompanyPayload({ name: 'Kunde AG', location: 'Ulm', website: '', status: 'client' })).toEqual({
      name: 'Kunde AG', location: 'Ulm', website: null, status: 'client', is_client: true,
    })
  })

  it('reads the existing company out of the 409 so it can be opened', () => {
    const id = '0b0c7d1e-2f3a-4b5c-8d9e-0f1a2b3c4d5e'
    expect(existingCompanyId(`{"detail":"company exists as ${id}"}`)).toBe(id)
    expect(existingCompanyId('{"detail":"nope"}')).toBeNull()
  })
})
