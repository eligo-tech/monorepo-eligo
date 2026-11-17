import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { ContactRowDTO, ManagerDTO } from '@/api/types'
import { t } from '@/i18n'

import { ContactRow } from './ContactListScreen'
import { ManagerProfile } from './ManagerProfile'

// ELI-38 "Status on top": a lead's open next call is its status. It sits on
// the name line — where the eye lands — not among the phone and e-mail links.
// No DOM test environment here, so the row is rendered to markup and split
// at the second line.

const row = (over: Partial<ContactRowDTO> = {}): ContactRowDTO =>
  ({
    manager_id: 'm1',
    company_id: 'c1',
    company_name: 'Telis Finanz AG',
    full_name: 'Ina Dorsch',
    role_title: 'Bereichsleitung Personalmanagement',
    phone: null,
    email: null,
    linkedin_url: null,
    xing_url: null,
    added_at: '2026-11-10T09:00:00Z',
    source: 'public_web',
    source_detail: 'https://example.invalid/ad',
    art14_outstanding: true,
    last_outcome: 'not_reached',
    last_call_at: '2026-11-12T09:00:00Z',
    last_call_by: 'Dima',
    next_action_at: '2026-11-11T09:00:00Z',
    due: true,
    ...over,
  }) as ContactRowDTO

/** The name line's markup — everything before the contact details line. */
const nameLine = (r: ContactRowDTO) =>
  renderToStaticMarkup(<ContactRow row={r} showCompany onCalled={() => {}} />).split('mt-1.5')[0]

describe('ContactRow (ELI-38)', () => {
  it('shows a due call-back on the name line', () => {
    expect(nameLine(row())).toContain(t('Fällig seit'))
  })

  it('shows an upcoming next call on the name line', () => {
    expect(nameLine(row({ due: false, next_action_at: '2026-11-20T09:00:00Z' }))).toContain(t('Nächster Anruf'))
  })

  it('shows no next-call status when none is open', () => {
    const line = nameLine(row({ due: false, next_action_at: null }))
    expect(line).not.toContain(t('Fällig seit'))
    expect(line).not.toContain(t('Nächster Anruf'))
  })
})

// ELI-49: the Art. 14 duty is shown and settled on the Manager page, not on
// the Leads list — the list is for calling. The status itself stays.
describe('ContactRow (ELI-49)', () => {
  it('shows no Art. 14 badge or mark-as-notified link on a lead that owes the notice', () => {
    const html = renderToStaticMarkup(<ContactRow row={row({ art14_outstanding: true })} showCompany onCalled={() => {}} />)
    expect(html).not.toContain(t('Art. 14 offen'))
    expect(html).not.toContain('Als informiert markieren')
    expect(html).not.toContain('Mark as notified')
  })

  it('still shows and settles the Art. 14 status on the Manager page', () => {
    const manager = {
      id: 'm1',
      company_id: 'c1',
      full_name: 'Ina Dorsch',
      role_title: null,
      email: null,
      phone: null,
      linkedin_url: null,
      source: 'public_web',
      source_detail: 'https://example.invalid/ad',
      art14_notified_at: null,
      art14_outstanding: true,
      notes: null,
      status: 'active',
      created_at: '2026-11-10T09:00:00Z',
    } as unknown as ManagerDTO
    const html = renderToStaticMarkup(
      <ManagerProfile manager={manager} companyName="Telis Finanz AG" onClose={() => {}} onNotified={() => {}} />,
    )
    expect(html).toContain(t('Art. 14 offen'))
    expect(html).toContain('Art. 14 erledigt')
  })
})
