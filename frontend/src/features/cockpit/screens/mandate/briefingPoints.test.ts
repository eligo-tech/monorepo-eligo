import { beforeEach, describe, expect, it } from 'vitest'

import { setLang } from '@/i18n'

import {
  BRIEFING_KEYS,
  briefingDraft,
  briefingPatch,
  missingLabel,
  pointLabel,
  pointTarget,
  scoreLine,
} from './briefingPoints'
import type { JobDTO } from '@/api/types'

// ELI-47: the backend decides which of the ten points are geklärt
// (`app/domain/jobs/briefing.py`). This module only names them and turns the
// form into a PATCH — so the keys here must be the backend's, in its order.

beforeEach(() => setLang('de'))

const job = (over: Partial<JobDTO> = {}): JobDTO => ({
  id: 'j1',
  tenant_id: 't',
  title: 'Java Dev',
  client_company_id: 'c1',
  manager_id: null,
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
  ...over,
})

describe('the ten briefing points', () => {
  it('are the backend keys, in the backend order', () => {
    expect(BRIEFING_KEYS).toEqual([
      'tasks',
      'must_have',
      'nice_to_have',
      'salary',
      'location',
      'start',
      'team_size',
      'contact',
      'interview_process',
      'vacancy_reason',
    ])
  })

  it('each has a label and a "fehlt" line', () => {
    for (const key of BRIEFING_KEYS) {
      expect(pointLabel(key)).not.toBe(key)
    }
    expect(missingLabel('salary')).toBe('Gehaltsrahmen fehlt')
    expect(missingLabel('vacancy_reason')).toBe('Grund der Vakanz fehlt')
  })

  it('an unknown key from a newer backend still reads as something', () => {
    expect(pointLabel('culture')).toBe('culture')
  })

  it('says the score as a sentence, in both languages', () => {
    expect(scoreLine({ done: 7, total: 10, missing: [] })).toBe('7 von 10 Punkten geklärt')
    setLang('en')
    expect(scoreLine({ done: 7, total: 10, missing: [] })).toBe('7 of 10 points clarified')
    expect(missingLabel('salary')).toBe('Salary range missing')
  })

  it('the contact is picked in the Stammdaten, everything else in the form', () => {
    expect(pointTarget('contact')).toEqual({ section: 'section-stammdaten' })
    expect(pointTarget('salary')).toEqual({ field: 'salary_min' })
    expect(pointTarget('start')).toEqual({ field: 'start_date' })
  })
})

describe('the briefing form', () => {
  it('seeds from the job', () => {
    const d = briefingDraft(job({ salary_max: 95000, nice_to_have_skills: ['Kafka'], tasks: 'Bauen' }))
    expect(d.salary_max).toBe('95000')
    expect(d.salary_min).toBe('')
    expect(d.nice_to_have_skills).toEqual(['Kafka'])
    expect(d.tasks).toBe('Bauen')
  })

  it('sends only what changed, blank as null, numbers as numbers', () => {
    const before = job({ tasks: 'Alt', location: 'Berlin' })
    const d = {
      ...briefingDraft(before),
      tasks: '  ',
      team_size: ' 6 Devs ',
      salary_max: '95000',
      nice_to_have_skills: ['Kafka', ' '],
    }
    expect(briefingPatch(briefingDraft(before), d)).toEqual({
      ok: true,
      patch: {
        tasks: null,
        team_size: '6 Devs',
        salary_max: 95000,
        nice_to_have_skills: ['Kafka'],
      },
    })
  })

  it('refuses an inverted or unreadable band before sending it', () => {
    const before = job()
    expect(briefingPatch(briefingDraft(before), { ...briefingDraft(before), salary_min: '100000', salary_max: '90000' }).ok).toBe(false)
    expect(briefingPatch(briefingDraft(before), { ...briefingDraft(before), salary_min: 'viel' }).ok).toBe(false)
  })

  it('never sends back a field the form did not touch, even if it changed meanwhile', () => {
    // Opened with no criteria; a chip in the Suchprofil then added "Java".
    const opened = job()
    const base = briefingDraft(opened)
    const d = { ...base, team_size: '6' }
    expect(briefingPatch(base, d)).toEqual({ ok: true, patch: { team_size: '6' } })
    expect(briefingPatch(base, base)).toEqual({ ok: true, patch: {} })
  })
})
