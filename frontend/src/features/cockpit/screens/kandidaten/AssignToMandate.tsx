// "Zu Mandat zuordnen" — the step between knowing a person and running a
// process with them.
//
// It did not exist. A candidate could be created, parsed, enriched and
// searched, and there was no way in the product to put them on a mandate —
// the only path was a POST to /pipeline/applications by hand. So the chain
// the recruiter actually walks (Manager → Mandat → Gespräch → Prozess) broke
// exactly where the work starts.
//
// Several mandates at once is the normal case, not an edge one: a senior
// backend developer is a candidate for three open searches, and deciding
// which one to present them on is the recruiter's job, not a limitation of
// the form.

import { useMemo, useState } from 'react'
import { Check, Plus, Search, X } from 'lucide-react'

import { api } from '@/api/client'
import type { CompanyDTO, JobDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { searchScore } from '@/lib/search'

export function AssignToMandate({
  candidateId,
  assignedJobIds,
  onAssigned,
}: {
  candidateId: string
  /** Mandates this candidate already runs on — offered as "bereits zugeordnet"
   *  rather than hidden, so the list answers "where is she already?" too. */
  assignedJobIds: string[]
  onAssigned?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<string[]>([])

  const jobs = useAsync<JobDTO[]>(
    () => (open ? api.jobs().catch(() => []) : Promise.resolve([])),
    [open],
  )
  const companies = useAsync<CompanyDTO[]>(
    () => (open ? api.companies().catch(() => []) : Promise.resolve([])),
    [open],
  )

  const companyName = useMemo(() => {
    const byId = new Map((companies.data ?? []).map((c) => [c.id, c.name]))
    return (id: string | null) => (id ? (byId.get(id) ?? '') : '')
  }, [companies.data])

  // Open mandates first: you assign to a search that is running. Closed ones
  // stay reachable through the search box rather than vanishing.
  const rows = useMemo(() => {
    const all = jobs.data ?? []
    const scored = all
      .map((job) => ({
        job,
        score: searchScore(
          [
            { text: job.title, weight: 3 },
            { text: companyName(job.client_company_id), weight: 3 },
            { text: job.location ?? '', weight: 2 },
          ],
          query,
        ),
      }))
      .filter((r) => r.score > 0)
    if (query.trim()) scored.sort((a, b) => b.score - a.score)
    else
      scored.sort(
        (a, b) =>
          Number(b.job.status === 'open') - Number(a.job.status === 'open') ||
          a.job.title.localeCompare(b.job.title, 'de'),
      )
    return scored.map((r) => r.job).slice(0, 40)
  }, [jobs.data, companyName, query])

  async function assign(job: JobDTO) {
    setBusy(job.id)
    try {
      await api.assignToJob(candidateId, job.id)
      setDone((prev) => [...prev, job.id])
      onAssigned?.()
    } finally {
      setBusy(null)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-xl border border-cockpit-line px-3.5 py-2 text-[13px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-mint-300"
      >
        <Plus className="h-4 w-4" /> Zu Mandat zuordnen
      </button>
    )
  }

  return (
    <div className="absolute right-6 top-20 z-50 w-[26rem] rounded-xl border border-cockpit-line bg-cockpit-surface p-3 shadow-panel">
      <div className="mb-2 flex items-center gap-2">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          Zu Mandat zuordnen
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Schließen"
          className="ml-auto text-cockpit-faint transition-colors hover:text-cockpit-text"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <label className="mb-2 flex items-center gap-2 rounded-lg border border-cockpit-line bg-cockpit-inset px-2.5 py-1.5 focus-within:border-cockpit-edge">
        <Search className="h-4 w-4 shrink-0 text-cockpit-faint" />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Mandat, Firma oder Ort — Tippfehler erlaubt"
          className="w-full bg-transparent text-[13px] text-cockpit-text placeholder:text-cockpit-faint focus:outline-none"
        />
      </label>

      <div className="max-h-72 space-y-0.5 overflow-y-auto">
        {jobs.loading && (
          <p className="px-2 py-3 font-mono text-[12px] text-cockpit-faint">lädt…</p>
        )}
        {!jobs.loading && rows.length === 0 && (
          <p className="px-2 py-3 text-[13px] text-cockpit-faint">
            Kein Mandat passt zu „{query}“.
          </p>
        )}
        {rows.map((job) => {
          const already = assignedJobIds.includes(job.id) || done.includes(job.id)
          return (
            <button
              key={job.id}
              type="button"
              disabled={already || busy !== null}
              onClick={() => void assign(job)}
              className={cn(
                'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors',
                already
                  ? 'cursor-default text-cockpit-faint'
                  : 'text-cockpit-dim hover:bg-white/[0.04] hover:text-cockpit-text',
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px]">{job.title}</span>
                <span className="block truncate text-[11.5px] text-cockpit-faint">
                  {companyName(job.client_company_id) || '—'}
                  {job.location ? ` · ${job.location}` : ''}
                  {job.status !== 'open' ? ` · ${job.status}` : ''}
                </span>
              </span>
              {already ? (
                <span className="flex shrink-0 items-center gap-1 font-mono text-[11px] text-mint-400">
                  <Check className="h-3.5 w-3.5" /> zugeordnet
                </span>
              ) : (
                <span className="shrink-0 font-mono text-[11px] text-cockpit-faint">
                  {busy === job.id ? 'ordnet zu…' : '+'}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
