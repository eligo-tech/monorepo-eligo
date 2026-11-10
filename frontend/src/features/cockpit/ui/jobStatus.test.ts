import { describe, expect, it } from 'vitest'
import { JOB_STATUSES, isLive, jobStatusLabel, statusChoices } from './jobStatus'

// ELI-22: an ad taken from Markt is a `lead` — business development, not a
// mandate. It must never count as live business, and nothing goes back to it.
describe('lead', () => {
  it('is a known status, listed first because it happens first', () => {
    expect(JOB_STATUSES[0]).toBe('lead')
    expect(JOB_STATUSES).toContain('active')
    expect(JOB_STATUSES).toContain('inactive')
  })

  it('is not live business', () => {
    expect(isLive('lead')).toBe(false)
    expect(isLive('active')).toBe(true)
  })

  it('has a label of its own instead of the raw word', () => {
    expect(jobStatusLabel('lead')).toBe('Lead')
  })

  it('offers the moves the backend allows, and no way back to lead', () => {
    expect(statusChoices('lead')).toEqual(['lead', 'active', 'inactive'])
    expect(statusChoices('active')).toEqual(['active', 'inactive'])
    expect(statusChoices('open')).toEqual(['active', 'inactive'])
    expect(statusChoices('inactive')).toEqual(['inactive'])
  })
})
