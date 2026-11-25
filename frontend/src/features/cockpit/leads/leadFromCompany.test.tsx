import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { CompanyPersonDTO } from '@/api/types'
import { t } from '@/i18n'

import { ManagerRow, companyDetail } from '../screens/CompanyScreen'
import { NoNamedContactNext } from '../screens/ContactsPanel'
import { companyLeadHref } from '../ui/companyList'
import { EMPTY_LEAD_FORM, leadPayload } from './manualLead'
import { NewLead } from './NewLead'

// ELI-78: a person found for a Markt company that named nobody ended up as a
// manager ("Manager hinzufügen") and never in Leads. The company page now
// offers "+ Lead" for THAT company, and "Zu Leads" for a manager added by
// hand nobody has spoken to yet.

const company = { id: 'c1', name: 'Nordlicht Software GmbH' }

describe('+ Lead from a company page (ELI-78)', () => {
  it('sends the company id, so the lead lands at this company', () => {
    expect(
      leadPayload({ ...EMPTY_LEAD_FORM, jobTitle: 'Controller', fullName: 'Ben Ott', companyName: '' }, company),
    ).toMatchObject({ company_id: 'c1', company_name: 'Nordlicht Software GmbH', full_name: 'Ben Ott' })
  })

  it('shows the company fixed, not as a field to type', () => {
    const html = renderToStaticMarkup(<NewLead company={company} onCancel={() => {}} onSaved={() => {}} />)
    expect(html).toContain('Nordlicht Software GmbH')
    expect(html).not.toContain(`>${t('Firma *')}<`)
  })

  it('"#companies/<id>/lead" opens that company with the form', () => {
    expect(companyDetail('c1/lead')).toEqual({ id: 'c1', newLead: true })
    expect(companyDetail('c1')).toEqual({ id: 'c1', newLead: false })
  })
})

describe('Markt: no Ansprechpartner named (ELI-78)', () => {
  it('a company already taken offers "Lead anlegen" on its page, with the form open', () => {
    expect(companyLeadHref('c1')).toBe('#companies/c1/lead')
    const html = renderToStaticMarkup(<NoNamedContactNext companyId="c1" />)
    expect(html).toContain('href="#companies/c1/lead"')
    expect(html).toContain(t('Lead anlegen'))
  })

  it('a company not taken yet says to take it first', () => {
    const html = renderToStaticMarkup(<NoNamedContactNext companyId={null} />)
    expect(html).not.toContain('href=')
    expect(html).toContain(t('Kennen Sie die Person? Erst „Übernehmen“, dann „Lead anlegen“.'))
  })
})

const manager = (over: Partial<CompanyPersonDTO> = {}): CompanyPersonDTO => ({
  id: 'm1',
  full_name: 'Jonas Weber',
  role_title: null,
  email: null,
  phone: null,
  stage: 'manager',
  last_contact_at: null,
  can_be_lead: true,
  ...over,
})

describe('"Zu Leads" on a manager row (ELI-78)', () => {
  it('is offered for a manager added by hand and not contacted yet', () => {
    expect(renderToStaticMarkup(<ManagerRow person={manager()} onMoved={() => {}} />)).toContain(t('Zu Leads'))
  })

  it('is not offered once the relationship has begun', () => {
    expect(
      renderToStaticMarkup(<ManagerRow person={manager({ can_be_lead: false })} onMoved={() => {}} />),
    ).not.toContain(t('Zu Leads'))
  })
})
