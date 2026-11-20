import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { CompanyPersonDTO } from '@/api/types'
import { t } from '@/i18n'

import { LeadRow } from './CompanyScreen'

// ELI-68: the company page showed "Noch kein Manager" above a lead of the
// same company, and the only way to make that lead a manager was to leave
// for the Leads list. Each lead row now carries "Zu Managern" itself.

const lead = (over: Partial<CompanyPersonDTO> = {}): CompanyPersonDTO => ({
  id: 'm1',
  full_name: 'Kathrin Telega',
  role_title: 'Junior People & Culture Business Partner',
  email: null,
  phone: null,
  stage: 'bus_dev',
  last_contact_at: null,
  no_interest_at: null,
  ...over,
})

const markup = (p: CompanyPersonDTO) => renderToStaticMarkup(<LeadRow person={p} onPromoted={() => {}} />)

describe('Company page — lead row (ELI-68)', () => {
  it('offers "Zu Managern" on a lead', () => {
    const html = markup(lead())
    expect(html).toContain('Kathrin Telega')
    expect(html).toContain(t('Zu Managern'))
  })

  it('a lead with "Kein Interesse" is not offered — the way back is on the person', () => {
    expect(markup(lead({ no_interest_at: '2026-11-18T09:00:00Z' }))).not.toContain(t('Zu Managern'))
  })
})
