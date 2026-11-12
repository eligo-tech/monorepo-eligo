import { describe, expect, it } from 'vitest'
import { filterCompanies, kindCounts } from './companyList'

// ELI-33: Unternehmen lists every company — clients and lead companies.
const row = (name: string, managers: number, leads: number, location: string | null = null) => ({
  id: name, name, location, managers, leads, mandates: 0, last_contact_at: null,
})
const rows = [
  row('Kurtz Holding GmbH', 2, 0, 'Kreuzwertheim'),
  row('Grimme Landmaschinen', 0, 3),
  row('Bergfreunde GmbH', 1, 1),
  row('Altkunde AG', 0, 0),
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

  it('counts each filter', () => {
    expect(kindCounts(rows)).toEqual({ all: 4, clients: 2, leads: 2 })
  })
})
