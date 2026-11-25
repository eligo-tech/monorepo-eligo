import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { ContactRowDTO } from '@/api/types'
import { t } from '@/i18n'

import { ContactRow } from '../screens/ContactListScreen'
import { NewLead } from './NewLead'

// ELI-65: a lead entered by hand is marked "manuell" on the Leads list and
// shows the job it is about; a Markt lead is not marked.

const row = {
  manager_id: 'm1', company_id: 'c1', company_name: 'Ott KG', full_name: 'Ben Ott', role_title: null,
  phone: null, email: null, linkedin_url: null, xing_url: null, added_at: '2026-11-20T09:00:00Z',
  source: 'third_party_source', source_detail: 'https://jobs.example/123', art14_outstanding: true,
  last_outcome: null, last_call_at: null, last_call_by: null, next_action_at: null, due: false,
  manual: true,
  jobs: [{ title: 'Controller (m/w/d)', location: null, url: 'https://jobs.example/123', posting_id: null, job_id: null }],
} as ContactRowDTO

describe('a lead entered by hand on the Leads list (ELI-65)', () => {
  it('is marked manuell and shows its job, linked to the ad — once', () => {
    const html = renderToStaticMarkup(<ContactRow row={row} showCompany onCalled={() => {}} />)
    expect(html).toContain(`>${t('manuell')}<`)
    expect(html).toContain('Controller (m/w/d)')
    expect(html.split('href="https://jobs.example/123"')).toHaveLength(2)
    expect(html).not.toContain(`>${t('Quelle')}<`)
    // A profile link the job does not use is the source.
    const fromProfile = renderToStaticMarkup(
      <ContactRow
        row={{ ...row, source_detail: 'https://www.linkedin.com/in/ben', jobs: [{ ...row.jobs![0], url: null }] }}
        showCompany
        onCalled={() => {}}
      />,
    )
    expect(fromProfile).toContain(t('Quelle'))
    expect(html).toContain(t('angelegt am {date}', { date: '20.11.2026' }).split(' ')[0])
  })

  it('a Markt lead carries no such mark', () => {
    const html = renderToStaticMarkup(
      <ContactRow row={{ ...row, manual: false, source: 'public_web' }} showCompany onCalled={() => {}} />,
    )
    expect(html).not.toContain(`>${t('manuell')}<`)
    expect(html).toContain(t('übernommen am {date}', { date: '' }).split(' ')[0])
  })
})

describe('the + Lead form (ELI-65)', () => {
  it('asks for job, link, name, title, company, e-mail and number', () => {
    const html = renderToStaticMarkup(<NewLead onCancel={() => {}} onSaved={() => {}} />)
    for (const label of [
      'LinkedIn-/XING-Profil', 'Job *', 'Link zur Stellenanzeige', 'Name Ansprechpartner *',
      'Jobtitel Ansprechpartner', 'Firma *', 'E-Mail', 'Nummer',
    ]) expect(html).toContain(t(label))
    // Nothing to save until Job, Name and Firma are filled.
    expect(html).toMatch(/<button[^>]*type="submit"[^>]*disabled/)
  })
})
