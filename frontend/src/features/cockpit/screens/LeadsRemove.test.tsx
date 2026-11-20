import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { ContactRowDTO, ManagerDTO } from '@/api/types'
import { t } from '@/i18n'

import { NoInterestChip, removeReasonLabel } from '../leads/NoInterest'
import { ContactRow } from './ContactListScreen'
import { ManagerProfile } from './ManagerProfile'

// ELI-66: "Entfernen" hides a lead with a reason — never deletes it — and
// every field of a lead is editable on its page.

const row = (over: Partial<ContactRowDTO> = {}): ContactRowDTO =>
  ({
    manager_id: 'm1', company_id: 'c1', company_name: 'Telis Finanz AG', full_name: 'Ina Dorsch',
    role_title: null, phone: null, email: null, linkedin_url: null, xing_url: null,
    added_at: '2026-11-10T09:00:00Z', source: 'public_web', source_detail: null, art14_outstanding: false,
    last_outcome: null, last_call_at: null, last_call_by: null, next_action_at: null, due: false,
    ...over,
  }) as ContactRowDTO

const lead = (over: Partial<ManagerDTO> = {}): ManagerDTO =>
  ({
    id: 'm1', company_id: 'c1', full_name: 'Ina Dorsch', first_name: 'Ina', last_name: 'Dorsch',
    role_title: null, department: null, email: null, phone: null, linkedin_url: null, source: 'public_web',
    source_detail: null, art14_notified_at: null, art14_outstanding: false, notes: null, status: 'active',
    stage: 'bus_dev', created_at: '2026-11-10T09:00:00Z',
    ...over,
  }) as unknown as ManagerDTO

const markup = (r: ContactRowDTO) => renderToStaticMarkup(<ContactRow row={r} showCompany onCalled={() => {}} />)
const page = (m: ManagerDTO) =>
  renderToStaticMarkup(<ManagerProfile manager={m} companyName="Telis Finanz AG" onClose={() => {}} onNotified={() => {}} />)

describe('Leads entfernen (ELI-66)', () => {
  it('a lead on the list can be removed, and opened to edit', () => {
    const html = markup(row())
    expect(html).toContain(t('Entfernen'))
    expect(html).toContain('href="#managers/m1"')
  })

  it('a removed lead shows why and the way back, not "Entfernen"', () => {
    const html = markup(row({ no_interest_at: '2026-11-18T09:00:00Z', removed_reason: 'agency' }))
    expect(html).toContain(removeReasonLabel('agency'))
    expect(html).toContain(t('Wieder als Lead aufnehmen'))
    expect(html).not.toContain(`>${t('Entfernen')}<`)
  })

  it('the chip names the reason, or "Kein Interesse" for a call', () => {
    const since = '2026-11-18T09:00:00Z'
    expect(renderToStaticMarkup(<NoInterestChip since={since} reason="other" />)).toContain(removeReasonLabel('other'))
    expect(renderToStaticMarkup(<NoInterestChip since={since} />)).toContain(t('Kein Interesse (seit {date})', { date: '' }).split('(')[0].trim())
  })

  it('the lead page offers "Entfernen" for a lead, not for a vetted manager', () => {
    expect(page(lead())).toContain(t('Entfernen'))
    expect(page(lead({ stage: 'manager' }))).not.toContain(`>${t('Entfernen')}<`)
  })

  it('the reasons are Personalberatung, Nicht interessant, Sonstiges', () => {
    expect(['agency', 'not_relevant', 'other'].map((r) => removeReasonLabel(r as 'agency'))).toEqual(
      [t('Personalberatung'), t('Nicht interessant'), t('Sonstiges')],
    )
  })
})
