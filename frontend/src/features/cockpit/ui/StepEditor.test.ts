// The placement question has exactly one decision worth testing, and it is
// the one that decides whether the question is useful or noise: did THIS save
// just fill the mandate?
//
// Two ways to get it wrong, and both end with the question being ignored.
// Too quiet, and a recruiter who filled a role never gets asked, keeps
// searching on the mandate that is already closed, and its Laufzeit and
// ratios describe two searches. Too loud — asking again every time somebody
// corrects the contract date — and people learn to dismiss the dialog without
// reading it, which is the same outcome with extra clicks.

import { describe, expect, it } from 'vitest'

import { isPlaced, placementJustHappened, type StepFacts } from './StepEditor'

const step = (key: string, facts: Partial<StepFacts> = {}): StepFacts => ({
  key,
  scheduledAt: null,
  doneAt: null,
  outcome: 'open',
  ...facts,
})

/** A process that got as far as the offer and no further. */
const beforeTheContract: StepFacts[] = [
  step('vorgestellt', { doneAt: '2026-09-01T00:00:00Z', outcome: 'pass' }),
  step('interview', { doneAt: '2026-09-14T00:00:00Z', outcome: 'pass' }),
  step('offer', { doneAt: '2026-10-01T00:00:00Z', outcome: 'pass' }),
  step('vertrag'),
]

describe('isPlaced', () => {
  it('reads a done contract as filled', () => {
    expect(isPlaced([step('vertrag', { doneAt: '2026-10-20T00:00:00Z' })])).toBe(true)
  })

  it('reads a BOOKED contract as filled, like the backend does', () => {
    // `derive_stage` counts a scheduled step as reached: the date is the
    // commitment, and waiting for the signing appointment to happen would
    // leave the board a week behind the recruiter.
    expect(isPlaced([step('vertrag', { scheduledAt: '2026-11-02T10:00:00Z' })])).toBe(true)
  })

  it('reads a green contract cell as filled', () => {
    expect(isPlaced([step('vertrag', { outcome: 'pass' })])).toBe(true)
  })

  it('is not filled while the contract step is empty', () => {
    expect(isPlaced(beforeTheContract)).toBe(false)
  })

  it('is not filled when the contract fell through', () => {
    expect(
      isPlaced([step('vertrag', { doneAt: '2026-10-20T00:00:00Z', outcome: 'out' })]),
    ).toBe(false)
  })

  it('is not filled when any step is red — a red cell ends the process', () => {
    // The backend returns REJECTED before it looks at `vertrag`, so this is
    // not a placement however the last cell is coloured.
    expect(
      isPlaced([
        step('feedback-2', { outcome: 'out' }),
        step('vertrag', { doneAt: '2026-10-20T00:00:00Z' }),
      ]),
    ).toBe(false)
  })

  it('does not mistake another step for the contract', () => {
    expect(isPlaced([step('offer', { doneAt: '2026-10-01T00:00:00Z', outcome: 'pass' })])).toBe(
      false,
    )
  })
})

describe('placementJustHappened', () => {
  it('asks when the contract step is ticked', () => {
    expect(
      placementJustHappened(
        beforeTheContract,
        step('vertrag', { doneAt: '2026-10-20T00:00:00Z', outcome: 'pass' }),
      ),
    ).toBe(true)
  })

  it('asks when the signing appointment is booked', () => {
    expect(
      placementJustHappened(
        beforeTheContract,
        step('vertrag', { scheduledAt: '2026-11-02T10:00:00Z' }),
      ),
    ).toBe(true)
  })

  it('asks when the contract step had no row at all before', () => {
    // A step nobody has touched has no row, so it can be missing from the
    // card rather than present and empty.
    expect(
      placementJustHappened(
        beforeTheContract.filter((s) => s.key !== 'vertrag'),
        step('vertrag', { doneAt: '2026-10-20T00:00:00Z' }),
      ),
    ).toBe(true)
  })

  it('does not ask twice — correcting the contract date is not a second placement', () => {
    const placed = [
      ...beforeTheContract.slice(0, -1),
      step('vertrag', { doneAt: '2026-10-20T00:00:00Z', outcome: 'pass' }),
    ]
    expect(
      placementJustHappened(
        placed,
        step('vertrag', { doneAt: '2026-10-21T00:00:00Z', outcome: 'pass' }),
      ),
    ).toBe(false)
  })

  it('does not ask when the contract step is saved empty', () => {
    expect(placementJustHappened(beforeTheContract, step('vertrag'))).toBe(false)
  })

  it('does not ask when the contract fell through', () => {
    expect(
      placementJustHappened(
        beforeTheContract,
        step('vertrag', { doneAt: '2026-10-20T00:00:00Z', outcome: 'out' }),
      ),
    ).toBe(false)
  })

  it('does not ask on any earlier step', () => {
    for (const key of ['vorgestellt', 'feedback-1', 'interview', 'finaltermin', 'offer']) {
      expect(
        placementJustHappened(
          beforeTheContract,
          step(key, { doneAt: '2026-10-05T00:00:00Z', outcome: 'pass' }),
        ),
        key,
      ).toBe(false)
    }
  })

  it('does not ask when the process had already ended in a no', () => {
    const rejected = [...beforeTheContract, step('feedback-2', { outcome: 'out' })]
    expect(
      placementJustHappened(rejected, step('vertrag', { doneAt: '2026-10-20T00:00:00Z' })),
    ).toBe(false)
  })
})
