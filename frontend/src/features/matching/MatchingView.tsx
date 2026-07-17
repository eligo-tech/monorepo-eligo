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
} from 'lucide-react'
import { Breadcrumb } from '@/components/Breadcrumb'
import { Avatar } from '@/components/ui/Avatar'
import { DataSourceBadge } from '@/components/ui/DataSourceBadge'
import { MatchStrengthBadge } from './MatchStrengthBadge'
import { candidates, marieMatchReasons } from '@/data/candidates'
import type { MatchStrength } from '@/data/types'
import { api } from '@/api/client'
import { toCandidate, toMatchReasons, overallStrength } from '@/api/adapters'
import { useAsync } from '@/hooks/useAsync'

const marie = candidates.find((c) => c.id === 'c-marie')!
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

export function MatchingView() {
  const { data, loading } = useAsync(async () => {
    const jobs = await api.jobs()
    if (!jobs.length) throw new Error('no jobs')
    const [results, cands] = await Promise.all([
      api.matchJob(jobs[0].id, true),
      api.candidates(),
    ])
    const byId = new Map(cands.map((c) => [c.id, c]))
    const top = results.find((r) => r.passed_hard_filters) ?? results[0]
    const dto = top && byId.get(top.candidate_id)
    if (!top || !dto) throw new Error('no match')
    return {
      candidate: toCandidate(dto),
      reasons: toMatchReasons(top.reasons),
      strength: overallStrength(top),
      count: results.length,
    }
  }, [])

  const source = loading ? 'loading' : data ? 'live' : 'demo'
  const candidate = data?.candidate ?? marie
  const reasons = data?.reasons ?? marieMatchReasons
  const strength: MatchStrength = data?.strength ?? 'strong'
  const total = data?.count ?? 65

  return (
    <div className="flex h-full flex-col overflow-hidden pt-[76px]">
      {/* Header */}
      <div className="flex items-center justify-between px-8 pt-6">
        <div className="flex items-center gap-3">
          <Breadcrumb items={['Start', 'Kandidaten', candidate.name]} />
          <DataSourceBadge state={source} />
        </div>
        <div className="flex items-center gap-3 text-ink-muted">
          <span className="text-[15px]">1 von {total}</span>
          <div className="flex items-center gap-1">
            <button className="rounded-lg border border-line p-1.5 hover:bg-slate-50">
              <ChevronUp className="h-4 w-4" />
            </button>
            <button className="rounded-lg border border-line p-1.5 hover:bg-slate-50">
              <ChevronDown className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

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
            {candidate.experience.map((e) => (
              <div key={e.company + e.title} className="rounded-2xl border border-line p-4">
                <div className="flex items-center gap-2.5">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-[11px] font-bold text-white">
                    {e.company.slice(0, 2).toUpperCase()}
                  </span>
                  <span className="font-semibold text-ink">{e.company}</span>
                </div>
                <div className="mt-2.5 font-semibold text-ink">{e.title}</div>
                <div className="text-[14px] text-ink-muted">
                  {e.period} · {e.location}
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
            {reasons.map((r) => (
              <div key={r.title} className="rounded-2xl border border-line p-4">
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

      {/* Decision bar */}
      <div className="flex items-center gap-3 border-t border-line px-8 py-4">
        <button className="flex items-center gap-2 rounded-xl bg-brand-500 px-6 py-2.5 text-[15px] font-semibold text-white shadow-sm hover:bg-brand-600">
          <Check className="h-4 w-4" /> Annehmen
        </button>
        <button className="flex items-center gap-2 rounded-xl border border-line px-6 py-2.5 text-[15px] font-semibold text-ink-soft hover:bg-slate-50">
          <X className="h-4 w-4" /> Ablehnen
        </button>
      </div>
    </div>
  )
}