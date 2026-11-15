import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { t } from '@/i18n'

import { InteractionComposer, composeEntry } from './InteractionComposer'
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
