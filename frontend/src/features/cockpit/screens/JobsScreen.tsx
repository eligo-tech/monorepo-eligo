// "Jobs" — the client mandates. Live from /jobs.
//
// A Job here is a MANDATE: a role a client asked us to fill, which drives the
// deterministic hard filters in matching and the pipeline. It is not the same
// thing as a market posting in the Markt corpus — that distinction is what
// keeps scraped market noise out of the matcher (ARCHITECTURE.md, §1).

import { locale } from '@/i18n/format'

import { t } from '@/i18n'

import { useMemo, useState } from 'react'
import {
  Archive,
  ArrowUpRight,
  Briefcase,
  Copy,
  MapPin,
  Pencil,
  Plus,
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
import { NewMandate } from './NewMandate'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import {
  JOB_STATUSES,
  JOB_STATUS_TONE,
  isLive,
  jobStatus,
  jobStatusLabel,
} from '../ui/jobStatus'
import { MandateEditor } from './MandateEditor'



const GRID =
  'grid-cols-[1.5rem_minmax(0,2.5fr)_minmax(0,1.5fr)_minmax(0,1.1fr)_minmax(0,1.3fr)_15rem_3.5rem]'
const COLUMNS = ['', t('Titel'), t('Firma'), t('Ort'), t('Gehaltsband'), t('Status'), '']

/** "85.000–95.000 €", or the honest gap. A mandate without a ceiling applies
 *  no salary filter at all, which is worth seeing at a glance. */
function band(job: JobDTO): string | null {
  const money = (v: number) => v.toLocaleString(locale())
  const symbol = (job.salary_currency || 'EUR') === 'EUR' ? '€' : job.salary_currency
  if (job.salary_min != null && job.salary_max != null) {
    return `${money(job.salary_min)}–${money(job.salary_max)} ${symbol}`
  }
  if (job.salary_max != null) return `bis ${money(job.salary_max)} ${symbol}`
  if (job.salary_min != null) return `ab ${money(job.salary_min)} ${symbol}`
  return null
}

/** The status chip, and the one transition it can make.
 *
 *  It was a `<select>` with three options. ELI-7's second half makes `inaktiv`
 *  final — "kann nicht wieder geöffnet werden, muss neu angelegt werden" — and
 *  a select is a control whose entire grammar promises you can pick the other
 *  one back. The backend answers 409 to that; a dropdown offering it would be
 *  a button whose job is to fail.
 *
 *  So: a live mandate gets one action that asks first, and an inactive one
 *  gets a plain chip and the copy action beside it.
 *
 *  It writes through `PATCH /jobs/{id}`, which routes the change through the
 *  verification gate and leaves a receipt — the same path as editing the
 *  salary band, because this is the field that decides whether the mandate
 *  counts as live business.
 */
function StatusPicker({
  job,
  onChanged,
}: {
  job: JobDTO
  onChanged: (updated: JobDTO) => void
}) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  if (!isLive(job.status)) {
    return (
      <span
        title={t('Ein inaktives Mandat kann nicht wieder aktiviert werden — legen Sie es als Kopie neu an.')}
        className="cursor-help"
      >
        <Chip tone={JOB_STATUS_TONE[jobStatus(job.status)]}>
          {jobStatusLabel(job.status)}
        </Chip>
      </span>
    )
  }

  if (asking) {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap font-mono text-[11px]">
        <span className="text-gold-300">{t('endgültig?')}</span>
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            setFailed(false)
            try {
              onChanged(await api.updateJob(job.id, { status: 'inactive' }))
              setAsking(false)
            } catch {
              // The chip is driven by `job.status`, so a failed write simply
              // leaves the old value on screen. The ring says the click did
              // not take, instead of the list quietly disagreeing with the
              // database until the next reload.
              setFailed(true)
            } finally {
              setBusy(false)
            }
          }}
          className={cn(
            'rounded-md border border-coral-600/60 px-1.5 py-0.5 text-coral-300',
            'transition-colors hover:bg-coral-500/10',
            busy && 'opacity-60',
            failed && 'border-coral-400',
          )}
        >
          {busy ? t('speichert…') : t('ja, inaktiv')}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          className="text-cockpit-faint transition-colors hover:text-cockpit-text"
        >
          {t('abbrechen')}
        </button>
      </span>
    )
  }

  return (
    <Chip tone={JOB_STATUS_TONE[jobStatus(job.status)]} className="px-1.5 py-0">
      <button
        type="button"
        onClick={() => setAsking(true)}
        title={t('Mandat inaktiv setzen. Das ist endgültig — die Rolle wird später als Kopie neu angelegt.')}
        aria-label={`${job.title} — ${t('inaktiv setzen')}`}
        className="inline-flex cursor-pointer items-center gap-1 font-mono text-[12px] text-inherit"
      >
        {jobStatusLabel(job.status)}
        <Archive className="h-3 w-3 opacity-70" />
      </button>
    </Chip>
  )
}

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
  // Bumped after a mandate is created, so the list re-reads: `useAsync` has
  // no reload of its own, it re-runs when its deps change.
  const [reloadKey, setReloadKey] = useState(0)
  const jobs = useAsync<JobDTO[]>(() => api.jobs(), [reloadKey])
  const companies = useAsync<CompanyDTO[]>(() => api.companies(), [reloadKey])

  const companyName = useMemo(() => {
    const byId = new Map((companies.data ?? []).map((c) => [c.id, c.name]))
    return (id: string | null) => (id ? (byId.get(id) ?? '—') : '—')
  }, [companies.data])

  const [editing, setEditing] = useState<JobDTO | null>(null)
  // The first thing a new workspace needs, and the one thing it could not do:
  // nothing in the frontend called POST /jobs or POST /companies.
  const [creating, setCreating] = useState(false)
  // Which mandates to take to the cockpit. One opens its workspace, several
  // open the overall view narrowed to them — a shortlist of searches to work
  // through, which is what "select several jobs" is for.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Saved mandates are overlaid locally: `useAsync` has no refetch, and
  // re-mounting the screen to see your own edit reads as a bug.
  const [saved, setSaved] = useState<Record<string, JobDTO>>({})

  // "alte Jobs als Kopie wiederverwenden" (ELI-7) — and the only way back
  // from `inaktiv`, which the backend refuses to undo.
  const [copying, setCopying] = useState<string | null>(null)
  const [copyFailed, setCopyFailed] = useState(false)

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
      .filter((job) => !status || jobStatus(job.status) === status)
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
  //
  // "Running" rather than "open", because a mandate being actively worked is
  // the most open thing in the book and would otherwise fall out of the one
  // number on the screen that says how much business is live.
  const running = rows.filter((j) => isLive(j.status)).length
  const withoutCriteria = all.filter(
    (j) => (j.must_have_skills ?? []).length === 0,
  ).length

  /** Copy, then open the Suchprofil of the copy.
   *
   *  A mandate is copied in order to be changed — the role is nearly the same
   *  one, which is why it was worth copying — and the band and the
   *  Muss-Kriterien are hard filters. Landing in the editor is the difference
   *  between reusing a Suchprofil and inheriting one.
   */
  const copy = async (job: JobDTO) => {
    setCopying(job.id)
    setCopyFailed(false)
    try {
      const fresh = await api.copyJob(job.id)
      setReloadKey((k) => k + 1)
      setEditing(fresh)
    } catch {
      setCopyFailed(true)
    } finally {
      setCopying(null)
    }
  }

  const reset = () => {
    setFilter('')
    setStatus('')
    onClearQuery?.()
  }

  return (
    <div className="space-y-8">
      <header id="section-jobs" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          {t('Jobs')}
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          {t('Die eigenen Mandate — Rollen, die ein Kunde besetzt haben möchte. Nicht zu verwechseln mit den Marktanzeigen unter „Markt“: nur ein Mandat steuert die harten Filter im Matching.')}
        </p>
      </header>

      <section className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <SectionHeader
            id="section-mandate"
            index="01"
            title={t('Mandate')}
            hint={jobs.error ? 'offline' : t('live aus dem Datensatz')}
          />
          <Button tone="primary" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> {t('Neues Mandat')}
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex min-w-[16rem] flex-1 items-center gap-2.5 rounded-lg border border-cockpit-line bg-cockpit-inset px-3 focus-within:border-cockpit-edge">
            <Search className="h-4 w-4 shrink-0 text-cockpit-faint" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t('Mandat, Firma, Ort oder #A-Nummer — Tippfehler erlaubt')}
              className="w-full bg-transparent py-2 text-[14px] text-cockpit-text placeholder:text-cockpit-faint focus:outline-none"
            />
            {filter && (
              <button
                type="button"
                onClick={() => setFilter('')}
                aria-label={t('Suche leeren')}
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
            title={t('Mandate ohne Muss-Kriterien — das Matching filtert bei ihnen nicht, es sortiert nur')}
            className={cn(
              'rounded-lg border px-2.5 py-1.5 font-mono text-[12px] transition-colors',
              onlyUnfiltered
                ? 'border-gold-600 bg-gold-500/10 text-gold-300'
                : 'border-cockpit-line text-cockpit-faint hover:text-cockpit-dim',
            )}
          >
            {t('ohne Muss-Kriterien')} {withoutCriteria}
          </button>

          <div className="flex flex-wrap gap-1.5">
            {[{ value: '', label: t('Alle') }, ...JOB_STATUSES.map((v) => ({ value: v, label: jobStatusLabel(v) }))].map((option) => (
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
            {rows.length === all.length ? t(' Mandate') : t(' von {n} Mandaten', { n: all.length })}
          </span>
          <span>
            <span className="text-cockpit-text">{running}</span> {t('laufend')}
          </span>
          {copyFailed && (
            <span className="text-coral-400">
              {t('Kopie konnte nicht angelegt werden.')}
            </span>
          )}
          {term && rows.length > 1 && <span>{t('nach Relevanz sortiert')}</span>}
          {query && (
            <span className="flex items-center gap-1.5 rounded-md border border-gold-600/45 px-2 py-0.5 text-gold-300">
              {t('Suche oben: „{query}“', { query })}
              {onClearQuery && (
                <button
                  type="button"
                  onClick={onClearQuery}
                  aria-label={t('Suche oben leeren')}
                  className="transition-colors hover:text-cockpit-text"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </span>
          )}
        </div>

        {jobs.loading && (
          <p className="font-mono text-[13px] text-cockpit-faint">{t('lädt…')}</p>
        )}

        {jobs.error && (
          <Panel className="p-5">
            <p className="text-[14px] text-coral-400">
              {t('Mandate konnten nicht geladen werden — ist die Sitzung noch gültig?')}
            </p>
          </Panel>
        )}

        {!jobs.loading && !jobs.error && rows.length === 0 && all.length > 0 && (
          <Panel className="p-6">
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-[14px] text-cockpit-dim">
                {t('Kein Mandat passt zu dieser Suche.')}
              </p>
              <button
                type="button"
                onClick={reset}
                className="font-mono text-[12px] text-mint-300 transition-colors hover:text-cockpit-text"
              >
                {t('Filter zurücksetzen')}
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
                {t('Noch keine Mandate erfasst.')}
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
                {selected.size > 0 ? t('{n} ausgewählt', { n: selected.size }) : t('Alle wählen')}
              </label>

              <Button
                tone="primary"
                disabled={selected.size === 0}
                onClick={() => {
                  window.location.hash = `cockpit/${[...selected].join(',')}`
                }}
                title={
                  selected.size === 0
                    ? t('Erst ein Mandat auswählen')
                    : selected.size === 1
                      ? t('Dieses Mandat im Cockpit öffnen')
                      : t('{n} Mandate im Cockpit öffnen', { n: selected.size })
                }
              >
                {t('Im Cockpit öffnen')} <ArrowUpRight className="h-4 w-4" />
              </Button>

              {selected.size > 0 && (
                <button
                  type="button"
                  onClick={() => setSelected(new Set())}
                  className="font-mono text-[12px] text-cockpit-faint transition-colors hover:text-cockpit-text"
                >
                  {t('Auswahl aufheben')}
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
                  aria-label={t('{title} auswählen', { title: job.title })}
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
                  title={t('Im Cockpit öffnen')}
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
                    <span className="truncate text-cockpit-faint">{t('kein Band')}</span>
                  )}
                </span>
                <span className="flex items-center gap-1.5">
                  <StatusPicker
                    job={job}
                    onChanged={(updated) =>
                      setSaved((prev) => ({ ...prev, [updated.id]: updated }))
                    }
                  />
                  {/* The matcher cannot filter on what is not recorded, and
                      a ranked list that was never filtered looks exactly
                      like one that was. */}
                  {(job.must_have_skills ?? []).length === 0 && (
                    <span
                      title={t('Keine Muss-Kriterien — das Matching sortiert nur, es filtert nicht')}
                      className="cursor-help font-mono text-[11px] text-gold-400"
                    >
                      {t('ungefiltert')}
                    </span>
                  )}
                </span>
                <span className="flex justify-self-end">
                  <button
                    type="button"
                    disabled={copying === job.id}
                    onClick={() => void copy(job)}
                    title={t('Als neues Mandat kopieren — Suchprofil, Kunde und Ansprechpartner, ohne den Prozess')}
                    aria-label={`${job.title} kopieren`}
                    className={cn(
                      'p-1 text-cockpit-faint transition-colors hover:text-mint-300',
                      copying === job.id && 'opacity-50',
                    )}
                  >
                    <Copy className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditing(job)}
                    title={t('Mandat bearbeiten')}
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

      {creating && (
        <NewMandate
          onClose={() => setCreating(false)}
          onCreated={(jobId) => {
            setCreating(false)
            setReloadKey((k) => k + 1)
            // Straight into the mandate: the next thing after creating a
            // search is working it, not finding it again in the list.
            window.location.hash = `#cockpit/${jobId}`
          }}
        />
      )}

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
