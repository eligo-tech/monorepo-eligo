import { describe, expect, it } from 'vitest'
import { SCREENS, resolveScreen } from './CockpitShell'

// ELI-23: the menu the recruiters asked for, and old links that still land.
describe('menu', () => {
  it('is Cockpit · Markt · Kontaktliste · Manager · Jobs · Kandidaten · Einstellungen', () => {
    expect(SCREENS.map((s) => s.key)).toEqual([
      'cockpit', 'markt', 'kontakte', 'managers', 'jobs', 'kandidaten', 'einstellungen',
    ])
  })

  it('sends retired screens somewhere that exists', () => {
    expect(resolveScreen('projekte')).toBe('kontakte')
    expect(resolveScreen('workspace')).toBe('kontakte')
    expect(resolveScreen('anrufen')).toBe('kontakte')
    expect(resolveScreen('tracking')).toBe('cockpit')
    expect(resolveScreen('kontakte')).toBe('kontakte')
  })
})
