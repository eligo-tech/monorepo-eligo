import { describe, expect, it } from 'vitest'
import type { LeadJobDTO } from '@/api/types'
import { leadJobLine, mandateHref } from './leadJobs'

const job = (over: Partial<LeadJobDTO> = {}): LeadJobDTO => ({
  title: 'Pflegefachkraft (m/w/d)',
  location: 'Ulm',
  url: 'https://www.arbeitsagentur.de/jobsuche/jobdetail/1',
  posting_id: 'p1',
  job_id: null,
  ...over,
})

describe('ELI-37: the jobs on a lead', () => {
  it('reads title and place', () => {
    expect(leadJobLine(job())).toBe('Pflegefachkraft (m/w/d) · Ulm')
    expect(leadJobLine(job({ location: null }))).toBe('Pflegefachkraft (m/w/d)')
  })

  it('links a job the workspace holds to its page, and nothing else', () => {
    expect(mandateHref(job({ job_id: 'j1' }))).toBe('#cockpit/j1')
    expect(mandateHref(job())).toBeNull()
  })
})
