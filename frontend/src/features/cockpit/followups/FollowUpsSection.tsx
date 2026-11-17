// "Wiedervorlagen" on the cockpit (ELI-44) — where the recruiter starts the
// day: every open follow-up of the workspace, overdue in red on top, then
// today, then what is coming. Each names and links its person; "Erledigt"
// takes it off. A follow-up stays here until somebody marks it done.

import { t } from '@/i18n'

import { useState } from 'react'
import { BellRing } from 'lucide-react'

import type { FollowUpDTO } from '@/api/types'
import { Panel, SectionHeader } from '../ui/primitives'
import { FollowUpRows } from '../ui/FollowUpList'
import { dueCount, localIsoDate } from '../ui/followUps'
import { completeFollowUp, downloadFollowUpIcs, useOpenFollowUps } from './useFollowUps'

/** Upcoming rows shown on the cockpit; overdue and today are never cut. */
const UPCOMING_SHOWN = 8

export function FollowUpsSection() {
  const { rows, failed } = useOpenFollowUps()
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const today = localIsoDate()
  const open = rows ?? []
  const due = dueCount(open, today)

  const done = async (row: FollowUpDTO) => {
    setBusyId(row.id)
    setError(null)
    try {
      await completeFollowUp(row)
    } catch {
      setError(t('Nicht gespeichert — bitte erneut versuchen.'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="space-y-5">
      <SectionHeader
        id="section-wiedervorlagen"
        title={t('Wiedervorlagen')}
        tone={due > 0 ? 'coral' : 'gold'}
        icon={<BellRing className="h-[15px] w-[15px]" />}
        hint={t('{due} fällig · {open} offen', { due: String(due), open: String(open.length) })}
      />
      <Panel className="px-6 py-5">
        {failed && <p className="text-[14px] text-coral-400">{t('Wiedervorlagen konnten nicht geladen werden.')}</p>}
        {rows === null && !failed && <p className="font-mono text-[13px] text-cockpit-faint">{t('lädt…')}</p>}
        {rows !== null && open.length === 0 && (
          <p className="text-[14px] text-cockpit-dim">
            {t('Keine offenen Wiedervorlagen. Legen Sie eine beim Lead, Manager oder Kandidaten an — oder bestätigen Sie den Vorschlag nach einer Notiz.')}
          </p>
        )}
        <FollowUpRows
          rows={open}
          today={today}
          showPerson
          busyId={busyId}
          limitUpcoming={UPCOMING_SHOWN}
          onDone={(row) => void done(row)}
          onCalendar={downloadFollowUpIcs}
        />
        {error && <p className="mt-2 text-[12px] text-coral-400">{error}</p>}
      </Panel>
    </section>
  )
}

/** The navigation badge: overdue plus due today. */
export function useDueFollowUpCount(): number {
  const { rows } = useOpenFollowUps()
  return dueCount(rows ?? [], localIsoDate())
}
