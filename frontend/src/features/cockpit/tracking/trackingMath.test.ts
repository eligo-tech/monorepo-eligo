import { describe, expect, it } from 'vitest'

import { daysLabel, goalName, paceTone, progress, ratioLabel } from './trackingMath'

describe('tracking arithmetic', () => {
  it('never divides by a goal of zero or overflows the bar', () => {
    expect(progress(5, 0)).toBe(0)
    expect(progress(5, null)).toBe(0)
    expect(progress(null, 10)).toBe(0)
    expect(progress(15, 10)).toBe(1)
    expect(progress(5, 10)).toBe(0.5)
  })

  it('bands the pace', () => {
    expect(paceTone(0.95)).toBe('mint')
    expect(paceTone(0.7)).toBe('gold')
    expect(paceTone(0.1)).toBe('coral')
  })

  it('shows n of m with the rate, and a blank where nobody was in the step', () => {
    // The test runner's language may be either; the numbers are the point.
    expect(ratioLabel({ reached: 2, of: 3, ratio: 2 / 3 })).toMatch(/^2 \S+ 3 · 67 %$/)
    expect(ratioLabel({ reached: 0, of: 1, ratio: 0 })).toMatch(/^0 \S+ 1 · 0 %$/)
    expect(ratioLabel({ reached: 0, of: 0, ratio: null })).toBe('—')
  })

  it('says the median days, or nothing when no dates could be measured', () => {
    expect(daysLabel(null)).toBe('—')
    expect(daysLabel(7)).toMatch(/^Median 7 (Tage|days)$/)
    expect(daysLabel(1)).toMatch(/^Median 1 (Tag|day)$/)
  })

  it('names a goal by its label, else by its people', () => {
    const people = [
      { actor_user_id: 'u1', name: 'Jonas', events: 3 },
      { actor_user_id: 'u2', name: 'Tobias', events: 1 },
    ]
    expect(goalName({ label: 'Team Nord', members: ['u1', 'u2'] }, people)).toBe('Team Nord')
    expect(goalName({ label: null, members: ['u1', 'u2'] }, people)).toBe('Jonas & Tobias')
    expect(goalName({ label: null, members: ['u9'] }, people)).toBe('u9')
  })
})
