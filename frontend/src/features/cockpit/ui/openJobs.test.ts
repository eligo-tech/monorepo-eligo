import { describe, expect, it } from 'vitest'
import { jobsShown } from './openJobs'

// ELI-33: what a company is hiring for now, on its page and beside a manager.
const job = (title: string) => ({ title, city: 'München', posted_at: null, source: 'bundesagentur', url: null })

describe('open jobs', () => {
  it('shows the first few and says how many more there are', () => {
    const market = { linked: true, total: 7, jobs: ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map(job), careers: null }
    expect(jobsShown(market, 5)).toEqual({ shown: market.jobs.slice(0, 5), more: 2 })
  })

  it('counts beyond the jobs listed — the page carries at most 50', () => {
    const market = { linked: true, total: 80, jobs: Array.from({ length: 50 }, (_, i) => job(String(i))), careers: null }
    expect(jobsShown(market, 5).more).toBe(75)
  })

  it('an unlinked company has nothing to show', () => {
    expect(jobsShown({ linked: false, total: 0, jobs: [], careers: null }, 5)).toEqual({ shown: [], more: 0 })
  })
})
