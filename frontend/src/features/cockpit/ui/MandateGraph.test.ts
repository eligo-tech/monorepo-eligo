import { describe, expect, it } from 'vitest'

import { mandateCaption } from './MandateGraph'

/** The regression this file exists for:
 *
 *  On `#cockpit` the mandate node read
 *
 *      Linde + Wiemann · 3 Kandidaten · bester Fit 8/10
 *
 *  and the score crossed the tone dot, the caret and the right edge of its
 *  own box. The line was written left to right, so the only thing clipped
 *  was the client name — at a fixed 18 characters that had nothing to do
 *  with the width actually left over.
 *
 *  Mono is a fixed advance, so these are exact widths: the caption must fit
 *  the box minus the padding and the controls on the right. */
const WIDTH = 392
const FITS = (caption: string) => caption.length * 11 * 0.6 <= WIDTH - 16 - 58

describe('mandateCaption', () => {
  it('keeps the score inside the box — the case from the screenshot', () => {
    const caption = mandateCaption('Linde + Wiemann', 3, 8)
    expect(caption).toBe('Linde + Wiemann · 3 Kandidaten · bester Fit 8/10')
    expect(FITS(caption)).toBe(true)
  })

  it('gives up the client name, never the score', () => {
    const caption = mandateCaption(
      'Eine Firma mit einem unverschämt langen Namen GmbH & Co. KG',
      3,
      8,
    )
    expect(caption.endsWith('· bester Fit 8/10')).toBe(true)
    expect(caption).toContain('…')
    expect(FITS(caption)).toBe(true)
  })

  it('says a mandate nobody has assessed has no score, not a zero', () => {
    expect(mandateCaption('Sixt', 5, null)).toBe('Sixt · 5 Kandidaten · ohne Bewertung')
  })

  it('counts one candidate in the singular', () => {
    expect(mandateCaption('KVB', 1, null)).toBe('KVB · 1 Kandidat · ohne Bewertung')
  })

  it('fits whatever it is given — every client in the book, both tails', () => {
    const clients = ['GE Software', 'Computacenter', 'SSI', 'KurtzErsa', 'EM Software']
    for (const client of clients) {
      for (const fit of [null, 0, 10] as const) {
        for (const count of [1, 12]) {
          expect(FITS(mandateCaption(client, count, fit))).toBe(true)
        }
      }
    }
  })

  it('leaves at least a trace of the name when the tail eats the line', () => {
    expect(mandateCaption('Computacenter', 5, 8, { width: 180 })).toMatch(
      /^C?…? ?· 5 Kandidaten · bester Fit 8\/10$/,
    )
  })
})
