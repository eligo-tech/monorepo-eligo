import { beforeEach, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { JobDTO } from '@/api/types'
import { setLang } from '@/i18n'

import { BriefingCheck } from './BriefingCheck'

// ELI-47: the mandate's Briefing area says how much is geklärt and lists
// what to ask next — exactly what the backend's score says, nothing more.

beforeEach(() => setLang('de'))

const job = (briefing: JobDTO['briefing']): JobDTO => ({
  id: 'j1',
  tenant_id: 't',
  title: 'Java Dev',
  client_company_id: 'c1',
  location: null,
  location_radius_km: null,
  must_have_skills: [],
  required_certifications: [],
  requires_work_permit: true,
  salary_min: null,
  salary_max: null,
  salary_currency: 'EUR',
  status: 'active',
  created_at: '',
  updated_at: '',
  briefing,
})

const render = (j: JobDTO) => renderToStaticMarkup(<BriefingCheck job={j} onSaved={() => {}} />)

describe('BriefingCheck', () => {
  it('shows the score and each missing point as something to ask', () => {
    const html = render(job({ done: 7, total: 10, missing: ['salary', 'start', 'vacancy_reason'] }))
    expect(html).toContain('7 von 10 Punkten geklärt')
    expect(html).toContain('Gehaltsrahmen fehlt')
    expect(html).toContain('Startdatum fehlt')
    expect(html).toContain('Grund der Vakanz fehlt')
    expect(html).not.toContain('Teamgröße fehlt')
  })

  it('says so when nothing is missing', () => {
    const html = render(job({ done: 10, total: 10, missing: [] }))
    expect(html).toContain('10 von 10 Punkten geklärt')
    expect(html).toContain('Alle Punkte geklärt.')
  })

  it('draws nothing for a backend that sends no score yet', () => {
    expect(render(job(undefined))).toBe('')
  })
})
