// "Jobs" — the client mandates. Live from /jobs.
//
// A Job here is a MANDATE: a role a client asked us to fill, which drives the
// deterministic hard filters in matching and the pipeline. It is not the same
// thing as a market posting in the Markt corpus — that distinction is what
// keeps scraped market noise out of the matcher (ARCHITECTURE.md, §1).

import { useMemo } from 'react'
import { Briefcase, MapPin } from 'lucide-react'
import { api } from '@/api/client'
import type { CompanyDTO, JobDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { Chip, Panel, SectionHeader } from '../ui/primitives'



const GRID = 'grid-cols-[minmax(0,3fr)_minmax(0,1.8fr)_minmax(0,1.4fr)_7rem]'
const COLUMNS = ['Titel', 'Firma', 'Ort', 'Status']

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

  const rows = jobs.data ?? []
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
                <span className="truncate text-[15px] text-cockpit-text">{job.title}</span>
                <span className="truncate text-[14px] text-cockpit-dim">
                  {companyName(job.client_company_id)}
                </span>
                <span className="flex min-w-0 items-center gap-1.5 font-mono text-[13px] text-cockpit-dim">
                  {job.location && (
                    <MapPin className="h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
                  )}
                  <span className="truncate">{job.location ?? '—'}</span>
                </span>
                <span>
                  <Chip tone={STATUS_TONE[job.status]}>{job.status}</Chip>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
