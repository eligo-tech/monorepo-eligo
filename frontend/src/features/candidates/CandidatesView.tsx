import { Search, SlidersHorizontal, ChevronDown, ArrowDownUp } from 'lucide-react'
import { Breadcrumb } from '@/components/Breadcrumb'
import { Avatar } from '@/components/ui/Avatar'
import { SkillBadge, CountChip } from '@/components/ui/SkillBadge'
import { VerificationScore } from '@/components/ui/VerificationScore'
import { LinkedInMark } from '@/components/ui/LinkedInMark'
import { DataSourceBadge } from '@/components/ui/DataSourceBadge'
import { candidates as mockCandidates } from '@/data/candidates'
import { api } from '@/api/client'
import { toCandidate } from '@/api/adapters'
import { useAsync } from '@/hooks/useAsync'

function Toolbar() {
  return (
    <div className="flex items-center gap-3">
      <div className="flex flex-1 items-center gap-2.5 rounded-xl border border-line bg-white px-3.5 py-2.5 text-[15px] text-ink-faint">
        <Search className="h-[18px] w-[18px]" />
        <span>Kandidaten, Stichworte, Notizen…</span>
      </div>
      <button className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2.5 text-[14px] text-ink-soft hover:bg-slate-50">
        <ArrowDownUp className="h-4 w-4 text-ink-muted" />
        Sortiert nach <span className="font-semibold text-ink">Letzte Aktivität</span>
      </button>
      <button className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2.5 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
        <SlidersHorizontal className="h-4 w-4 text-ink-muted" />
        Filter
      </button>
    </div>
  )
}

const columns = ['Name', 'E-Mail', 'Telefon', 'Erfahrung', 'Skills', 'Verifizierung']

export function CandidatesView() {
  const { data, loading } = useAsync(() => api.candidates(), [])
  const source = loading ? 'loading' : data ? 'live' : 'demo'
  const rows = data ? data.map(toCandidate) : mockCandidates

  return (
    <div className="flex h-full flex-col overflow-hidden pt-[76px]">
      {/* Header */}
      <div className="flex items-center justify-between px-8 pt-6">
        <div className="flex items-center gap-3">
          <Breadcrumb items={['Start', 'Kandidaten']} count={rows.length} />
          <DataSourceBadge state={source} />
        </div>
        <div className="flex items-center gap-2.5">
          <button className="flex items-center gap-1.5 rounded-xl border border-line px-3.5 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
            Standard <ChevronDown className="h-4 w-4" />
          </button>
          <button className="rounded-xl border border-line px-4 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
            Ansicht
          </button>
          <button className="rounded-xl border border-line px-4 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
            Import/Export
          </button>
          <button className="rounded-xl bg-ink px-4 py-2 text-[14px] font-semibold text-white hover:bg-ink-soft">
            + Kandidat
          </button>
        </div>
      </div>

      <div className="px-8 pt-5">
        <Toolbar />
      </div>

      {/* Table */}
      <div className="mt-2 flex-1 overflow-y-auto px-8 pb-8">
        <div className="grid grid-cols-[1.6fr_1.6fr_1fr_1.4fr_1.1fr_0.8fr] gap-4 border-b border-line px-2 py-3 text-[13px] font-medium text-ink-muted">
          {columns.map((c) => (
            <div key={c}>{c}</div>
          ))}
        </div>

        {rows.map((c) => (
          <div
            key={c.id}
            className="grid grid-cols-[1.6fr_1.6fr_1fr_1.4fr_1.1fr_0.8fr] items-center gap-4 border-b border-line px-2 py-4 transition-colors hover:bg-slate-50/60"
          >
            {/* Name */}
            <div className="flex items-center gap-3">
              <Avatar initials={c.initials} tone={c.avatar} />
              <span className="font-semibold leading-tight text-ink">{c.name}</span>
              {c.linkedin && <LinkedInMark />}
            </div>

            {/* Email */}
            <a className="truncate text-[15px] font-medium text-brand-600" href={`mailto:${c.email}`}>
              {c.email}
            </a>

            {/* Phone */}
            <div className="text-[15px] text-ink-soft">{c.phone}</div>

            {/* Experience */}
            <div className="text-[14px] leading-snug">
              <div className="font-semibold text-ink">{c.currentTitle}</div>
              <div className="text-ink-muted">
                {c.currentCompany} ({c.tenure}){' '}
                {c.extraRoles > 0 && <CountChip n={c.extraRoles} />}
              </div>
            </div>

            {/* Skills */}
            <div className="flex flex-wrap items-center gap-1.5">
              {c.skills.map((s) => (
                <SkillBadge key={s.label} label={s.label} tone={s.tone} />
              ))}
              {c.extraSkills > 0 && <CountChip n={c.extraSkills} />}
            </div>

            {/* Verification */}
            <div>
              <VerificationScore value={c.verification} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}