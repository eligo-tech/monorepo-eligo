// Wiedervorlagen as a list (ELI-44): overdue in red, today, then upcoming —
// each with one-click "Erledigt" and a calendar file. Presentational only:
// the cockpit and a person's page fetch, this renders.

import { t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'

import { CalendarDays, Check, Pencil, Trash2 } from 'lucide-react'

import type { FollowUpDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { bucketFollowUps, parseLocalDate, personHref, shortTime } from './followUps'

const KIND_LABEL: Record<FollowUpDTO['subject_kind'], string> = {
  lead: t('Lead'),
  manager: t('Manager'),
  candidate: t('Kandidat'),
}

export function FollowUpRows({
  rows,
  today,
  showPerson,
  onDone,
  onCalendar,
  onEdit,
  onDelete,
  busyId,
  limitUpcoming,
}: {
  rows: readonly FollowUpDTO[]
  /** The recruiter's calendar day, `YYYY-MM-DD`. */
  today: string
  /** On the cockpit every row names its person; on their own page it would
   *  only repeat the heading. */
  showPerson?: boolean
  onDone: (row: FollowUpDTO) => void
  onCalendar: (row: FollowUpDTO) => void
  onEdit?: (row: FollowUpDTO) => void
  onDelete?: (row: FollowUpDTO) => void
  busyId?: string | null
  /** Upcoming rows shown at most; overdue and today are never cut. */
  limitUpcoming?: number
}) {
  const b = bucketFollowUps(rows, today)
  const upcoming = limitUpcoming === undefined ? b.upcoming : b.upcoming.slice(0, limitUpcoming)
  const groups = [
    { key: 'overdue', title: t('Überfällig'), list: b.overdue, tone: 'text-coral-400', total: b.overdue.length },
    { key: 'today', title: t('Heute'), list: b.today, tone: 'text-gold-400', total: b.today.length },
    { key: 'upcoming', title: t('Demnächst'), list: upcoming, tone: 'text-cockpit-dim', total: b.upcoming.length },
  ]
  return (
    <div className="space-y-3">
      {groups.map((g) =>
        g.list.length === 0 ? null : (
          <section key={g.key}>
            <p className={cn('pb-1 font-mono text-[11px] uppercase tracking-[0.12em]', g.tone)}>
              {g.title} · {g.total}
            </p>
            <ul>
              {g.list.map((row) => (
                <li
                  key={row.id}
                  className={cn(
                    'flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-cockpit-line/50 py-2.5 last:border-0',
                    g.key === 'overdue' && 'bg-coral-800/10',
                  )}
                >
                  <span className={cn('w-[6.5rem] shrink-0 font-mono text-[13px]', g.tone)}>
                    {fmtDate(parseLocalDate(row.due_date))}
                    {row.due_time && <span className="ml-1 text-cockpit-faint">{shortTime(row.due_time)}</span>}
                  </span>
                  {showPerson && (
                    <a href={personHref(row)} className="min-w-[10rem] text-[14px] font-medium text-cockpit-text hover:text-mint-400">
                      {row.person_name}
                      <span className="ml-2 font-mono text-[11px] font-normal text-cockpit-faint">
                        {KIND_LABEL[row.subject_kind]}
                        {row.company_name ? ` · ${row.company_name}` : ''}
                      </span>
                    </a>
                  )}
                  <span className="min-w-0 flex-1 text-[13.5px] text-cockpit-dim">{row.text}</span>
                  <span className="ml-auto flex shrink-0 items-center gap-3 font-mono text-[12px]">
                    <button
                      type="button"
                      onClick={() => onCalendar(row)}
                      title={t('Als .ics in den eigenen Kalender übernehmen')}
                      className="flex items-center gap-1 text-cockpit-faint hover:text-mint-400"
                    >
                      <CalendarDays className="h-3.5 w-3.5" />
                      {t('In Kalender')}
                    </button>
                    {onEdit && (
                      <button
                        type="button"
                        onClick={() => onEdit(row)}
                        aria-label={t('Bearbeiten')}
                        title={t('Bearbeiten')}
                        className="text-cockpit-faint hover:text-cockpit-text"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {onDelete && (
                      <button
                        type="button"
                        onClick={() => onDelete(row)}
                        aria-label={t('Löschen')}
                        title={t('Löschen')}
                        className="text-cockpit-faint hover:text-coral-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => onDone(row)}
                      disabled={busyId === row.id}
                      className="flex items-center gap-1 rounded-md border border-mint-700 px-2 py-0.5 text-mint-400 hover:bg-mint-800/40 disabled:opacity-40"
                    >
                      <Check className="h-3.5 w-3.5" />
                      {t('Erledigt')}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            {g.list.length < g.total && (
              <p className="pt-1 font-mono text-[11px] text-cockpit-faint">
                {t('+ {n} weitere', { n: String(g.total - g.list.length) })}
              </p>
            )}
          </section>
        ),
      )}
    </div>
  )
}
