// "Jobs" — the client mandates. Live from /jobs.
//
// A Job here is a MANDATE: a role a client asked us to fill, which drives the
// deterministic hard filters in matching and the pipeline. It is not the same
// thing as a market posting in the Markt corpus — that distinction is what
// keeps scraped market noise out of the matcher (ARCHITECTURE.md, §1).

import { useMemo, useState } from 'react'
import {
  ArrowUpRight,
  Briefcase,
  MapPin,
  Pencil,
  Search,
  Wallet,
  X,
} from 'lucide-react'
import { api } from '@/api/client'
import type { CompanyDTO, JobDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { searchScore } from '@/lib/search'
import { Button } from '../ui/forms'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import { MandateEditor } from './MandateEditor'



const GRID =
  'grid-cols-[1.5rem_minmax(0,2.5fr)_minmax(0,1.5fr)_minmax(0,1.1fr)_minmax(0,1.3fr)_7rem_2rem]'
const COLUMNS = ['', 'Titel', 'Firma', 'Ort', 'Gehaltsband', 'Status', '']

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

const STATUS_FILTERS = [
  { value: '', label: 'Alle' },
  { value: 'open', label: 'Offen' },
  { value: 'on_hold', label: 'Pausiert' },
  { value: 'filled', label: 'Besetzt' },
  { value: 'cancelled', label: 'Abgesagt' },
]

const mandateRef = (id: string) => `#A-${id.slice(0, 4)}`

export function JobsScreen({
  query = '',
  onClearQuery,
}: {
  /** The command bar's term. It used to go nowhere — the box looked like a
   *  search and filtered nothing. */
  query?: string
  onClearQuery?: () => void
}) {
  const jobs = useAsync<JobDTO[]>(() => api.jobs(), [])
  const companies = useAsync<CompanyDTO[]>(() => api.companies(), [])

  const companyName = useMemo(() => {
    const byId = new Map((companies.data ?? []).map((c) => [c.id, c.name]))
    return (id: string | null) => (id ? (byId.get(id) ?? '—') : '—')
  }, [companies.data])

  const [editing, setEditing] = useState<JobDTO | null>(null)
  // Which mandates to take to the cockpit. One opens its workspace, several
  // open the overall view narrowed to them — a shortlist of searches to work
  // through, which is what "select several jobs" is for.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Saved mandates are overlaid locally: `useAsync` has no refetch, and
  // re-mounting the screen to see your own edit reads as a bug.
  const [saved, setSaved] = useState<Record<string, JobDTO>>({})

  const [filter, setFilter] = useState('')
  const [status, setStatus] = useState('')
  // 63 of 76 mandates carry no Muss-Kriterien, which makes the matcher's
  // deterministic half a no-op for most of the book. Not visible from a
  // list of titles, so it gets its own lens.
  const [onlyUnfiltered, setOnlyUnfiltered] = useState(false)

  const all = (jobs.data ?? []).map((j) => saved[j.id] ?? j)

  // Both boxes apply. The command bar's query is shown as a removable chip
  // so a term typed on another screen cannot silently empty this list.
  //
  // Scored, not merely matched: "Softwre" still finds GE Software, and the
  // closest mandate comes first instead of whatever the alphabet decided.
  const term = [filter, query].filter(Boolean).join(' ')

  const rows = useMemo(() => {
    const scored = all
      .filter((job) => !status || job.status === status)
      .filter((job) => !onlyUnfiltered || (job.must_have_skills ?? []).length === 0)
      .map((job) => ({
        job,
        score: searchScore(
          [
            { text: job.title, weight: 3 },
            { text: companyName(job.client_company_id), weight: 3 },
            { text: job.location ?? '', weight: 2 },
            { text: mandateRef(job.id), weight: 2 },
            { text: job.status, weight: 1 },
          ],
          term,
        ),
      }))
      .filter((r) => r.score > 0)
    if (term) scored.sort((a, b) => b.score - a.score)
    return scored.map((r) => r.job)
  }, [all, companyName, status, term])

  // Counted over the filtered list: "2 von 10 Mandaten · 6 offen" would read
  // as if the filter had kept six of them.
  const open = rows.filter((j) => j.status === 'open').length
  const withoutCriteria = all.filter(
    (j) => (j.must_have_skills ?? []).length === 0,
  ).length

  const reset = () => {
    setFilter('')
    setStatus('')
    onClearQuery?.()
  }

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

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex min-w-[16rem] flex-1 items-center gap-2.5 rounded-lg border border-cockpit-line bg-cockpit-inset px-3 focus-within:border-cockpit-edge">
            <Search className="h-4 w-4 shrink-0 text-cockpit-faint" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Mandat, Firma, Ort oder #A-Nummer — Tippfehler erlaubt"
              className="w-full bg-transparent py-2 text-[14px] text-cockpit-text placeholder:text-cockpit-faint focus:outline-none"
            />
            {filter && (
              <button
                type="button"
                onClick={() => setFilter('')}
                aria-label="Suche leeren"
                className="text-cockpit-faint transition-colors hover:text-cockpit-text"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </label>

          <button
            type="button"
            onClick={() => setOnlyUnfiltered((v) => !v)}
            aria-pressed={onlyUnfiltered}
            title="Mandate ohne Muss-Kriterien — das Matching filtert bei ihnen nicht, es sortiert nur"
            className={cn(
              'rounded-lg border px-2.5 py-1.5 font-mono text-[12px] transition-colors',
              onlyUnfiltered
                ? 'border-gold-600 bg-gold-500/10 text-gold-300'
                : 'border-cockpit-line text-cockpit-faint hover:text-cockpit-dim',
            )}
          >
            ohne Muss-Kriterien {withoutCriteria}
          </button>

          <div className="flex flex-wrap gap-1.5">
            {STATUS_FILTERS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setStatus(option.value)}
                aria-pressed={status === option.value}
                className={cn(
                  'rounded-lg border px-2.5 py-1.5 font-mono text-[12px] transition-colors',
                  status === option.value
                    ? 'border-cockpit-edge bg-white/[0.06] text-cockpit-text'
                    : 'border-cockpit-line text-cockpit-faint hover:text-cockpit-dim',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 font-mono text-[13px] text-cockpit-faint">
          <span>
            <span className="text-cockpit-text">{rows.length}</span>
            {rows.length === all.length ? ' Mandate' : ` von ${all.length} Mandaten`}
          </span>
          <span>
            <span className="text-cockpit-text">{open}</span> offen
          </span>
          {term && rows.length > 1 && <span>nach Relevanz sortiert</span>}
          {query && (
            <span className="flex items-center gap-1.5 rounded-md border border-gold-600/45 px-2 py-0.5 text-gold-300">
              Suche oben: „{query}“
              {onClearQuery && (
                <button
                  type="button"
                  onClick={onClearQuery}
                  aria-label="Suche oben leeren"
                  className="transition-colors hover:text-cockpit-text"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </span>
          )}
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

        {!jobs.loading && !jobs.error && rows.length === 0 && all.length > 0 && (
          <Panel className="p-6">
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-[14px] text-cockpit-dim">
                Kein Mandat passt zu dieser Suche.
              </p>
              <button
                type="button"
                onClick={reset}
                className="font-mono text-[12px] text-mint-300 transition-colors hover:text-cockpit-text"
              >
                Filter zurücksetzen
              </button>
            </div>
          </Panel>
        )}

        {!jobs.loading && !jobs.error && all.length === 0 && (
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
            {/* The cockpit link used to sit in every row, which made 76 rows
                shout the same word. It belongs here: tick what you want to
                look at, then go once. */}
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-[13px] text-cockpit-dim">
                <input
                  type="checkbox"
                  className="h-[15px] w-[15px] accent-[#a9d6b4]"
                  checked={selected.size > 0 && selected.size === rows.length}
                  ref={(el) => {
                    if (el) {
                      el.indeterminate =
                        selected.size > 0 && selected.size < rows.length
                    }
                  }}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked ? new Set(rows.map((j) => j.id)) : new Set(),
                    )
                  }
                />
                {selected.size > 0 ? `${selected.size} ausgewählt` : 'Alle wählen'}
              </label>

              <Button
                tone="primary"
                disabled={selected.size === 0}
                onClick={() => {
                  window.location.hash = `cockpit/${[...selected].join(',')}`
                }}
                title={
                  selected.size === 0
                    ? 'Erst ein Mandat auswählen'
                    : selected.size === 1
                      ? 'Dieses Mandat im Cockpit öffnen'
                      : `${selected.size} Mandate im Cockpit öffnen`
                }
              >
                Im Cockpit öffnen <ArrowUpRight className="h-4 w-4" />
              </Button>

              {selected.size > 0 && (
                <button
                  type="button"
                  onClick={() => setSelected(new Set())}
                  className="font-mono text-[12px] text-cockpit-faint transition-colors hover:text-cockpit-text"
                >
                  Auswahl aufheben
                </button>
              )}
            </div>

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
                <input
                  type="checkbox"
                  aria-label={`${job.title} auswählen`}
                  className="h-[15px] w-[15px] accent-[#a9d6b4]"
                  checked={selected.has(job.id)}
                  onChange={(e) =>
                    setSelected((prev) => {
                      const next = new Set(prev)
                      if (e.target.checked) next.add(job.id)
                      else next.delete(job.id)
                      return next
                    })
                  }
                />
                {/* Still a link: a title that opens the thing is invisible
                    chrome, unlike a button repeated seventy-six times. */}
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
                <span className="flex items-center gap-1.5">
                  <Chip tone={STATUS_TONE[job.status]}>{job.status}</Chip>
                  {/* The matcher cannot filter on what is not recorded, and
                      a ranked list that was never filtered looks exactly
                      like one that was. */}
                  {(job.must_have_skills ?? []).length === 0 && (
                    <span
                      title="Keine Muss-Kriterien — das Matching sortiert nur, es filtert nicht"
                      className="cursor-help font-mono text-[11px] text-gold-400"
                    >
                      ungefiltert
                    </span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={() => setEditing(job)}
                  title="Mandat bearbeiten"
                  aria-label={`${job.title} bearbeiten`}
                  className="justify-self-end p-1 text-cockpit-faint transition-colors hover:text-mint-300"
                >
                  <Pencil className="h-4 w-4" />
                </button>
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
