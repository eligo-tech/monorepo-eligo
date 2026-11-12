import { describe, expect, it } from 'vitest'
import { SCREENS, resolveDetail, resolveScreen } from './CockpitShell'

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

// ELI-33: a company page and a manager are links — the manager page's company
// name opens `#companies/<id>`, a manager on it opens `#managers/<id>`.
describe('links to a company or a manager', () => {
  it('land on the screen with the record in focus', () => {
    expect(resolveScreen('companies/abc-123')).toBe('companies')
    expect(resolveDetail('companies/abc-123')).toBe('abc-123')
    expect(resolveScreen('managers/m-9')).toBe('managers')
    expect(resolveDetail('managers/m-9')).toBe('m-9')
    expect(resolveDetail('companies')).toBeNull()
  })
})
