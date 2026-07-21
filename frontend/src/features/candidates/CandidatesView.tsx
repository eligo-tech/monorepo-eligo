import { useMemo, useState } from 'react'
import { Search, SlidersHorizontal, ArrowDownUp, X, Download, Check } from 'lucide-react'
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

type SortKey = 'created' | 'name'
const SORT_LABELS: Record<SortKey, string> = {
  created: 'Neueste zuerst',
  name: 'Name (A–Z)',
}
const SORT_ORDER: SortKey[] = ['created', 'name']

interface ToolbarProps {
  query: string
  onQuery: (v: string) => void
  sort: SortKey
  onCycleSort: () => void
  skills: { label: string; count: number }[]
  selected: Set<string>
  onToggleSkill: (s: string) => void
  onClearSkills: () => void
}

/** Popover: filter candidates by technology (skill). AND semantics — each added
 *  technology narrows the list to candidates who have all of them. */
function FilterPopover({
  skills,
  selected,
  onToggleSkill,
  onClearSkills,
}: Pick<ToolbarProps, 'skills' | 'selected' | 'onToggleSkill' | 'onClearSkills'>) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const shown = skills.filter((s) => s.label.toLowerCase().includes(q.trim().toLowerCase()))
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2.5 text-[14px] font-medium text-ink-soft hover:bg-slate-50"
      >
        <SlidersHorizontal className="h-4 w-4 text-ink-muted" />
        Filter
        {selected.size > 0 && (
          <span className="rounded-md bg-brand-500 px-1.5 text-[12px] font-semibold text-white">
            {selected.size}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-2 w-72 rounded-xl border border-line bg-white p-2 shadow-xl">
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-[13px] focus-within:border-brand-500">
              <Search className="h-4 w-4 text-ink-faint" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Technologie suchen…"
                className="w-full bg-transparent outline-none placeholder:text-ink-faint"
              />
            </div>
            <div className="max-h-64 overflow-y-auto">
              {shown.length === 0 && (
                <p className="px-2 py-3 text-center text-[13px] text-ink-muted">Keine Treffer</p>
              )}
              {shown.map((s) => {
                const active = selected.has(s.label)
                return (
                  <button
                    key={s.label}
                    onClick={() => onToggleSkill(s.label)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-slate-50"
                  >
                    <span
                      className={`flex h-4 w-4 items-center justify-center rounded border ${
                        active ? 'border-brand-500 bg-brand-500 text-white' : 'border-line'
                      }`}
                    >
                      {active && <Check className="h-3 w-3" />}
                    </span>
                    <span className="flex-1 truncate text-ink">{s.label}</span>
                    <span className="text-[12px] text-ink-faint">{s.count}</span>
                  </button>
                )
              })}
            </div>
            {selected.size > 0 && (
              <button
                onClick={onClearSkills}
                className="mt-2 w-full rounded-lg border border-line py-1.5 text-[13px] font-medium text-ink-soft hover:bg-slate-50"
              >
                Zurücksetzen ({selected.size})
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function Toolbar({ query, onQuery, sort, onCycleSort, ...filter }: ToolbarProps) {
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
      <FilterPopover {...filter} />
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
  const [sort, setSort] = useState<SortKey>('created')
  const [skillFilter, setSkillFilter] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Candidate | null>(null)
  const { data, loading, error } = useAsync(() => api.candidates(), [refreshKey])

  // Live data when reachable; mock only as an OFFLINE fallback (never flash mock
  // over a real, possibly-empty, tenant). While loading we show nothing.
  const all = useMemo(
    () => (data ? data.map(toCandidate) : error ? mockCandidates : []),
    [data, error],
  )

  // Distinct technologies across the pool, most common first (for the filter).
  const skillOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const c of all) {
      for (const s of c.profile?.allSkills ?? c.skills.map((x) => x.label)) {
        counts.set(s, (counts.get(s) ?? 0) + 1)
      }
    }
    return [...counts.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
  }, [all])

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    let out = q ? all.filter((c) => matches(c, q)) : all
    if (skillFilter.size > 0) {
      out = out.filter((c) => {
        const have = new Set(
          (c.profile?.allSkills ?? c.skills.map((x) => x.label)).map((s) => s.toLowerCase()),
        )
        return [...skillFilter].every((s) => have.has(s.toLowerCase()))
      })
    }
    const sorted = [...out]
    if (sort === 'name') sorted.sort((a, b) => a.name.localeCompare(b.name, 'de'))
    else sorted.sort((a, b) => (b.createdAt ?? '').localeCompare(a.createdAt ?? ''))
    return sorted
  }, [all, query, sort, skillFilter])

  const total = all.length
  const cycleSort = () => setSort((s) => SORT_ORDER[(SORT_ORDER.indexOf(s) + 1) % SORT_ORDER.length])
  const toggleSkill = (s: string) =>
    setSkillFilter((prev) => {
      const next = new Set(prev)
      next.has(s) ? next.delete(s) : next.add(s)
      return next
    })

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
        <Toolbar
          query={query}
          onQuery={setQuery}
          sort={sort}
          onCycleSort={cycleSort}
          skills={skillOptions}
          selected={skillFilter}
          onToggleSkill={toggleSkill}
          onClearSkills={() => setSkillFilter(new Set())}
        />
      </div>

      {/* Table */}
      <div className="mt-2 flex-1 overflow-y-auto px-8 pb-8">
        <div className={`grid ${GRID} gap-4 border-b border-line px-2 py-3 text-[13px] font-medium text-ink-muted`}>
          {columns.map((c) => (
            <div key={c}>{c}</div>
          ))}
        </div>

        {loading && rows.length === 0 && (
          <div className="px-2 py-16 text-center text-[14px] text-ink-muted">Lädt…</div>
        )}

        {!loading && rows.length === 0 && (
          <div className="px-2 py-16 text-center text-[14px] text-ink-muted">
            Keine Kandidaten gefunden
            {query ? ` für „${query}“` : ''}
            {skillFilter.size > 0 ? ` mit ${[...skillFilter].join(', ')}` : ''}.
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

      {selected && (
        <CandidateDossier
          candidate={selected}
          onClose={() => setSelected(null)}
          onSaved={(updated) => {
            setSelected(toCandidate(updated)) // reflect the edit in the open dossier
            setRefreshKey((k) => k + 1) // and refresh the underlying list
          }}
        />
      )}

      {uploadOpen && (
        <CvUploadModal
          onClose={() => setUploadOpen(false)}
          onCreated={() => setRefreshKey((k) => k + 1)}
        />
      )}
    </div>
  )
}
