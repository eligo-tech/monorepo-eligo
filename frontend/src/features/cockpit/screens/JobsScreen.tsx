// "Jobs" — the client mandates. Live from /jobs.
//
// A Job here is a MANDATE: a role a client asked us to fill, which drives the
// deterministic hard filters in matching and the pipeline. It is not the same
// thing as a market posting in the Markt corpus — that distinction is what
// keeps scraped market noise out of the matcher (ARCHITECTURE.md, §1).

import { useMemo, useState } from 'react'
import { ArrowUpRight, Briefcase, MapPin, Pencil, Wallet } from 'lucide-react'
import { api } from '@/api/client'
import type { CompanyDTO, JobDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import { MandateEditor } from './MandateEditor'



const GRID =
  'grid-cols-[minmax(0,2.4fr)_minmax(0,1.5fr)_minmax(0,1.1fr)_minmax(0,1.25fr)_7rem_auto]'
const COLUMNS = ['Titel', 'Firma', 'Ort', 'Gehaltsband', 'Status', '']

/** "85.000–95.000 €", or the honest gap. A mandate without a ceiling applies
 *  no salary filter at all, which is worth seeing at a glance. */
function band(job: JobDTO): string | null {
  const money = (v: number) => v.toLocaleString('de-DE')
  const symbol = (job.salary_currency || 'EUR') === 'EUR' ? '€' : job.salary_currency
  if (job.salary_min != null && job.salary_max != null) {
    return `${money(job.salary_min)}–${money(job.salary_max)} ${symbol}`
  }
  if (job.salary_max != null) return `bis ${money(job.salary_max)} ${symbol}`
  if (job.salary_min != null) return `ab ${money(job.salary_min)} ${symbol}`
  return null
}

const STATUS_TONE: Record<string, 'mint' | 'gold' | undefined> = {
  open: 'mint',
  on_hold: 'gold',
}

export function JobsScreen() {
  const jobs = useAsync<JobDTO[]>(() => api.jobs(), [])
  const companies = useAsync<CompanyDTO[]>(() => api.companies(), [])

  const companyName = useMemo(() => {
    const byId = new Map((companies.data ?? []).map((c) => [c.id, c.name]))
    return (id: string | null) => (id ? (byId.get(id) ?? '—') : '—')
  }, [companies.data])

  const [editing, setEditing] = useState<JobDTO | null>(null)
  // Saved mandates are overlaid locally: `useAsync` has no refetch, and
  // re-mounting the screen to see your own edit reads as a bug.
  const [saved, setSaved] = useState<Record<string, JobDTO>>({})

  const rows = (jobs.data ?? []).map((j) => saved[j.id] ?? j)
  const open = rows.filter((j) => j.status === 'open').length

  return (
    <div className="space-y-8">
      <header id="section-jobs" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Jobs
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          Die eigenen Mandate — Rollen, die ein Kunde besetzt haben möchte. Nicht zu
          verwechseln mit den Marktanzeigen unter „Markt“: nur ein Mandat steuert die
          harten Filter im Matching.
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          id="section-mandate"
          index="01"
          title="Mandate"
          hint={jobs.error ? 'offline' : 'live aus dem Datensatz'}
        />

        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 font-mono text-[13px] text-cockpit-faint">
          <span>
            <span className="text-cockpit-text">{rows.length}</span> Mandate
          </span>
          <span>
            <span className="text-cockpit-text">{open}</span> offen
          </span>
        </div>

        {jobs.loading && (
          <p className="font-mono text-[13px] text-cockpit-faint">lädt…</p>
        )}

        {jobs.error && (
          <Panel className="p-5">
            <p className="text-[14px] text-coral-400">
              Mandate konnten nicht geladen werden — ist die Sitzung noch gültig?
            </p>
          </Panel>
        )}

        {!jobs.loading && !jobs.error && rows.length === 0 && (
          <Panel className="p-6">
            <div className="flex items-start gap-3">
              <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
                <Briefcase className="h-5 w-5" />
              </span>
              <p className="text-[14px] leading-relaxed text-cockpit-dim">
                Noch keine Mandate erfasst.
              </p>
            </div>
          </Panel>
        )}

        {rows.length > 0 && (
          <div>
            <div
              className={cn(
                'grid gap-4 border-b border-cockpit-line px-3 pb-2.5',
                'font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint',
                GRID,
              )}
            >
              {COLUMNS.map((c) => (
                <div key={c}>{c}</div>
              ))}
            </div>

            {rows.map((job) => (
              <div
                key={job.id}
                className={cn(
                  'grid items-center gap-4 border-b border-cockpit-line/60 px-3 py-2.5',
                  GRID,
                )}
              >
                {/* The mandate opens in the cockpit's per-job view — the
                    list says a role exists, the cockpit says where it stands. */}
                <a
                  href={`#cockpit/${job.id}`}
                  title="Im Cockpit öffnen"
                  className="truncate text-[15px] text-cockpit-text underline-offset-2 transition-colors hover:text-mint-300 hover:underline"
                >
                  {job.title}
                </a>
                <span className="truncate text-[14px] text-cockpit-dim">
                  {companyName(job.client_company_id)}
                </span>
                <span className="flex min-w-0 items-center gap-1.5 font-mono text-[13px] text-cockpit-dim">
                  {job.location && (
                    <MapPin className="h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
                  )}
                  <span className="truncate">{job.location ?? '—'}</span>
                </span>
                <span className="flex min-w-0 items-center gap-1.5 font-mono text-[13px] text-cockpit-dim">
                  {band(job) ? (
                    <>
                      <Wallet className="h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
                      <span className="truncate">{band(job)}</span>
                    </>
                  ) : (
                    <span className="truncate text-cockpit-faint">kein Band</span>
                  )}
                </span>
                <span>
                  <Chip tone={STATUS_TONE[job.status]}>{job.status}</Chip>
                </span>
                <span className="flex items-center justify-end gap-1.5">
                  {/* The mandate's two doors: edit what is being searched
                      for, or open where the search stands. The title links
                      to the cockpit too, but a link in a table reads as
                      "detail page" — this says which cockpit view it is. */}
                  <a
                    href={`#cockpit/${job.id}`}
                    title="Dieses Mandat im Cockpit öffnen"
                    className="flex items-center gap-1.5 rounded-lg border border-cockpit-line px-2.5 py-1 font-mono text-[11.5px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-mint-300"
                  >
                    Cockpit <ArrowUpRight className="h-3.5 w-3.5" />
                  </a>
                  <button
                    type="button"
                    onClick={() => setEditing(job)}
                    title="Mandat bearbeiten"
                    aria-label={`${job.title} bearbeiten`}
                    className="p-1 text-cockpit-faint transition-colors hover:text-mint-300"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {editing && (
        <MandateEditor
          job={editing}
          companies={companies.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={(updated) =>
            setSaved((prev) => ({ ...prev, [updated.id]: updated }))
          }
        />
      )}
    </div>
  )
}
