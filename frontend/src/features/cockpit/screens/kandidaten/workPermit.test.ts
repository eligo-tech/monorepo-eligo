// ELI-28: "Arbeitserlaubnis Vorauswahl: Staatsbürger (wir arbeiten nur mit
// Staatsbürgern oder Arbeitserlaubnis)".
//
// The preselection is for a NEW candidate only. An existing record keeps what
// it stores — `unknown` included — because work permit is a hard filter in
// matching, and a form that quietly turned `unknown` into `citizen` on any
// unrelated edit would let people through that filter nobody vouched for.

import { describe, expect, it } from 'vitest'

import { NEW_CANDIDATE_WORK_PERMIT, WORK_PERMITS, workPermitForEdit } from './workPermit'

describe('work permit', () => {
  it('preselects Staatsbürger for a new candidate', () => {
    expect(NEW_CANDIDATE_WORK_PERMIT).toBe('citizen')
    expect(WORK_PERMITS.some((o) => o.value === NEW_CANDIDATE_WORK_PERMIT)).toBe(true)
  })

  it('offers every value the backend enum knows', () => {
    expect(WORK_PERMITS.map((o) => o.value).sort()).toEqual(
      ['citizen', 'none', 'permanent', 'requires_sponsorship', 'unknown', 'work_visa'].sort(),
    )
  })

  it('shows an existing record as stored, unknown included', () => {
    expect(workPermitForEdit('unknown')).toBe('unknown')
    expect(workPermitForEdit('work_visa')).toBe('work_visa')
    expect(workPermitForEdit(undefined)).toBe('unknown')
  })
})
