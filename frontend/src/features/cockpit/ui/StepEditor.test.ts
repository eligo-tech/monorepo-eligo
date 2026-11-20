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

import {
  autoDoneAt,
  initialStepInputs,
  isPlaced,
  parseFee,
  placementJustHappened,
  presentedStep,
  type StepFacts,
} from './StepEditor'

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

// ── ELI-28: the dialog opens on "now" ───────────────────────────────────────
//
// "Vorauswahl ist immer das aktuelle Datum mit der aktuellen Uhrzeit." Only an
// EMPTY step is filled, and only the date the step is about: a milestone is
// done now, an appointment is booked now. Filling both would mark an
// interview as having happened the moment somebody opened it to book it.

describe('initialStepInputs', () => {
  // 14:05 UTC on 15 Nov 2026 is 15:05 on a Berlin wall clock (CET, +1).
  const now = new Date('2026-11-15T14:05:00Z')

  it('opens an appointment as booked now (ELI-28)', () => {
    expect(initialStepInputs({ key: 'interview' }, now)).toEqual({ scheduled: '2026-11-15T15:05' })
    expect(initialStepInputs({ key: 'interviewtermin_3' }, now).scheduled).toBe('2026-11-15T15:05')
  })

  it('leaves a milestone’s Termin empty — the calendar fills today on a click (ELI-21)', () => {
    expect(initialStepInputs({ key: 'vorgestellt' }, now)).toEqual({ scheduled: '' })
  })

  it('never overwrites what is already recorded', () => {
    expect(initialStepInputs({ key: 'interview', scheduledAt: '2026-12-01T09:00:00Z' }, now)).toEqual({
      scheduled: '2026-12-01T10:00',
    })
  })

  it('does not prefill a step further down the process', () => {
    expect(initialStepInputs({ key: 'interview', state: 'pending' }, now)).toEqual({ scheduled: '' })
  })
})

describe('autoDoneAt — "Erledigt am" is no longer typed (ELI-21)', () => {
  const now = new Date('2026-11-18T15:12:00Z')
  const at = now.toISOString()

  it('a due milestone saved without a Termin happened now (what ELI-28 prefilled)', () => {
    expect(autoDoneAt({ key: 'vorgestellt' }, { scheduled: '', outcome: 'open' }, now)).toBe(at)
    expect(autoDoneAt({ key: 'feedback-1', state: 'current' }, { scheduled: '', outcome: 'open' }, now)).toBe(at)
  })

  it('a milestone given a Termin has not happened yet', () => {
    expect(
      autoDoneAt({ key: 'vorgestellt' }, { scheduled: '2026-11-20T10:00', outcome: 'open' }, now),
    ).toBeUndefined()
  })

  it('a verdict is the moment the step was done', () => {
    expect(autoDoneAt({ key: 'interview' }, { scheduled: '2026-11-20T10:00', outcome: 'pass' }, now)).toBe(at)
    expect(autoDoneAt({ key: 'interview' }, { scheduled: '', outcome: 'out' }, now)).toBe(at)
  })

  it('an open appointment is booked, not done', () => {
    expect(autoDoneAt({ key: 'interview' }, { scheduled: '2026-11-20T10:00', outcome: 'open' }, now)).toBeUndefined()
  })

  it('never moves a date already recorded', () => {
    expect(
      autoDoneAt({ key: 'vorgestellt', doneAt: '2026-09-01T08:30:00Z' }, { scheduled: '', outcome: 'pass' }, now),
    ).toBeUndefined()
  })

  it('a step further down, opened for a note, is not done', () => {
    expect(autoDoneAt({ key: 'vertrag', state: 'pending' }, { scheduled: '', outcome: 'open' }, now)).toBeUndefined()
  })

  it('a step that already had a verdict or a Termin is not re-dated by a note', () => {
    expect(
      autoDoneAt({ key: 'vorgestellt', outcome: 'pass' }, { scheduled: '', outcome: 'pass' }, now),
    ).toBeUndefined()
    expect(
      autoDoneAt(
        { key: 'vorgestellt', scheduledAt: '2026-11-10T09:00:00Z' },
        { scheduled: '2026-11-10T10:00', outcome: 'open' },
        now,
      ),
    ).toBeUndefined()
  })
})

describe('presentedStep', () => {
  it('is the Vorgestellt step, with nothing recorded yet', () => {
    const s = presentedStep()
    expect(s.key).toBe('vorgestellt')
    expect(s.doneAt ?? null).toBeNull()
    // Saved straight after "Zu Mandat zuordnen", it is presented now.
    const now = new Date('2026-07-01T06:00:00Z')
    expect(autoDoneAt(s, { scheduled: '', outcome: 'open' }, now)).toBe(now.toISOString())
  })
})


// ELI-64: the Honorar on the Vertrag step is what Umsatz adds up. People type
// it the way they write it; a misread number is revenue that never happened.
describe('the Honorar as typed', () => {
  it('reads whole euros however they are written', () => {
    expect(parseFee('25000')).toBe(25000)
    expect(parseFee('25.000')).toBe(25000)
    expect(parseFee('25 000 €')).toBe(25000)
    expect(parseFee('25.000,00')).toBe(25000)
  })

  it('treats empty as no fee and refuses what is not a whole number', () => {
    expect(parseFee('')).toBeNull()
    expect(parseFee('  ')).toBeNull()
    expect(parseFee('25k')).toBe('invalid')
    expect(parseFee('12,5')).toBe('invalid')
    expect(parseFee('-3')).toBe('invalid')
  })
})
