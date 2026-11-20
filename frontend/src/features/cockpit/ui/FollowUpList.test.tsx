import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { getLang, setLang, t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'
import type { FollowUpDTO } from '@/api/types'

import { FollowUpOffer } from './FollowUpOffer'
import { FollowUpRows } from './FollowUpList'
import { followUpWhen } from './followUps'

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
const save = () => Promise.resolve()

describe('FollowUpOffer', () => {
  it('offers the date read from the note, quoting the phrase', () => {
    const html = renderToStaticMarkup(
      <FollowUpOffer
        suggestions={[{ due_date: '2027-02-01', phrase: 'Anfang Februar' }]}
        fallbackDate="2026-11-24"
        noteText="Anfang Februar melden"
        onConfirm={noop}
        onSave={save}
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
        fallbackDate="2026-11-24"
        noteText="Anfang Februar melden"
        onConfirm={noop}
        onSave={save}
        onDismiss={noop}
      />,
    )
    expect(html).toContain(fmtDate(new Date(2026, 11, 15)))
    expect(html).toContain('Mitte Dezember')
  })

  it('offers to pick another date even when the note names one (ELI-48)', () => {
    const html = renderToStaticMarkup(
      <FollowUpOffer
        suggestions={[{ due_date: '2027-02-01', phrase: 'Anfang Februar' }]}
        fallbackDate="2026-11-24"
        noteText="Anfang Februar melden"
        onConfirm={noop}
        onSave={save}
        onDismiss={noop}
      />,
    )
    expect(html).toContain(t('Anderes Datum…'))
  })

  it('still offers a Wiedervorlage when the note names no date (ELI-48)', () => {
    const html = renderToStaticMarkup(
      <FollowUpOffer
        suggestions={[]}
        fallbackDate="2026-11-24"
        noteText="grad gesprochen"
        onConfirm={noop}
        onSave={save}
        onDismiss={noop}
      />,
    )
    expect(html).toContain(t('Wiedervorlage erstellen?'))
    expect(html).toContain(t('Kein Datum in der Notiz — Vorschlag: {date}', { date: fmtDate(new Date(2026, 10, 24)) }))
    expect(html).toContain(t('Wiedervorlage erstellen'))
    expect(html).toContain(t('Verwerfen'))
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

// ELI-63: "20.11.2026 10:00Doris Böhner" — the time ran into the name.
/** Runs `fn` in one language and puts the previous one back — the runner's
 *  own language comes from its locale, so neither may be assumed. */
function inLang<T>(lang: 'de' | 'en', fn: () => T): T {
  const before = getLang()
  setLang(lang)
  try {
    return fn()
  } finally {
    setLang(before)
  }
}

describe('followUpWhen — a time only when one was set (ELI-63)', () => {
  it('a follow-up saved without a time shows only its date', () => {
    expect(inLang('de', () => followUpWhen({ due_date: '2026-11-20', due_time: null }))).toEqual({ date: '20.11.2026', time: null })
  })

  it('a time somebody set shows as HH:MM', () => {
    expect(inLang('de', () => followUpWhen({ due_date: '2026-11-20', due_time: '10:00:00' }))).toEqual({ date: '20.11.2026', time: '10:00' })
  })

  it('formats the date the English way too', () => {
    expect(inLang('en', () => followUpWhen({ due_date: '2026-11-20', due_time: '09:30:00' }))).toEqual({
      date: '20/11/2026',
      time: '09:30',
    })
  })
})

describe('FollowUpRows — the date cell (ELI-63)', () => {
  const render = (due_time: string | null) =>
    inLang('de', () =>
      renderToStaticMarkup(
        <FollowUpRows rows={[row({ due_date: '2026-11-20', due_time })]} today="2026-11-17" showPerson onDone={noop} onCalendar={noop} />,
      ),
    )

  it('renders no time for a follow-up without one', () => {
    const html = render(null)
    expect(html).toContain('20.11.2026')
    expect(html).not.toMatch(/\d\d:\d\d/)
  })

  it('renders date and time as separate pieces that can wrap, never one run-on string', () => {
    const html = render('10:00:00')
    expect(html).toContain('>20.11.2026<')
    expect(html).toContain('>10:00<')
    expect(html).not.toContain('20.11.202610:00')
  })

  it('gives the cell a width that holds "20.11.2026 10:00" and lets it stack when narrow', () => {
    const html = render('10:00:00')
    const cell = html.match(/<span class="([^"]*)" data-testid="follow-up-when"/)
    expect(cell).not.toBeNull()
    // Wide enough for 16 mono characters at 13px (≈ 7.8rem) plus the gap…
    expect(cell![1]).toContain('sm:w-[8.75rem]')
    // …and stacked (time under the date) below the sm breakpoint.
    expect(cell![1]).toContain('flex-col')
    expect(cell![1]).toContain('sm:flex-row')
  })
})
