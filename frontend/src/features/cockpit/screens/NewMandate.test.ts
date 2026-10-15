import { describe, expect, it } from 'vitest'

import { typedName } from './NewMandate'

const rows = [{ name: 'Linde + Wiemann' }, { name: 'EM Software' }]
const nameOf = (r: { name: string }) => r.name

/** The regression this file exists for:
 *
 *  Typing "New Firm" into the Kunde box and pressing "Mandat anlegen" did
 *  nothing. The button was disabled because the only state the form could
 *  see was set by CLICKING the "neu anlegen" suggestion row — and the hint
 *  underneath read "Titel und Kunde fehlen noch" while both were on screen.
 *
 *  A name typed and left in the box is an answer. */
describe('typedName', () => {
  it('returns a name that is not in the list — that is a new client', () => {
    expect(typedName(rows, 'New Firm', nameOf)).toBe('New Firm')
  })

  it('trims, because a trailing space is not a different company', () => {
    expect(typedName(rows, '  New Firm  ', nameOf)).toBe('New Firm')
  })

  it('returns nothing for a name already on the list', () => {
    expect(typedName(rows, 'EM Software', nameOf)).toBe('')
  })

  it('ignores case when matching an existing one', () => {
    expect(typedName(rows, 'em software', nameOf)).toBe('')
    expect(typedName(rows, 'LINDE + WIEMANN', nameOf)).toBe('')
  })

  it('returns nothing for a stray keystroke', () => {
    expect(typedName(rows, '', nameOf)).toBe('')
    expect(typedName(rows, ' ', nameOf)).toBe('')
    expect(typedName(rows, 'L', nameOf)).toBe('')
  })

  it('works against an empty list — the first client in a new workspace', () => {
    expect(typedName([], 'New Firm', nameOf)).toBe('New Firm')
  })
})
