import { useEffect, useMemo, useState } from 'react'
import {
  ChevronUp,
  ChevronDown,
  ScanSearch,
  Mail,
  Phone,
  MapPin,
  User,
  Briefcase,
  ThumbsUp,
  Check,
  X,
  Target,
} from 'lucide-react'
import { Breadcrumb } from '@/components/Breadcrumb'
import { Avatar } from '@/components/ui/Avatar'
import { MatchStrengthBadge } from './MatchStrengthBadge'
import type { MatchStrength } from '@/data/types'
import { api } from '@/api/client'
import { toCandidate, toMatchReasons, overallStrength } from '@/api/adapters'
import { useAsync } from '@/hooks/useAsync'

const detailTabs = ['Erfahrung', 'Notizen', 'Chat', 'Dateien', 'Aufgaben']

const OVERALL_LABEL: Record<MatchStrength, string> = {
  'very-strong': 'Sehr starker Match',
  strong: 'Starker Match',
  moderate: 'Solider Match',
  weak: 'Schwacher Match',
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-line px-4 py-3">
      <div className="text-[13px] text-ink-muted">{label}</div>
      <div className="mt-1 text-lg font-bold tracking-tight text-ink">{value}</div>
    </div>
  )
}

function DetailRow({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex gap-3 py-2">
      <Icon className="mt-0.5 h-[18px] w-[18px] shrink-0 text-ink-faint" />
      <div className="grid flex-1 grid-cols-[128px_1fr] gap-3 text-[15px]">
        <span className="text-[13px] leading-tight text-ink-muted">{label}</span>
        <span className="text-ink">{children}</span>
      </div>
    </div>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-8 pt-[76px] text-center">
      {children}
    </div>
  )
}

export function MatchingView() {
  const { data: jobs, loading: jobsLoading } = useAsync(() => api.jobs(), [])
  const [jobId, setJobId] = useState<string | null>(null)
  useEffect(() => {
    if (jobs?.length && !jobId) setJobId(jobs[0].id)
  }, [jobs, jobId])

  // Rank the pool against the selected job (hard filters → soft ranking).
  const { data: match, loading: matchLoading } = useAsync(async () => {
    if (!jobId) return null
    const [results, cands] = await Promise.all([api.matchJob(jobId, true), api.candidates()])
    const byId = new Map(cands.map((c) => [c.id, c]))
    const ranked = results
      .filter((r) => r.passed_hard_filters)
      .map((r) => ({ result: r, dto: byId.get(r.candidate_id)! }))
      .filter((x) => x.dto)
    return { ranked, total: results.length, passed: results.filter((r) => r.passed_hard_filters).length }
  }, [jobId])

  const [index, setIndex] = useState(0)
  useEffect(() => setIndex(0), [jobId])

  const ranked = match?.ranked ?? []
  const current = ranked[index]
  const candidate = useMemo(() => (current ? toCandidate(current.dto) : null), [current])
  const reasons = current ? toMatchReasons(current.result.reasons) : []
  const strength: MatchStrength = current ? overallStrength(current.result) : 'strong'
  const move = (d: number) => setIndex((i) => Math.min(ranked.length - 1, Math.max(0, i + d)))

  // ── Empty / loading states ────────────────────────────────────────────────
  if (jobsLoading && !jobs) return <Centered><p className="text-[14px] text-ink-muted">Lädt…</p></Centered>
  if (!jobs?.length) {
    return (
      <Centered>
        <Target className="h-9 w-9 text-ink-faint" />
        <h2 className="text-[17px] font-semibold text-ink">Noch keine Jobs</h2>
        <p className="max-w-sm text-[14px] text-ink-muted">
          Matching rankt Ihren Kandidatenpool gegen eine offene Rolle. Legen Sie einen Job an,
          um zu starten.
        </p>
      </Centered>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden pt-[76px]">
      {/* Header: job picker + rank nav */}
      <div className="flex items-center justify-between gap-4 px-8 pt-6">
        <div className="flex items-center gap-3">
          <Breadcrumb items={['Start', 'Matching']} />
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 rounded-xl border border-line bg-white px-3 py-1.5 text-[14px]">
            <Target className="h-4 w-4 text-brand-500" />
            <span className="text-ink-muted">Rolle</span>
            <select
              value={jobId ?? ''}
              onChange={(e) => setJobId(e.target.value)}
              className="max-w-[280px] bg-transparent font-semibold text-ink outline-none"
            >
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title}
                </option>
              ))}
            </select>
          </label>
          {ranked.length > 0 && (
            <div className="flex items-center gap-2 text-ink-muted">
              <span className="text-[15px] tabular-nums">
                {index + 1} von {ranked.length}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => move(-1)}
                  disabled={index === 0}
                  className="rounded-lg border border-line p-1.5 hover:bg-slate-50 disabled:opacity-40"
                >
                  <ChevronUp className="h-4 w-4" />
                </button>
                <button
                  onClick={() => move(1)}
                  disabled={index >= ranked.length - 1}
                  className="rounded-lg border border-line p-1.5 hover:bg-slate-50 disabled:opacity-40"
                >
                  <ChevronDown className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {matchLoading && !match ? (
        <Centered><p className="text-[14px] text-ink-muted">Rangliste wird berechnet…</p></Centered>
      ) : !candidate ? (
        <Centered>
          <User className="h-9 w-9 text-ink-faint" />
          <h2 className="text-[17px] font-semibold text-ink">Kein passender Kandidat</h2>
          <p className="max-w-sm text-[14px] text-ink-muted">
            Kein Kandidat erfüllt die Muss-Kriterien dieser Rolle
            {match ? ` (0 von ${match.total} bestanden)` : ''}. Passen Sie die Kriterien an.
          </p>
        </Centered>
      ) : (
        <>
          {/* Candidate identity + tabs */}
          <div className="px-8 pt-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3.5">
                <Avatar initials={candidate.initials} tone={candidate.avatar} size="lg" />
                <h1 className="text-2xl font-bold tracking-tight text-ink">{candidate.name}</h1>
              </div>
              <button className="flex items-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-3.5 py-2 text-[14px] font-semibold text-sky-700 hover:bg-sky-100">
                <ScanSearch className="h-4 w-4" />
                Zur Prüfung
              </button>
            </div>

            <div className="mt-4 flex items-center gap-6 border-b border-line">
              {detailTabs.map((t, i) => (
                <button
                  key={t}
                  className={
                    i === 0
                      ? '-mb-px border-b-2 border-brand-500 pb-3 text-[15px] font-semibold text-ink'
                      : 'pb-3 text-[15px] text-ink-muted hover:text-ink-soft'
                  }
                >
                  {t}
                  {i === 0 && (
                    <span className="ml-2 rounded-md bg-slate-100 px-1.5 py-0.5 text-[12px] font-medium text-ink-muted">
                      {candidate.experience.length}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Body: details | why-matched */}
          <div className="grid flex-1 grid-cols-2 gap-8 overflow-hidden px-8 pb-4 pt-5">
            {/* LEFT — details */}
            <div className="overflow-y-auto pr-1">
              <h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink">
                <User className="h-[18px] w-[18px] text-brand-500" /> Details
              </h2>
              <div className="mt-2">
                <DetailRow icon={Mail} label="E-Mail">
                  <span className="font-medium text-brand-600">{candidate.email}</span>
                </DetailRow>
                <DetailRow icon={Phone} label="Telefon">
                  <span className="font-medium text-brand-600">{candidate.phone}</span>
                </DetailRow>
                <DetailRow icon={MapPin} label="Standort">
                  {candidate.location}
                </DetailRow>
                <DetailRow icon={User} label="KI-Zusammenfassung">
                  <span className="text-ink-soft">{candidate.aiSummary}</span>
                </DetailRow>
              </div>

              <h2 className="mt-6 flex items-center gap-2 text-[15px] font-semibold text-ink">
                <Briefcase className="h-[18px] w-[18px] text-brand-500" /> Berufserfahrung
              </h2>
              <div className="mt-3 grid grid-cols-3 gap-3">
                <StatCard label="Ø Verweildauer" value={candidate.stats.avgTenure} />
                <StatCard label="Aktuell" value={candidate.stats.current} />
                <StatCard label="Gesamt" value={candidate.stats.total} />
              </div>

              <div className="mt-4 space-y-3">
                {candidate.experience.map((e, i) => (
                  <div key={e.company + e.title + i} className="rounded-2xl border border-line p-4">
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-[11px] font-bold text-white">
                        {e.company.slice(0, 2).toUpperCase()}
                      </span>
                      <span className="font-semibold text-ink">{e.company}</span>
                    </div>
                    <div className="mt-2.5 font-semibold text-ink">{e.title}</div>
                    <div className="text-[14px] text-ink-muted">
                      {[e.period, e.location].filter(Boolean).join(' · ')}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* RIGHT — why we matched */}
            <div className="flex flex-col overflow-hidden rounded-2xl">
              <div className="flex items-center justify-between pb-1">
                <h2 className="text-[15px] font-semibold text-brand-700">Warum wir gematcht haben</h2>
                <span className="flex items-center gap-1.5 rounded-lg bg-brand-100 px-2.5 py-1 text-[13px] font-semibold text-brand-700">
                  <ThumbsUp className="h-3.5 w-3.5" /> {OVERALL_LABEL[strength]}
                </span>
              </div>

              <div className="mt-2 flex-1 space-y-3 overflow-y-auto pr-1">
                {reasons.map((r, i) => (
                  <div key={r.title + i} className="rounded-2xl border border-line p-4">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-[15px] font-semibold leading-snug text-ink">{r.title}</h3>
                      <MatchStrengthBadge strength={r.strength} />
                    </div>
                    <p className="mt-2 text-[14px] leading-relaxed text-ink-soft">{r.detail}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Decision bar — advances to the next ranked candidate */}
          <div className="flex items-center gap-3 border-t border-line px-8 py-4">
            <button
              onClick={() => move(1)}
              className="flex items-center gap-2 rounded-xl bg-brand-500 px-6 py-2.5 text-[15px] font-semibold text-white shadow-sm hover:bg-brand-600"
            >
              <Check className="h-4 w-4" /> Annehmen
            </button>
            <button
              onClick={() => move(1)}
              className="flex items-center gap-2 rounded-xl border border-line px-6 py-2.5 text-[15px] font-semibold text-ink-soft hover:bg-slate-50"
            >
              <X className="h-4 w-4" /> Ablehnen
            </button>
          </div>
        </>
      )}
    </div>
  )
}
