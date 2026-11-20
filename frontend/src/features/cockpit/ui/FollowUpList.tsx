// Wiedervorlagen as a list (ELI-44): overdue in red, today, then upcoming —
// each with one-click "Erledigt" and a calendar file. Presentational only:
// the cockpit and a person's page fetch, this renders.

import { t } from '@/i18n'

import { CalendarDays, Check, Pencil, Trash2 } from 'lucide-react'

import type { FollowUpDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { bucketFollowUps, followUpWhen, personHref } from './followUps'

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
                  <FollowUpWhen row={row} tone={g.tone} />
                  {showPerson && (
                    <a href={personHref(row)} className="min-w-[10rem] text-[14px] font-medium text-cockpit-text hover:text-mint-400">
                      {row.person_name}
                      <span className="ml-2 font-mono text-[11px] font-normal text-cockpit-faint">
                        {KIND_LABEL[row.subject_kind]}
                        {row.company_name ? ` · ${row.company_name}` : ''}
                      </span>
                    </a>
                  )}
                  {/* A floor, so on a phone the to-do takes its own line
                      rather than a one-word column beside the name. */}
                  <span className="min-w-[12rem] flex-1 text-[13.5px] text-cockpit-dim">{row.text}</span>
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

/** ELI-63: the date cell. One fixed width for every row so the names line
 *  up, wide enough for "20.11.2026 10:00" (16 mono characters at 13px ≈
 *  7.8rem) in either language — en-GB's "20/11/2026" is as long. It was
 *  6.5rem, so a time ran into the name. Below `sm` the time stacks under the
 *  date instead; the row's own gap keeps the name clear at every width. */
function FollowUpWhen({ row, tone }: { row: FollowUpDTO; tone: string }) {
  const when = followUpWhen(row)
  return (
    <span
      className={cn(
        'flex w-[5.75rem] shrink-0 flex-col font-mono text-[13px] leading-tight sm:w-[8.75rem] sm:flex-row sm:gap-x-1.5',
        tone,
      )}
      data-testid="follow-up-when"
    >
      <span>{when.date}</span>
      {when.time && <span className="text-cockpit-faint">{when.time}</span>}
    </span>
  )
}
