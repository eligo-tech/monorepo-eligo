import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { LeadPrefillDTO } from '@/api/types'
import { t } from '@/i18n'

import { applyPrefill } from './adPrefill'
import { EMPTY_LEAD_FORM, leadPayload } from './manualLead'
import { ManualLeadChip, NewLead } from './NewLead'

// ELI-73: "+ Lead" fills itself from a job ad — a link to an ad Markt holds,
// or the ad text pasted. Only a proposal: it fills EMPTY fields, never one the
// recruiter typed, and nothing is saved until "Lead anlegen".

const anna = {
  full_name: 'Anna Berg', role_title: 'Teamleitung HR', email: 'anna.berg@firma.de', phone: '0761 123456',
  found_by: 'rules' as const, quote: 'Ihre Ansprechpartnerin: Frau Anna Berg',
}
const fromMarkt: LeadPrefillDTO = {
  found: 'corpus', job_title: 'Senior Java Entwickler (m/w/d)', company_name: 'Nordlicht Software GmbH',
  posting_id: 'p1', source_url: 'https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1-S', is_agency: false,
  contacts: [anna],
}

describe('applyPrefill (ELI-73)', () => {
  it('fills job, company, the ad link and the one person the ad names', () => {
    expect(applyPrefill(EMPTY_LEAD_FORM, fromMarkt, 0)).toMatchObject({
      jobTitle: 'Senior Java Entwickler (m/w/d)',
      companyName: 'Nordlicht Software GmbH',
      sourceUrl: 'https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1-S',
      fullName: 'Anna Berg',
      roleTitle: 'Teamleitung HR',
      email: 'anna.berg@firma.de',
      phone: '0761 123456',
    })
  })

  it('never overwrites what the recruiter typed', () => {
    const typed = { ...EMPTY_LEAD_FORM, jobTitle: 'Java Lead', fullName: 'Dr. Anna Berg', phone: '+49 761 1' }
    const next = applyPrefill(typed, fromMarkt, 0)
    expect(next.jobTitle).toBe('Java Lead')
    expect(next.fullName).toBe('Dr. Anna Berg')
    expect(next.phone).toBe('+49 761 1')
    expect(next.email).toBe('anna.berg@firma.de')
  })

  it('takes the person picked when the ad names several, none when none is picked', () => {
    const two = { ...fromMarkt, contacts: [anna, { ...anna, full_name: 'Ben Ott', email: 'ben.ott@firma.de' }] }
    expect(applyPrefill(EMPTY_LEAD_FORM, two, 1).fullName).toBe('Ben Ott')
    expect(applyPrefill(EMPTY_LEAD_FORM, two, null).fullName).toBe('')
  })

  it('pasted text marks the lead as read from pasted text, a Markt ad does not', () => {
    const fromText: LeadPrefillDTO = { ...fromMarkt, found: 'text', source_url: null, company_name: null, posting_id: null }
    expect(applyPrefill(EMPTY_LEAD_FORM, fromText, 0).fromPastedText).toBe(true)
    expect(applyPrefill(EMPTY_LEAD_FORM, fromMarkt, 0).fromPastedText).toBe(false)
    const form = { ...applyPrefill(EMPTY_LEAD_FORM, fromText, 0), companyName: 'Nordlicht Software GmbH' }
    expect(leadPayload(form)).toMatchObject({ from_pasted_text: true })
  })
})

describe('a second fill, and picking a person (ELI-73)', () => {
  const ben = { ...anna, full_name: 'Ben Ott', role_title: null, email: null, phone: null }
  const other: LeadPrefillDTO = {
    ...fromMarkt, job_title: 'Teamlead Backend (m/w/d)', company_name: 'Ott KG', source_url: 'https://jobs.lever.co/ott/1',
    contacts: [ben],
  }

  it('a second ad replaces what the first one filled — and only that', () => {
    const first = applyPrefill(EMPTY_LEAD_FORM, fromMarkt, 0)
    const typed = { ...first, phone: '+49 761 999' }
    const second = applyPrefill(typed, other, 0, first)
    expect(second.jobTitle).toBe('Teamlead Backend (m/w/d)')
    expect(second.companyName).toBe('Ott KG')
    expect(second.fullName).toBe('Ben Ott')
    // The first ad's e-mail is cleared — it was that ad's, not this one's.
    expect(second.email).toBe('')
    // Typed after the first fill: kept.
    expect(second.phone).toBe('+49 761 999')
  })

  it('the link that was looked up is saved as the ad\'s own page', () => {
    const typed = { ...EMPTY_LEAD_FORM, sourceUrl: 'arbeitsagentur.de/jobsuche/jobdetail/10000-1-S?pk=x' }
    expect(applyPrefill(typed, fromMarkt, 0, { sourceUrl: typed.sourceUrl }).sourceUrl).toBe(fromMarkt.source_url)
  })

  it('picking another person never wipes what the recruiter typed', () => {
    const two = { ...fromMarkt, contacts: [anna, ben] }
    const first = applyPrefill(EMPTY_LEAD_FORM, two, 0)
    const typed = { ...first, roleTitle: 'Leitung Recruiting' }
    const picked = applyPrefill(typed, two, 1, first)
    expect(picked.fullName).toBe('Ben Ott')
    expect(picked.roleTitle).toBe('Leitung Recruiting')
    expect(picked.email).toBe('')
  })
})

describe('the + Lead form reads a job ad (ELI-73)', () => {
  it('a lead read from pasted ad text says so on its "manuell" mark', () => {
    const html = renderToStaticMarkup(<ManualLeadChip source="aus eingefügtem Anzeigentext" />)
    expect(html).toContain(t('Von Hand angelegt — aus eingefügtem Anzeigentext.'))
  })

  it('offers to fill the form from the ad link, and to paste the ad text', () => {
    const html = renderToStaticMarkup(<NewLead onCancel={() => {}} onSaved={() => {}} />)
    expect(html).toContain(t('Aus Anzeige übernehmen'))
    expect(html).toContain(t('Anzeigentext einfügen'))
  })
})
