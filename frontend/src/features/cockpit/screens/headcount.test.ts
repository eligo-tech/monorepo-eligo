import { describe, expect, it } from 'vitest'

import { num } from '@/i18n/format'

import { bucketLabel, HEADCOUNT_BUCKETS, headcountGate, headcountLabel } from './headcount'

// ELI-54: the Markt headcount filter's labels and its 30% gate.
describe('headcount', () => {
  it('offers the ten buckets of the ticket', () => {
    // Thousands in the reader's locale: "1.000" in German, "1,000" in English.
    const k = (n: number) => num(n)
    expect(HEADCOUNT_BUCKETS.map(bucketLabel)).toEqual([
      '1–3', '4–10', '11–50', '51–150', '151–300', '301–650',
      `651–${k(1000)}`, `${k(1001)}–${k(5000)}`, `${k(5001)}–${k(10000)}`, `${k(10001)}+`,
    ])
  })

  it('labels a point, a range and an open end', () => {
    expect(headcountLabel(250, 250)).toBe('250')
    expect(headcountLabel(51, 200)).toBe('51–200')
    expect(headcountLabel(500, null)).toBe('500+')
  })

  it('shows the filter only when the server says coverage is enough', () => {
    expect(headcountGate({ employers: 10, known: 3, coverage: 0.3, filter_available: true, buckets: [] }))
      .toEqual({ show: true, percent: 30 })
    expect(headcountGate({ employers: 10, known: 1, coverage: 0.123, filter_available: false, buckets: [] }))
      .toEqual({ show: false, percent: 12 })
    // A snapshot stored before ELI-54 has no coverage: no filter, 0 %.
    expect(headcountGate(undefined)).toEqual({ show: false, percent: 0 })
  })
})
