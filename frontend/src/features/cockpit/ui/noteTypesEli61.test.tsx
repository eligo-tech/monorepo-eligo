import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { t } from '@/i18n'

import {
  InteractionComposer,
  canSaveNote,
  profilesFollowUp,
} from './InteractionComposer'
import { MANAGER_INTERACTION_KINDS, CANDIDATE_INTERACTION_KINDS, interactionLabel, isContact } from './interactionKinds'
import { addWorkingDays } from './followUps'

// ELI-61: „Gesprächsnotiz“ and „Anonyme Profile gesendet“ on a manager.
// Mirrors backend/tests/test_note_types_eli61.py.

describe('ELI-61 note kinds', () => {
  it('offers both on a manager, in the backend order, and not on a candidate', () => {
    expect([...MANAGER_INTERACTION_KINDS]).toEqual([
      'meeting',
      'client_call',
      'business_call',
      'conversation',
      'profiles_sent',
      'message',
      'na',
      'note',
    ])
    expect(CANDIDATE_INTERACTION_KINDS).not.toContain('conversation')
    expect(CANDIDATE_INTERACTION_KINDS).not.toContain('profiles_sent')
  })

  it('labels them as the ticket names them', () => {
    expect(interactionLabel('conversation')).toBe(t('Gesprächsnotiz'))
    expect(interactionLabel('profiles_sent')).toBe(t('Anonyme Profile gesendet'))
  })

  it('counts a Gesprächsnotiz as reached', () => {
    expect(isContact('conversation')).toBe(true)
    expect(isContact('profiles_sent')).toBe(true)
  })
})

describe('addWorkingDays', () => {
  it('skips the weekend', () => {
    // Thu 19.11.2026 + 3 working days = Tue 24.11.
    expect(addWorkingDays('2026-11-19', 3)).toBe('2026-11-24')
    // Mon + 3 = Thu.
    expect(addWorkingDays('2026-11-16', 3)).toBe('2026-11-19')
    // From a Saturday: Mon, Tue, Wed.
    expect(addWorkingDays('2026-11-21', 3)).toBe('2026-11-25')
  })

  it('skips the holidays the backend date reader skips', () => {
    // Wed 23.12.2026: Thu 24, (Fri 25 + Sat 26 + Sun 27 off), Mon 28, Tue 29.
    expect(addWorkingDays('2026-12-23', 3)).toBe('2026-12-29')
    // Wed 30.12.: Thu 31, (Fri 1.1. off), Mon 4, Tue 5.
    expect(addWorkingDays('2026-12-30', 3)).toBe('2027-01-05')
  })
})

describe('Anonyme Profile gesendet → Wiedervorlage', () => {
  const render = (defaultKind: string) =>
    renderToStaticMarkup(
      <InteractionComposer
        kinds={MANAGER_INTERACTION_KINDS}
        defaultKind={defaultKind}
        onSave={async () => undefined}
        onCancel={() => undefined}
      />,
    )

  it('shows the Wiedervorlage, prefilled and editable, for profiles sent only', () => {
    const html = render('profiles_sent')
    expect(html).toContain(t('Feedback zu anonymen Profilen'))
    expect(html).toContain(t('Wiedervorlage'))
    expect(render('conversation')).not.toContain(t('Feedback zu anonymen Profilen'))
  })

  it('defaults to three working days from today in Germany', () => {
    // 23:30 UTC on Wed 18.11. is already Thu 19.11. in Berlin.
    const now = new Date('2026-11-18T23:30:00Z')
    expect(profilesFollowUp(now)).toEqual({ due_date: '2026-11-24', text: t('Feedback zu anonymen Profilen') })
  })

  it('needs no note text, but a Wiedervorlage with a day and a to-do', () => {
    expect(canSaveNote('', '', 'profiles_sent', { due_date: '2026-11-24', text: 'Feedback' })).toBe(true)
    expect(canSaveNote('', '', 'profiles_sent', { due_date: '', text: 'Feedback' })).toBe(false)
    expect(canSaveNote('', '', 'profiles_sent', { due_date: '2026-11-24', text: ' ' })).toBe(false)
    // Every other kind still needs words.
    expect(canSaveNote('', '', 'conversation')).toBe(false)
  })
})
