import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'

import { EMPTY_LEAD_FORM, existingLead, leadPayload } from './manualLead'

// ELI-65 "+ Lead": Job, Name and Firma are required; the rest goes out only
// when typed. A 409 names the person already held — shown, not doubled.

describe('leadPayload', () => {
  it('needs the job, the name and the company', () => {
    expect(leadPayload(EMPTY_LEAD_FORM)).toBeNull()
    expect(leadPayload({ ...EMPTY_LEAD_FORM, jobTitle: 'Controller', fullName: 'Ben Ott' })).toBeNull()
    expect(leadPayload({ ...EMPTY_LEAD_FORM, jobTitle: ' ', fullName: 'Ben Ott', companyName: 'Ott KG' })).toBeNull()
  })

  it('trims and sends empty optional fields as null', () => {
    expect(
      leadPayload({
        ...EMPTY_LEAD_FORM,
        jobTitle: ' Controller ',
        fullName: ' Ben Ott ',
        companyName: ' Ott KG ',
        email: '  ',
        sourceUrl: ' https://www.linkedin.com/in/ben-ott ',
      }),
    ).toEqual({
      job_title: 'Controller',
      full_name: 'Ben Ott',
      company_name: 'Ott KG',
      role_title: null,
      email: null,
      phone: null,
      source_url: 'https://www.linkedin.com/in/ben-ott',
      // ELI-77: the profile box was left empty.
      profile_url: null,
    })
  })
})

describe('existingLead', () => {
  const conflict = (detail: unknown) => new ApiError(409, JSON.stringify({ detail }))

  it('reads the person already held', () => {
    expect(
      existingLead(conflict({ code: 'lead_exists', manager_id: 'm1', stage: 'manager', full_name: 'Anna Kraft' })),
    ).toEqual({ managerId: 'm1', stage: 'manager', fullName: 'Anna Kraft' })
  })

  it('is nothing for any other refusal', () => {
    expect(existingLead(conflict({ code: 'suppressed', requested_on: '2026-11-01' }))).toBeNull()
    expect(existingLead(new ApiError(409, 'plain text'))).toBeNull()
    expect(existingLead(new Error('x'))).toBeNull()
  })
})
