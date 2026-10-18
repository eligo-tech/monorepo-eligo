// Which label wins on a live process step.
//
// The regression this file exists for: the cockpit's tracker read
//
//     Feedback Kunde · Interviewtermin · Vertrag
//
// in an English session, while the same tracker on demo data read
//
//     Feedback · Interview · Contract
//
// Both the frontend and the backend keep a nine-step table, and both label
// it in German — the frontend's through `t()`, the backend's as plain
// strings in `pipeline/steps.py`. `processCardsFromSteps` preferred
// `row.label`, so as soon as a workspace had real process rows the server's
// German won and the translation was undone.
//
// No static check can see this. The literal IS wrapped in `t()`; the wrong
// string simply wins at runtime, and only against live data. Hence a test
// at the join rather than another scanner.
//
// The rule it pins: our table for a key we know, the server's label only
// for a step the backend invented — an extra interview round, or a custom
// step the recruiter named, which is their words and not our copy.

import { beforeEach, describe, expect, it } from 'vitest'

import { setLang } from '@/i18n'
import type { ProcessJobDTO, ProcessStepDTO } from '@/api/types'

import { processCardsFromSteps } from './adapters'
import { PROCESS_STEPS } from './mock'

const step = (step_key: string, label: string): ProcessStepDTO => ({
  step_key,
  label,
  kind: 'milestone',
  scheduled_at: null,
  done_at: null,
  outcome: 'open',
  note: null,
})

/** One mandate, one candidate, the steps the server sent. */
const process = (steps: ProcessStepDTO[], order?: string[]): ProcessJobDTO[] => [
  {
    job_id: 'j1',
    job_title: 'DevOps Lead',
    company_id: 'c1',
    company_name: 'FinTech',
    location: null,
    must_have_skills: [],
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    status: 'open',
    candidates: [
      {
        application_id: 'a1',
        candidate_id: 'k1',
        candidate_name: 'Michael Vogel',
        stage: 'presented',
        presented_at: null,
        next_appointment: null,
        note: null,
        steps,
        step_order: order,
        assessment: null,
        salary_fit: null,
      },
    ],
  },
]

const labels = (dto: ProcessJobDTO[]) =>
  processCardsFromSteps(dto, [])[0].steps.map((s) => s.label)

describe('processCardsFromSteps — step labels', () => {
  describe('in English', () => {
    beforeEach(() => setLang('en'))

    it('translates a canonical step rather than echoing the server', () => {
      // These are exactly the German labels `pipeline/steps.py` sends.
      const dto = process(
        [
          step('vorgestellt', 'Vorgestellt'),
          step('feedback-1', 'Feedback Kunde'),
          step('interview', 'Interviewtermin'),
          step('vertrag', 'Vertrag'),
        ],
        ['vorgestellt', 'feedback-1', 'interview', 'vertrag'],
      )
      expect(labels(dto)).toEqual(['Presented', 'Feedback', 'Interview', 'Contract'])
    })

    it('keeps a custom step in the words the recruiter typed', () => {
      const dto = process(
        [step('custom_probearbeitstag', 'Probearbeitstag')],
        ['custom_probearbeitstag'],
      )
      expect(labels(dto)).toEqual(['Probearbeitstag'])
    })

    it('translates an extra interview round and keeps its number', () => {
      const dto = process(
        [step('interviewtermin_3', 'Interviewtermin 3')],
        ['interviewtermin_3'],
      )
      expect(labels(dto)).toEqual(['Interview 3'])
    })

    it('falls back to the key when the server sent no label at all', () => {
      expect(labels(process([], ['custom_unbekannt']))).toEqual(['custom_unbekannt'])
    })
  })

  // There is no "in German" counterpart, and the reason is the point of
  // `setLang` reloading the page: `PROCESS_STEPS` in `mock.ts` is a
  // module-level constant, so its labels are fixed in whatever language was
  // current when the module was imported — before any `beforeEach` runs.
  // A test cannot switch them afterwards, and neither can a re-render.
  // What CAN be asserted in any language is the rule itself.
  describe('in any language', () => {
    it('takes a canonical label from our table, never from the row', () => {
      const ours = PROCESS_STEPS.find((s) => s.key === 'vorgestellt')!.label
      const dto = process([step('vorgestellt', 'Vorgestellt')], ['vorgestellt'])
      expect(labels(dto)).toEqual([ours])
    })

    it('ignores a server label that disagrees with our table', () => {
      // If the backend renamed the step, we would still show our own word —
      // which is correct for one of the nine and is why a RENAMED step has
      // to be a custom step, with its own key.
      const dto = process([step('interview', 'Telefoninterview')], ['interview'])
      expect(labels(dto)).not.toContain('Telefoninterview')
      expect(labels(dto)).toEqual([
        PROCESS_STEPS.find((s) => s.key === 'interview')!.label,
      ])
    })

    it('passes a custom step through whatever the language', () => {
      const dto = process(
        [step('custom_probearbeitstag', 'Probearbeitstag')],
        ['custom_probearbeitstag'],
      )
      expect(labels(dto)).toEqual(['Probearbeitstag'])
    })
  })
})
