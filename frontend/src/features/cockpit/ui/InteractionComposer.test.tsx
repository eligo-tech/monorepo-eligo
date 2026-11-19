import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { t } from '@/i18n'

import { InteractionComposer, canSaveNote, composeEntry, isCompleteDay } from './InteractionComposer'
import { MANAGER_INTERACTION_KINDS } from './interactionKinds'

// ELI-40. No DOM test environment here, so the composer is rendered to markup
// per kind, and what it hands to `onSave` is a pure function.
const render = (defaultKind: string) =>
  renderToStaticMarkup(
    <InteractionComposer
      kinds={MANAGER_INTERACTION_KINDS}
      defaultKind={defaultKind}
      onSave={async () => undefined}
      onCancel={() => undefined}
    />,
  )

describe('InteractionComposer', () => {
  it('asks for a time when the note is a Termin', () => {
    const html = render('meeting')
    expect(html).toContain('type="time"')
    expect(html).toContain(t('→ wird unter Termine eingetragen'))
  })

  it('stays date-only for every other kind', () => {
    const html = render('business_call')
    expect(html).not.toContain('type="time"')
    expect(html).toContain('type="date"')
  })
})

describe('composeEntry', () => {
  it('saves a Termin at the time it was set for', () => {
    expect(composeEntry('meeting', ' Kickoff ', '2026-11-20', '14:30')).toEqual({
      interaction_type: 'meeting',
      summary: 'Kickoff',
      occurred_at: new Date('2026-11-20T14:30:00').toISOString(),
    })
  })

  it('ignores a time for a kind that does not take one — unchanged behaviour', () => {
    expect(composeEntry('business_call', 'erreicht', '2026-11-20', '14:30').occurred_at).toBe(
      new Date('2026-11-20T12:00:00').toISOString(),
    )
  })
})

// ELI-32: the two Datenschutz outcomes.
describe('privacy outcomes', () => {
  const withPrivacy = (canErase: boolean) =>
    renderToStaticMarkup(
      <InteractionComposer
        kinds={MANAGER_INTERACTION_KINDS}
        onSave={async () => undefined}
        onCancel={() => undefined}
        privacy={{ onErase: () => undefined, canErase }}
      />,
    )

  it('offers "Nicht mehr kontaktieren" and "Löschen (DSGVO)" only where the page passes them', () => {
    const html = withPrivacy(true)
    expect(html).toContain(t('Nicht mehr kontaktieren'))
    expect(html).toContain(t('Löschen (DSGVO)'))
    expect(render('note')).not.toContain(t('Löschen (DSGVO)'))
  })

  it('saves "Nicht mehr kontaktieren" with the note, even without text', () => {
    expect(composeEntry('business_call', '', '2026-11-20', '14:30', 'do_not_contact')).toMatchObject({
      interaction_type: 'business_call',
      summary: 'Möchte nicht mehr kontaktiert werden.',
      do_not_contact: true,
    })
    expect(composeEntry('note', ' Bitte keine Anrufe ', '2026-11-20', '', 'do_not_contact').summary).toBe(
      'Bitte keine Anrufe',
    )
    expect(composeEntry('note', 'x', '2026-11-20', '')).not.toHaveProperty('do_not_contact')
  })

  it('needs text for an ordinary note, none for the privacy outcomes', () => {
    const day = '2026-11-20'
    expect(canSaveNote('', '', 'note', null, day)).toBe(false)
    expect(canSaveNote('  ', '', 'note', null, day)).toBe(false)
    expect(canSaveNote('erreicht', '', 'note', null, day)).toBe(true)
    expect(canSaveNote('', 'do_not_contact', 'note', null, day)).toBe(true)
    expect(canSaveNote('', 'erase', 'note', null, day)).toBe(true)
  })
})

// ELI-56: a candidate note "could not be saved". A date field whose day was
// cleared or half-typed ("tt.11.2026") reports '' — and `occurredAt('')`
// threw a RangeError inside save(), so the composer said "Nicht gespeichert —
// bitte erneut versuchen" and never sent a request. Retrying could not help.
describe('an incomplete date', () => {
  it('is caught before saving instead of failing every retry', () => {
    expect(isCompleteDay('')).toBe(false)
    expect(isCompleteDay('2026-11')).toBe(false)
    expect(isCompleteDay('2026-02-31')).toBe(false)
    expect(isCompleteDay('2026-11-19')).toBe(true)
    expect(canSaveNote('Kurz telefoniert', '', 'note', null, '')).toBe(false)
    expect(canSaveNote('', 'do_not_contact', 'note', null, '')).toBe(false)
    // Erasure saves no note, so it needs no date.
    expect(canSaveNote('', 'erase', 'note', null, '')).toBe(true)
  })

  it('never makes composeEntry throw', () => {
    expect(() => composeEntry('candidate_qualification', 'x', '', '')).not.toThrow()
  })
})
