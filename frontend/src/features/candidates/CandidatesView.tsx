import { useMemo, useState } from 'react'
import { Search, SlidersHorizontal, ArrowDownUp, X, Download } from 'lucide-react'
import { Breadcrumb } from '@/components/Breadcrumb'
import { CvUploadModal } from './CvUploadModal'
import { CandidateDossier } from './CandidateDossier'
import { Avatar } from '@/components/ui/Avatar'
import { SkillBadge, CountChip } from '@/components/ui/SkillBadge'
import { LinkedInMark } from '@/components/ui/LinkedInMark'
import { candidates as mockCandidates } from '@/data/candidates'
import type { Candidate } from '@/data/types'
import { api } from '@/api/client'
import { toCandidate } from '@/api/adapters'
import { useAsync } from '@/hooks/useAsync'

type SortKey = 'activity' | 'name' | 'verification'
const SORT_LABELS: Record<SortKey, string> = {
  activity: 'Letzte Aktivität',
  name: 'Name (A–Z)',
  verification: 'Verifizierung',
}
const SORT_ORDER: SortKey[] = ['activity', 'name', 'verification']

interface ToolbarProps {
  query: string
  onQuery: (v: string) => void
  sort: SortKey
  onCycleSort: () => void
}

function Toolbar({ query, onQuery, sort, onCycleSort }: ToolbarProps) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex flex-1 items-center gap-2.5 rounded-xl border border-line bg-white px-3.5 py-2.5 text-[15px] focus-within:border-brand-500">
        <Search className="h-[18px] w-[18px] text-ink-faint" />
        <input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Kandidaten, Stichworte, Notizen…"
          className="w-full bg-transparent text-ink outline-none placeholder:text-ink-faint"
        />
        {query && (
          <button
            onClick={() => onQuery('')}
            aria-label="Suche zurücksetzen"
            className="text-ink-faint hover:text-ink-muted"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <button
        onClick={onCycleSort}
        className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2.5 text-[14px] text-ink-soft hover:bg-slate-50"
      >
        <ArrowDownUp className="h-4 w-4 text-ink-muted" />
        Sortiert nach <span className="font-semibold text-ink">{SORT_LABELS[sort]}</span>
      </button>
      <button className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2.5 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
        <SlidersHorizontal className="h-4 w-4 text-ink-muted" />
        Filter
      </button>
    </div>
  )
}

const columns = ['Name', 'LinkedIn', 'E-Mail', 'Telefon', 'Erfahrung', 'Skills']
const GRID = 'grid-cols-[1.6fr_0.7fr_1.6fr_1fr_1.4fr_1.2fr]'

/** Download the given candidates as a CSV file (client-side, no backend call). */
function exportCsv(rows: Candidate[]): void {
  if (rows.length === 0) return
  const headers = ['Name', 'E-Mail', 'Telefon', 'Titel', 'Unternehmen', 'Standort', 'Skills', 'LinkedIn']
  const cell = (v: string) => `"${(v ?? '').replace(/"/g, '""')}"`
  const lines = [
    headers.join(','),
    ...rows.map((c) =>
      [
        c.name,
        c.email,
        c.phone,
        c.currentTitle,
        c.currentCompany,
        c.location,
        (c.profile?.allSkills ?? c.skills.map((s) => s.label)).join('; '),
        c.linkedinUrl ?? '',
      ]
        .map((v) => cell(String(v ?? '')))
        .join(','),
    ),
  ]
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `kandidaten-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

/** Free-text haystack for one candidate row. */
function matches(c: Candidate, q: string): boolean {
  const hay = [
    c.name,
    c.email,
    c.phone,
    c.currentTitle,
    c.currentCompany,
    c.location,
    ...(c.profile?.allSkills ?? c.skills.map((s) => s.label)),
  ]
    .join(' ')
    .toLowerCase()
  return hay.includes(q)
}

export function CandidatesView() {
  // Deep-link: /?upload=1 opens the CV import dialog straight away.
  const [uploadOpen, setUploadOpen] = useState(
    () => new URLSearchParams(window.location.search).get('upload') === '1',
  )
  const [refreshKey, setRefreshKey] = useState(0)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('activity')
  const [selected, setSelected] = useState<Candidate | null>(null)
  const { data } = useAsync(() => api.candidates(), [refreshKey])

  const rows = useMemo(() => {
    const all = data ? data.map(toCandidate) : mockCandidates
    const q = query.trim().toLowerCase()
    const filtered = q ? all.filter((c) => matches(c, q)) : all
    const sorted = [...filtered]
    if (sort === 'name') sorted.sort((a, b) => a.name.localeCompare(b.name, 'de'))
    else if (sort === 'verification') sorted.sort((a, b) => b.verification - a.verification)
    return sorted
  }, [data, query, sort])

  const total = data ? data.length : mockCandidates.length
  const cycleSort = () => setSort((s) => SORT_ORDER[(SORT_ORDER.indexOf(s) + 1) % SORT_ORDER.length])

  return (
    <div className="flex h-full flex-col overflow-hidden pt-[76px]">
      {/* Header */}
      <div className="flex items-center justify-between px-8 pt-6">
        <div className="flex items-center gap-3">
          <Breadcrumb items={['Start', 'Kandidaten']} count={total} />
        </div>
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => exportCsv(rows)}
            disabled={rows.length === 0}
            className="flex items-center gap-1.5 rounded-xl border border-line px-4 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50 disabled:opacity-40"
          >
            <Download className="h-4 w-4" /> Export
          </button>
          <button
            onClick={() => setUploadOpen(true)}
            className="rounded-xl bg-ink px-4 py-2 text-[14px] font-semibold text-white hover:bg-ink-soft"
          >
            + Kandidat
          </button>
        </div>
      </div>

      <div className="px-8 pt-5">
        <Toolbar query={query} onQuery={setQuery} sort={sort} onCycleSort={cycleSort} />
      </div>

      {/* Table */}
      <div className="mt-2 flex-1 overflow-y-auto px-8 pb-8">
        <div className={`grid ${GRID} gap-4 border-b border-line px-2 py-3 text-[13px] font-medium text-ink-muted`}>
          {columns.map((c) => (
            <div key={c}>{c}</div>
          ))}
        </div>

        {rows.length === 0 && (
          <div className="px-2 py-16 text-center text-[14px] text-ink-muted">
            Keine Kandidaten gefunden für „{query}“.
          </div>
        )}

        {rows.map((c) => (
          <div
            key={c.id}
            onClick={() => setSelected(c)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setSelected(c)}
            className={`grid cursor-pointer ${GRID} items-center gap-4 border-b border-line px-2 py-4 transition-colors hover:bg-slate-50/60`}
          >
            {/* Name */}
            <div className="flex min-w-0 items-center gap-3">
              <Avatar initials={c.initials} tone={c.avatar} />
              <span className="truncate font-semibold leading-tight text-ink">{c.name}</span>
            </div>

            {/* LinkedIn */}
            <div className="flex items-center">
              {c.linkedinUrl ? (
                <LinkedInMark href={c.linkedinUrl} />
              ) : (
                <span className="text-ink-faint">—</span>
              )}
            </div>

            {/* Email */}
            <a
              className="truncate text-[15px] font-medium text-brand-600 hover:underline"
              href={`mailto:${c.email}`}
              onClick={(e) => e.stopPropagation()}
            >
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
          </div>
        ))}
      </div>

      {selected && <CandidateDossier candidate={selected} onClose={() => setSelected(null)} />}

      {uploadOpen && (
        <CvUploadModal
          onClose={() => setUploadOpen(false)}
          onCreated={() => setRefreshKey((k) => k + 1)}
        />
      )}
    </div>
  )
}
