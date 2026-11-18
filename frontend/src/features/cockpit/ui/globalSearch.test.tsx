import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { SearchResultsDTO } from '@/api/types'
import { t } from '@/i18n'
import { resolveDetail, resolveScreen } from '../CockpitShell'

import { flattenHits, moveSelection, searchTerm } from './globalSearch'
import { SearchResultsList } from './SearchResultsList'

// ELI-52 "Cockpit Suche — aktuell noch ohne Funktion". No DOM here: the
// adapter and the keyboard step are pure, the list is rendered to markup.

const results: SearchResultsDTO = {
  candidates: [{ id: 'c1', label: 'Anna Berger', subtitle: 'CTO · Acme' }],
  jobs: [{ id: 'j1', label: 'Bergführer (m/w/d)', subtitle: 'Bergfreunde GmbH' }],
  companies: [{ id: 'co1', label: 'Bergfreunde GmbH', subtitle: 'Tübingen' }],
  contacts: [
    { id: 'm1', label: 'Petra Vogel', subtitle: 'HR · Bergfreunde GmbH', kind: 'lead' },
    { id: 'm2', label: 'Klaus Mann', subtitle: null, kind: 'manager' },
  ],
}

describe('searchTerm', () => {
  it('asks the server only from two characters on', () => {
    expect(searchTerm('')).toBeNull()
    expect(searchTerm(' b ')).toBeNull()
    expect(searchTerm(' be ')).toBe('be')
  })
})

describe('flattenHits', () => {
  it('orders the groups Kandidaten → Mandate → Unternehmen → Leads & Manager', () => {
    expect(flattenHits(results).map((h) => h.id)).toEqual(['c1', 'j1', 'co1', 'm1', 'm2'])
  })

  it('opens each record where the cockpit already shows it', () => {
    const hashes = flattenHits(results).map((h) => h.hash)
    expect(hashes).toEqual([
      'kandidaten/c1',
      'cockpit/j1',
      'companies/co1',
      'managers/m1',
      'managers/m2',
    ])
    // …and each is a hash the shell resolves to that screen and record.
    expect(hashes.map((h) => [resolveScreen(h), resolveDetail(h)])).toEqual([
      ['kandidaten', 'c1'],
      ['cockpit', 'j1'],
      ['companies', 'co1'],
      ['managers', 'm1'],
      ['managers', 'm2'],
    ])
  })

  it('is empty for no answer', () => {
    expect(flattenHits(null)).toEqual([])
  })
})

describe('moveSelection', () => {
  it('steps with ↑/↓ and wraps around', () => {
    expect(moveSelection(-1, 'ArrowDown', 3)).toBe(0)
    expect(moveSelection(0, 'ArrowDown', 3)).toBe(1)
    expect(moveSelection(2, 'ArrowDown', 3)).toBe(0)
    expect(moveSelection(0, 'ArrowUp', 3)).toBe(2)
    expect(moveSelection(-1, 'ArrowUp', 3)).toBe(2)
  })

  it('stays put with nothing to choose', () => {
    expect(moveSelection(-1, 'ArrowDown', 0)).toBe(-1)
  })
})

describe('SearchResultsList', () => {
  const render = (over: Partial<Parameters<typeof SearchResultsList>[0]> = {}) =>
    renderToStaticMarkup(
      <SearchResultsList
        hits={flattenHits(results)}
        active={1}
        loading={false}
        failed={false}
        term="berg"
        onPick={() => undefined}
        onHover={() => undefined}
        {...over}
      />,
    )

  it('shows each group with its heading, a lead marked as one', () => {
    const html = render()
    for (const heading of [t('Kandidaten'), t('Mandate'), t('Unternehmen'), t('Leads & Manager')]) {
      expect(html).toContain(heading.replace('&', '&amp;'))
    }
    expect(html).toContain('Anna Berger')
    expect(html).toContain('HR · Bergfreunde GmbH')
    expect(html.split('Petra Vogel')[1]).toContain(t('Lead'))
  })

  it('marks the keyboard selection', () => {
    const html = render()
    const selected = html.split('aria-selected="true"')
    expect(selected).toHaveLength(2)
    expect(selected[1].split('</li>')[0]).toContain('Bergführer')
  })

  it('says so when nothing matched, and when the search failed', () => {
    expect(render({ hits: [] })).toContain(t('Keine Treffer für „{q}“', { q: 'berg' }))
    expect(render({ hits: [], failed: true })).toContain(t('Suche fehlgeschlagen'))
    expect(render({ hits: [], loading: true })).toContain(t('Suche …'))
  })
})
