import { describe, expect, it } from 'vitest'

import { fitMono, mandateCaption } from './MandateGraph'

import { PROCESS_STEPS } from '../data/mock'

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

/** The candidate node, one level further in. Its two lines share the box
 *  with the score on the right, so the room they have is the box minus the
 *  inset, the dot, and the reserve a "10/10" needs. */
const CAND_LINE = 396 - (16 + 22) - 72

describe('the candidate line', () => {
  it('holds every standing the process can be in', () => {
    for (const { label } of PROCESS_STEPS) {
      for (const standing of [label, `${label} ✓`, `abgesagt · ${label}`]) {
        expect(fitMono(standing, CAND_LINE, 11)).toBe(standing)
      }
    }
  })

  it('holds the state a process with no step at all is in', () => {
    expect(fitMono('noch kein Schritt', CAND_LINE, 11)).toBe('noch kein Schritt')
  })

  it('cuts a longer line rather than running it under the score', () => {
    const long = 'abgesagt · ' + 'Interviewtermin mit dem Fachbereich und der IT-Leitung'
    const cut = fitMono(long, CAND_LINE, 11)
    expect(cut.endsWith('…')).toBe(true)
    expect(cut.length * 11 * 0.6).toBeLessThanOrEqual(CAND_LINE)
  })

  it('keeps at least two characters, however little room there is', () => {
    expect(fitMono('Vorgestellt', 4, 11).length).toBe(2)
  })
})
