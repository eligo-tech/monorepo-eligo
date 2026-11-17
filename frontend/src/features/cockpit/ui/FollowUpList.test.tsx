import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'
import type { FollowUpDTO } from '@/api/types'

import { FollowUpOffer } from './FollowUpOffer'
import { FollowUpRows } from './FollowUpList'

// ELI-44. No DOM here: rendered to markup.

const row = (over: Partial<FollowUpDTO>): FollowUpDTO => ({
  id: 'f1',
  manager_id: 'm1',
  candidate_id: null,
  source_interaction_id: null,
  due_date: '2027-02-01',
  due_time: null,
  text: 'Wieder melden',
  status: 'open',
  origin: 'manual',
  created_at: '2026-11-17T09:00:00Z',
  created_by_name: null,
  done_at: null,
  done_by_name: null,
  subject_kind: 'lead',
  person_name: 'Petra Weber',
  company_id: 'c1',
  company_name: 'Zühlke Engineering GmbH',
  ...over,
})

const noop = () => undefined

describe('FollowUpOffer', () => {
  it('offers the date read from the note, quoting the phrase', () => {
    const html = renderToStaticMarkup(
      <FollowUpOffer
        suggestions={[{ due_date: '2027-02-01', phrase: 'Anfang Februar' }]}
        onConfirm={noop}
        onDismiss={noop}
      />,
    )
    const when = fmtDate(new Date(2027, 1, 1))
    expect(html).toContain(t('Wiedervorlage am {date} anlegen?', { date: when }))
    expect(html).toContain('Anfang Februar')
    expect(html).toContain(t('Anlegen'))
    expect(html).toContain(t('Verwerfen'))
  })

  it('offers the other dates a note names as alternatives', () => {
    const html = renderToStaticMarkup(
      <FollowUpOffer
        suggestions={[
          { due_date: '2026-12-01', phrase: 'in 2 Wochen' },
          { due_date: '2026-12-15', phrase: 'Mitte Dezember' },
        ]}
        onConfirm={noop}
        onDismiss={noop}
      />,
    )
    expect(html).toContain(fmtDate(new Date(2026, 11, 15)))
    expect(html).toContain('Mitte Dezember')
  })

  it('says nothing when the note names no date', () => {
    expect(renderToStaticMarkup(<FollowUpOffer suggestions={[]} onConfirm={noop} onDismiss={noop} />)).toBe('')
  })
})

describe('FollowUpRows', () => {
  const rows = [
    row({ id: 'late', due_date: '2026-11-10', text: 'Überfällig' }),
    row({ id: 'now', due_date: '2026-11-17', text: 'Heute dran' }),
    row({
      id: 'k',
      due_date: '2027-01-04',
      subject_kind: 'candidate',
      manager_id: null,
      candidate_id: 'k1',
      person_name: 'Erika Muster',
      company_name: null,
    }),
  ]

  it('groups overdue (red), today and upcoming, each linked to the person', () => {
    const html = renderToStaticMarkup(
      <FollowUpRows rows={rows} today="2026-11-17" showPerson onDone={noop} onCalendar={noop} />,
    )
    expect(html).toContain(t('Überfällig'))
    expect(html).toContain(t('Heute'))
    expect(html).toContain(t('Demnächst'))
    expect(html).toContain('text-coral-400')
    expect(html).toContain('href="#managers/m1"')
    expect(html).toContain('href="#kandidaten/k1"')
    expect(html).toContain('Erika Muster')
    expect(html).toContain(t('Erledigt'))
    expect(html).toContain(t('In Kalender'))
    // Order on the page: overdue first.
    expect(html.indexOf(t('Überfällig')) < html.indexOf('Heute dran')).toBe(true)
    expect(html.indexOf('Heute dran') < html.indexOf('Erika Muster')).toBe(true)
  })

  it('leaves the person out on their own page', () => {
    const html = renderToStaticMarkup(
      <FollowUpRows rows={rows.slice(0, 1)} today="2026-11-17" onDone={noop} onCalendar={noop} />,
    )
    expect(html).not.toContain('href="#managers/m1"')
  })
})
