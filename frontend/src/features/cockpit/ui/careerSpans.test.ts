// What the chart may and may not claim.
//
// Every case here is a shape the CV extractor actually produces. The ones
// that matter most are the refusals: a career chart is read as a fact about a
// person, so a bar drawn from a date nobody wrote down is worse than no bar.

import { describe, expect, it } from 'vitest'

import type { RoleEntry } from '@/data/types'
import { BENIGN_GAP_MONTHS, buildTimeline, OPEN, parseStamp, ticks } from './careerSpans'

const role = (start?: string, end?: string, title = 'Dev'): RoleEntry => ({
  title,
  company: 'ACME',
  start,
  end,
  highlights: [],
})

const NOW = new Date(2026, 9, 19) // October 2026

describe('parseStamp', () => {
  it('reads the formats a CV actually uses', () => {
    const cases: [string, number, string][] = [
      ['2019', 2019 * 12 + 0, 'year'],
      ['2019-03', 2019 * 12 + 2, 'month'],
      ['2019-03-15', 2019 * 12 + 2, 'month'],
      ['03/2019', 2019 * 12 + 2, 'month'],
      ['3/2019', 2019 * 12 + 2, 'month'],
      ['Mar 2019', 2019 * 12 + 2, 'month'],
      ['März 2019', 2019 * 12 + 2, 'month'],
      ['Sept. 2019', 2019 * 12 + 8, 'month'],
      ['Mai 2019', 2019 * 12 + 4, 'month'],
      ['seit Januar 2021', 2021 * 12 + 0, 'month'],
      ['Okt 2019', 2019 * 12 + 9, 'month'],
      ['Dezember 1998', 1998 * 12 + 11, 'month'],
    ]
    for (const [raw, months, precision] of cases) {
      expect(parseStamp(raw, 'start'), raw).toEqual({ months, precision })
    }
  })

  it('reads a bare year charitably at both ends', () => {
    // So that "… – 2019" followed by "2020 – …" is continuous employment and
    // not an eleven-month hole the source never claimed.
    expect(parseStamp('2019', 'start')).toEqual({ months: 2019 * 12, precision: 'year' })
    expect(parseStamp('2019', 'end')).toEqual({ months: 2019 * 12 + 11, precision: 'year' })
  })

  it('treats the present, however it is spelled, as open', () => {
    for (const s of ['heute', 'bis heute', 'Present', 'today', 'aktuell', 'now', 'laufend'])
      expect(parseStamp(s, 'end'), s).toBe(OPEN)
  })

  it('treats a missing end as open and a missing start as unreadable', () => {
    expect(parseStamp('', 'end')).toBe(OPEN)
    expect(parseStamp(undefined, 'end')).toBe(OPEN)
    expect(parseStamp('', 'start')).toBe(null)
  })

  it('returns null rather than a guess', () => {
    for (const s of ['irgendwann', 'ab sofort', 'n/a', '—', '13/2019 ']) {
      const got = parseStamp(s, 'start')
      // "13/2019" has a year in it and no legal month, so it is a year-only
      // stamp — never a month invented from a wrong number.
      expect(got === null || (got !== OPEN && got.precision === 'year'), s).toBe(true)
    }
    expect(parseStamp('irgendwann', 'start')).toBe(null)
  })
})

describe('buildTimeline', () => {
  it('ends a role AFTER its last month — March to March is one month, not zero', () => {
    const tl = buildTimeline([role('2019-03', '2019-03'), role('2020-01', '2020-06')], NOW)!
    expect(tl.spans[0].to - tl.spans[0].from).toBe(1)
    expect(tl.spans[1].to - tl.spans[1].from).toBe(6)
  })

  it('keeps the rows in the order the list shows them', () => {
    const tl = buildTimeline(
      [role('2022-01', '2024-01', 'Newest'), role('2015-01', '2022-01', 'Oldest')],
      NOW,
    )!
    expect(tl.spans.map((s) => s.role.title)).toEqual(['Newest', 'Oldest'])
  })

  it('counts what it cannot place instead of dropping it', () => {
    const tl = buildTimeline(
      [role('2020-01', '2022-01'), role('2015-01', '2018-01'), role('irgendwann', '2015-01')],
      NOW,
    )!
    expect(tl.spans).toHaveLength(2)
    expect(tl.undated).toBe(1)
  })

  it('refuses a role that ends before it starts', () => {
    const tl = buildTimeline(
      [role('2022-01', '2019-01'), role('2015-01', '2018-01'), role('2018-02', '2021-12')],
      NOW,
    )!
    expect(tl.spans).toHaveLength(2)
    expect(tl.undated).toBe(1)
  })

  it('draws nothing from a single dated role', () => {
    expect(buildTimeline([role('2020-01', '2022-01'), role()], NOW)).toBe(null)
    expect(buildTimeline([], NOW)).toBe(null)
  })

  it('runs an open role to today and says so', () => {
    const tl = buildTimeline([role('2024-03'), role('2019-01', '2024-02')], NOW)!
    expect(tl.openEnded).toBe(true)
    expect(tl.spans[0].open).toBe(true)
    expect(tl.spans[0].to).toBe(2026 * 12 + 9 + 1)
    expect(tl.to).toBe(2027 * 12)
  })

  it('stops the axis at the last date on the CV when nothing is open', () => {
    const tl = buildTimeline([role('2015-06', '2018-05'), role('2018-06', '2021-03')], NOW)!
    expect(tl.openEnded).toBe(false)
    expect(tl.from).toBe(2015 * 12)
    expect(tl.to).toBe(2022 * 12)
  })

  describe('gaps', () => {
    it('finds a hole between two month-precise roles', () => {
      const tl = buildTimeline([role('2019-01', '2020-06'), role('2021-02', '2023-01')], NOW)!
      expect(tl.gaps).toEqual([{ from: 2020 * 12 + 6, to: 2021 * 12 + 1, months: 7 }])
    })

    it('ignores a notice period', () => {
      // Three months is the usual German Kündigungsfrist: Jun → Oct is the
      // most ordinary job change there is and must not be flagged.
      const tl = buildTimeline([role('2019-01', '2020-06'), role('2020-10', '2023-01')], NOW)!
      expect(tl.gaps).toEqual([])
      expect(BENIGN_GAP_MONTHS).toBe(3)
    })

    it('flags the month after that', () => {
      const tl = buildTimeline([role('2019-01', '2020-06'), role('2020-11', '2023-01')], NOW)!
      expect(tl.gaps).toHaveLength(1)
      expect(tl.gaps[0].months).toBe(4)
    })

    it('will not invent one out of year-only dates', () => {
      // "… – 2019" then "2021 – …" leaves 2020 unaccounted for, which IS a
      // year, so it counts. "… – 2019" then "2020 – …" does not: the source
      // cannot resolve it either way.
      expect(buildTimeline([role('2015', '2019'), role('2020', '2023')], NOW)!.gaps).toEqual([])
      expect(buildTimeline([role('2015', '2019'), role('2021', '2023')], NOW)!.gaps).toHaveLength(1)
    })

    it('does not read two parallel roles as a gap', () => {
      // A freelance mandate beside an employment: the long one covers the
      // short one, and what follows is measured against the furthest point
      // reached, not against the previous row.
      const tl = buildTimeline(
        [role('2018-01', '2024-12'), role('2019-01', '2019-06'), role('2025-01', '2025-12')],
        NOW,
      )!
      expect(tl.gaps).toEqual([])
    })

    it('measures the hole before the current job too', () => {
      const tl = buildTimeline([role('2015-01', '2019-12'), role('2021-06')], NOW)!
      expect(tl.gaps).toHaveLength(1)
      expect(tl.gaps[0].months).toBe(17)
    })
  })

  it('puts the axis on January boundaries', () => {
    const tl = buildTimeline([role('2015-06', '2018-05'), role('2018-06', '2021-03')], NOW)!
    expect(tl.from % 12).toBe(0)
    expect(tl.to % 12).toBe(0)
  })
})

describe('ticks', () => {
  it('labels every year of a short career', () => {
    expect(ticks(2019 * 12, 2023 * 12)).toEqual([2019, 2020, 2021, 2022, 2023])
  })

  it('thins a long one to round years', () => {
    expect(ticks(1996 * 12, 2026 * 12)).toEqual([2000, 2005, 2010, 2015, 2020, 2025])
  })

  it('never returns more labels than it was allowed', () => {
    for (let years = 1; years <= 60; years += 1)
      expect(ticks(2000 * 12, (2000 + years) * 12).length, `${years}y`).toBeLessThanOrEqual(6)
  })
})
