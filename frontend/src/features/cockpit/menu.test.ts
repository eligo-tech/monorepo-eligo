import { describe, expect, it } from 'vitest'
import { SCREENS, resolveScreen } from './CockpitShell'
import { groupByCompany } from './screens/ContactListScreen'

// ELI-29: the ground structure — Markt · Leads · Companies · Manager · Mandate
// · Kandidaten — and old links that still land.
describe('menu', () => {
  it('is Cockpit · Markt · Leads · Companies · Manager · Mandate · Kandidaten · Einstellungen', () => {
    expect(SCREENS.map((s) => s.key)).toEqual([
      'cockpit', 'markt', 'leads', 'companies', 'managers', 'mandate', 'kandidaten', 'einstellungen',
    ])
  })

  it('sends retired screens somewhere that exists', () => {
    expect(resolveScreen('kontakte')).toBe('leads')
    expect(resolveScreen('jobs')).toBe('mandate')
    expect(resolveScreen('projekte')).toBe('leads')
    expect(resolveScreen('workspace')).toBe('leads')
    expect(resolveScreen('anrufen')).toBe('leads')
    expect(resolveScreen('tracking')).toBe('cockpit')
    expect(resolveScreen('leads')).toBe('leads')
    expect(resolveScreen('companies')).toBe('companies')
  })
})

// Companies is the same lead records, grouped — one record, two views.
describe('groupByCompany', () => {
  const row = (manager_id: string, company_id: string, company_name: string) =>
    ({ manager_id, company_id, company_name }) as never

  it('groups by company id, companies sorted by name, people in list order', () => {
    const g = groupByCompany([
      row('m1', 'c2', 'Zeta GmbH'),
      row('m2', 'c1', 'alpha AG'),
      row('m3', 'c2', 'Zeta GmbH'),
      row('m4', 'c3', 'Zeta GmbH'), // same name, other company: its own group
    ])
    expect(g.map((x) => [x.id, x.people.map((p) => p.manager_id)])).toEqual([
      ['c1', ['m2']],
      ['c2', ['m1', 'm3']],
      ['c3', ['m4']],
    ])
  })
})
