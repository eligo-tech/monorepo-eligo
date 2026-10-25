// Reading a salary out of a text box.
//
// Two forms now depend on this — the mandate's band and the candidate's
// expectation — which is why it has one home. The failure it exists to
// prevent is silent: a recruiter types what they always type, the parse
// returns something plausible but wrong, and a hard filter then excludes
// people against a number nobody checked.

import { describe, expect, it } from 'vitest'

import { toAmount } from './amount'

describe('toAmount', () => {
  it('reads the separators people actually type', () => {
    for (const text of ['92000', '92.000', '92,000', ' 92.000 ', '92 000']) {
      expect(toAmount(text), text).toBe(92000)
    }
  })

  it('reads the shorthand', () => {
    expect(toAmount('92k')).toBe(92000)
    expect(toAmount('92K')).toBe(92000)
  })

  it('does not multiply a number that is already thousands', () => {
    // "92000k" is a typo, not 92 million. The suffix only expands a value
    // small enough to have meant thousands.
    expect(toAmount('92000k')).toBe(92000)
  })

  it('is empty for text with no number in it', () => {
    // "nach Vereinbarung" is an answer, but it is not a figure, and turning
    // it into one would put a cap on a search nobody set.
    for (const text of ['', '   ', 'nach Vereinbarung', 'k', '—']) {
      expect(toAmount(text), JSON.stringify(text)).toBeNull()
    }
  })

  it('ignores a currency symbol', () => {
    expect(toAmount('€ 92.000')).toBe(92000)
    expect(toAmount('92.000 EUR')).toBe(92000)
  })
})
