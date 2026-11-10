import { describe, expect, it } from 'vitest'

import {
  CANDIDATE_INTERACTION_KINDS,
  MANAGER_INTERACTION_KINDS,
  interactionLabel,
  isContact,
} from './interactionKinds'

// Mirrors backend/tests/test_interaction_vocabulary.py — the two lists must
// say the same thing, in the same order.
describe('ELI-9 note vocabulary', () => {
  it('puts Candidate Qualification first on a candidate', () => {
    expect([...CANDIDATE_INTERACTION_KINDS]).toEqual([
      'candidate_qualification',
      'candidate_call',
      'message',
      'na',
      'note',
    ])
  })

  it('never offers a qualification on a manager', () => {
    expect(MANAGER_INTERACTION_KINDS).not.toContain('candidate_qualification')
  })

  it('labels it in the recruiters’ own words', () => {
    expect(interactionLabel('candidate_qualification')).toBe('Candidate Qualification')
  })

  it('counts a qualification as contact, a missed call not', () => {
    expect(isContact('candidate_qualification')).toBe(true)
    expect(isContact('na')).toBe(false)
  })
})
