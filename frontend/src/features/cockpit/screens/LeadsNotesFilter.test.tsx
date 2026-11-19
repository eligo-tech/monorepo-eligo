import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { ContactRowDTO } from '@/api/types'
import { t } from '@/i18n'

import { ContactRow, NotesFilter } from './ContactListScreen'

// ELI-62: Leads sorted into "Noch keine Notiz" (nothing has happened yet)
// and "Mit Notizen" — chips with the counts the backend returns.

describe('NotesFilter (ELI-62)', () => {
  const counts = { all: 12, none: 7, with: 5 }

  it('offers Alle, Noch keine Notiz and Mit Notizen with their counts', () => {
    const html = renderToStaticMarkup(<NotesFilter value="" counts={counts} onChange={() => {}} />)
    expect(html).toContain(t('Alle'))
    expect(html).toContain(t('Noch keine Notiz'))
    expect(html).toContain(t('Mit Notizen'))
    for (const n of ['12', '7', '5']) expect(html).toContain(`>${n}<`)
  })

  it('marks the chosen chip as pressed', () => {
    const html = renderToStaticMarkup(<NotesFilter value="none" counts={counts} onChange={() => {}} />)
    const pressed = html.split('<button').filter((b) => b.includes('aria-pressed="true"'))
    expect(pressed).toHaveLength(1)
    expect(pressed[0]).toContain(t('Noch keine Notiz'))
  })

  it('renders without counts while the page loads', () => {
    const html = renderToStaticMarkup(<NotesFilter value="" counts={null} onChange={() => {}} />)
    expect(html).toContain(t('Mit Notizen'))
  })
})

describe('ContactRow last note (ELI-62)', () => {
  const row = {
    manager_id: 'm1', company_id: 'c1', company_name: 'X AG', full_name: 'Ina Dorsch', role_title: null,
    phone: null, email: null, linkedin_url: null, xing_url: null, added_at: '2026-11-10T09:00:00Z',
    source: 'public_web', source_detail: null, art14_outstanding: false, last_outcome: null,
    last_call_at: null, last_call_by: null, next_action_at: null, due: false,
  } as ContactRowDTO

  it('shows when the latest note was and how many there are', () => {
    const html = renderToStaticMarkup(
      <ContactRow row={{ ...row, note_count: 3, last_note_at: '2026-11-12T09:00:00Z', has_notes: true }} showCompany onCalled={() => {}} />,
    )
    expect(html).toContain(t('Letzte Notiz'))
    expect(html).toContain(t('{n} Notizen', { n: '3' }))
  })

  it('says "1 Notiz", not "1 Notizen"', () => {
    const html = renderToStaticMarkup(
      <ContactRow row={{ ...row, note_count: 1, last_note_at: '2026-11-12T09:00:00Z', has_notes: true }} showCompany onCalled={() => {}} />,
    )
    expect(html).toContain(t('1 Notiz'))
    expect(html).not.toContain(t('{n} Notizen', { n: '1' }))
  })

  it('marks a lead whose only note is the free-text field', () => {
    const html = renderToStaticMarkup(
      <ContactRow row={{ ...row, note_count: 0, last_note_at: null, has_notes: true }} showCompany onCalled={() => {}} />,
    )
    expect(html).toContain(t('Notiz vorhanden'))
  })

  it('says nothing about notes on a lead without any', () => {
    const html = renderToStaticMarkup(<ContactRow row={{ ...row, note_count: 0, last_note_at: null }} showCompany onCalled={() => {}} />)
    expect(html).not.toContain(t('Letzte Notiz'))
  })
})
