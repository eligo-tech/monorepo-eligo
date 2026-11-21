import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { CompanyOverviewRowDTO, ContactRowDTO, ManagerDTO } from '@/api/types'
import { t } from '@/i18n'
import { EN } from '@/i18n/en'

import { ContactRow } from '../screens/ContactListScreen'
import { ManagerRow } from '../screens/ManagerScreen'
import { CompanyListItem } from '../screens/CompanyScreen'
import { CreatedByChip, CreatedByFilter, CreatedByLine, creatorOptions } from './createdBy'

// ELI-69: every lead, manager and company shows who added it ("Angelegt von
// <Name>") — on the rows when known, on the detail page always ("unbekannt"
// when nobody is recorded) — and the lists filter by it (Alle / Ich / each
// person who added something here).

const lead = {
  manager_id: 'm1', company_id: 'c1', company_name: 'Ott KG', full_name: 'Ben Ott', role_title: null,
  phone: null, email: null, linkedin_url: null, xing_url: null, added_at: '2026-11-20T09:00:00Z',
  source: 'public_web', source_detail: null, art14_outstanding: false,
  last_outcome: null, last_call_at: null, last_call_by: null, next_action_at: null, due: false,
  created_by_user_id: 'user_jonas', created_by_name: 'Jonas',
} as ContactRowDTO

const manager = {
  id: 'm2', company_id: 'c1', full_name: 'Eva Kern', first_name: null, last_name: null, role_title: null,
  department: null, email: null, phone: null, linkedin_url: null, source: 'human_verified',
  source_detail: null, art14_notified_at: null, art14_outstanding: false, notes: null, status: 'active',
  created_at: '2026-11-01T00:00:00Z', created_by_user_id: 'user_xaver', created_by_name: 'Xaver',
} as unknown as ManagerDTO

const company = {
  id: 'c1', name: 'Ott KG', location: null, managers: 1, leads: 0, mandates: 0, last_contact_at: null,
  created_by_user_id: 'user_t', created_by_name: 'T',
} as CompanyOverviewRowDTO

const chip = (name: string) => t('Angelegt von {name}', { name })

describe('"Angelegt von" (ELI-69)', () => {
  it('is a chip with the name, and nothing without one', () => {
    expect(renderToStaticMarkup(<CreatedByChip name="Jonas" />)).toContain(chip('Jonas'))
    expect(renderToStaticMarkup(<CreatedByChip name={null} />)).toBe('')
  })

  it('says "unbekannt" on a detail page when nobody is recorded', () => {
    expect(renderToStaticMarkup(<CreatedByLine name="Xaver" />)).toContain(chip('Xaver'))
    expect(renderToStaticMarkup(<CreatedByLine name={null} />)).toContain(t('Angelegt von: unbekannt'))
  })

  it('shows on a Leads row, a Manager row and an Unternehmen row', () => {
    expect(renderToStaticMarkup(<ContactRow row={lead} showCompany onCalled={() => {}} />)).toContain(chip('Jonas'))
    expect(
      renderToStaticMarkup(<ManagerRow manager={manager} companyName="Ott KG" onOpen={() => {}} />),
    ).toContain(chip('Xaver'))
    expect(renderToStaticMarkup(<CompanyListItem company={company} onOpen={() => {}} />)).toContain(chip('T'))
  })

  it('shows nothing on a row with no creator', () => {
    const html = renderToStaticMarkup(
      <ContactRow row={{ ...lead, created_by_user_id: null, created_by_name: null }} showCompany onCalled={() => {}} />,
    )
    expect(html).not.toContain(t('Angelegt von: unbekannt'))
    expect(html).not.toContain(chip(''))
  })

  it('filters by Alle, Ich and each person who added something here', () => {
    const options = creatorOptions([
      { user_id: 'user_jonas', name: 'Jonas' },
      { user_id: 'user_xaver', name: 'Xaver' },
    ])
    expect(options).toEqual([
      { value: '', label: t('Alle') },
      { value: 'me', label: t('Ich') },
      { value: 'user_jonas', label: 'Jonas' },
      { value: 'user_xaver', label: 'Xaver' },
    ])
    const html = renderToStaticMarkup(
      <CreatedByFilter value="me" onChange={() => {}} creators={[{ user_id: 'user_jonas', name: 'Jonas' }]} />,
    )
    expect(html).toContain(`aria-label="${t('Angelegt von')}"`)
    expect(html).toContain('value="user_jonas"')
    expect(html).toMatch(/<option value="me" selected="">/)
  })

  it('has English copy', () => {
    expect(EN['Angelegt von {name}']).toBe('Added by {name}')
    expect(EN['Angelegt von: unbekannt']).toBe('Added by: unknown')
    expect(EN['Angelegt von']).toBe('Added by')
    expect(EN['Ich']).toBe('Me')
  })
})
