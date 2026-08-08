// "Kandidaten" — the record list, as a cockpit screen.
//
// The whole pool, live from /candidates. Free-text search, AND-semantics skill
// filtering and CSV export are unchanged from the original view; only the surface
// is cockpit now. Verification is surfaced as a column because it is the one number
// on a candidate the record can actually vouch for.

import { useMemo, useState } from 'react'
import { ArrowDownUp, Check, Download, Search, SlidersHorizontal, Upload, X } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { LinkedInMark } from '@/components/ui/LinkedInMark'
import { candidates as mockCandidates } from '@/data/candidates'
import type { Candidate } from '@/data/types'
import { api } from '@/api/client'
import { toCandidate } from '@/api/adapters'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { Chip, SectionHeader } from '../../ui/primitives'
import { Button, FIELD } from '../../ui/forms'
import { CandidateDrawer } from './CandidateDrawer'
import { CvUploadModal } from './CvUploadModal'

/** Anchors the Navigator's ↑/↓ steps through on this screen. */
export const KANDIDATEN_SECTIONS = ['section-kandidaten', 'section-liste']

type SortKey = 'created' | 'name' | 'verification'
const SORT_LABELS: Record<SortKey, string> = {
  created: 'Neueste zuerst',
  name: 'Name (A–Z)',
  verification: 'Verifizierung',
}
const SORT_ORDER: SortKey[] = ['created', 'name', 'verification']

/** Verification thresholds — same ladder as the rest of the cockpit. */
function verificationTone(v: number): 'mint' | 'gold' | 'coral' {
  if (v >= 90) return 'mint'
  if (v >= 75) return 'gold'
  return 'coral'
}
const TONE_TEXT = { mint: 'text-mint-400', gold: 'text-gold-400', coral: 'text-coral-400' } as const
const TONE_BAR = { mint: 'bg-mint-400', gold: 'bg-gold-400', coral: 'bg-coral-400' } as const

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
  return [
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
    .includes(q)
}

/** Filter by technology. AND semantics — each added skill narrows the list. */
function SkillFilter({
  skills,
  selected,
  onToggle,
  onClear,
}: {
  skills: { label: string; count: number }[]
  selected: Set<string>
  onToggle: (s: string) => void
  onClear: () => void
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const shown = skills.filter((s) => s.label.toLowerCase().includes(q.trim().toLowerCase()))

  return (
    <div className="relative">
      <Button onClick={() => setOpen((o) => !o)}>
        <SlidersHorizontal className="h-4 w-4" />
        Filter
        {selected.size > 0 && (
          <span className="rounded-md bg-mint-800/70 px-1.5 font-mono text-[12px] text-mint-300">
            {selected.size}
          </span>
        )}
      </Button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-2 w-72 rounded-xl border border-cockpit-line bg-cockpit-surface p-2 shadow-panel">
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-cockpit-line bg-cockpit-inset px-2.5 py-1.5 focus-within:border-mint-600">
              <Search className="h-4 w-4 shrink-0 text-cockpit-faint" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Technologie suchen…"
                className="w-full bg-transparent text-[13px] text-cockpit-text outline-none placeholder:text-cockpit-faint"
              />
            </div>

            <div className="max-h-64 overflow-y-auto">
              {shown.length === 0 && (
                <p className="px-2 py-3 text-center text-[13px] text-cockpit-faint">Keine Treffer</p>
              )}
              {shown.map((s) => {
                const active = selected.has(s.label)
                return (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => onToggle(s.label)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-white/[0.04]"
                  >
                    <span
                      className={cn(
                        'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                        active
                          ? 'border-mint-500 bg-mint-500 text-[#0f1a12]'
                          : 'border-cockpit-edge',
                      )}
                    >
                      {active && <Check className="h-3 w-3" strokeWidth={3} />}
                    </span>
                    <span className="flex-1 truncate text-[13px] text-cockpit-text">{s.label}</span>
                    <span className="font-mono text-[12px] text-cockpit-faint">{s.count}</span>
                  </button>
                )
              })}
            </div>

            {selected.size > 0 && (
              <button
                type="button"
                onClick={onClear}
                className="mt-2 w-full rounded-lg border border-cockpit-line py-1.5 font-mono text-[12px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
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

const GRID = 'grid-cols-[1.7fr_0.5fr_1.5fr_1fr_1.4fr_1.1fr_0.7fr]'
const COLUMNS = ['Name', 'LI', 'E-Mail', 'Telefon', 'Erfahrung', 'Skills', 'Verif.']

export function KandidatenScreen() {
  // Deep-link: ?upload=1 opens the CV import dialog straight away.
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
    else if (sort === 'verification') sorted.sort((a, b) => b.verification - a.verification)
    else sorted.sort((a, b) => (b.createdAt ?? '').localeCompare(a.createdAt ?? ''))
    return sorted
  }, [all, query, sort, skillFilter])

  const avgVerification = all.length
    ? Math.round(all.reduce((s, c) => s + c.verification, 0) / all.length)
    : 0

  const cycleSort = () =>
    setSort((s) => SORT_ORDER[(SORT_ORDER.indexOf(s) + 1) % SORT_ORDER.length])
  const toggleSkill = (s: string) =>
    setSkillFilter((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })

  return (
    <div className="space-y-8">
      <header id="section-kandidaten" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Kandidaten
        </h1>
        <p className="mt-2 max-w-xl text-[16px] leading-relaxed text-cockpit-dim">
          Der eigene Bestand — jedes Profil aus einem echten Dokument extrahiert und gegen
          seine Quelle geprüft.
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          id="section-liste"
          index="01"
          title="Bestand"
          hint={error ? 'offline · Demo-Daten' : 'live aus dem Datensatz'}
        />

        {/* Stats strip */}
        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 font-mono text-[13px] text-cockpit-faint">
          <span>
            <span className="text-cockpit-text">{all.length}</span> Kandidaten
          </span>
          <span>
            <span className="text-cockpit-text">{rows.length}</span> angezeigt
          </span>
          <span>
            <span className="text-cockpit-text">{skillOptions.length}</span> Technologien
          </span>
          <span>
            Ø Verifizierung{' '}
            <span className={TONE_TEXT[verificationTone(avgVerification)]}>
              {avgVerification}%
            </span>
          </span>
        </div>

        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-3">
          <label className="relative flex min-w-[16rem] flex-1 items-center">
            <Search className="pointer-events-none absolute left-3.5 h-[17px] w-[17px] text-cockpit-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Kandidaten, Stichworte, Notizen…"
              className={cn(FIELD, 'py-2.5 pl-11 pr-9 text-[15px]')}
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery('')}
                aria-label="Suche zurücksetzen"
                className="absolute right-3 text-cockpit-faint transition-colors hover:text-cockpit-text"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </label>

          <Button onClick={cycleSort}>
            <ArrowDownUp className="h-4 w-4" />
            <span className="text-cockpit-faint">Sortiert nach</span>
            <span className="font-mono text-cockpit-text">{SORT_LABELS[sort]}</span>
          </Button>

          <SkillFilter
            skills={skillOptions}
            selected={skillFilter}
            onToggle={toggleSkill}
            onClear={() => setSkillFilter(new Set())}
          />

          <Button onClick={() => exportCsv(rows)} disabled={rows.length === 0}>
            <Download className="h-4 w-4" /> Export
          </Button>

          <Button tone="primary" onClick={() => setUploadOpen(true)}>
            <Upload className="h-4 w-4" /> Kandidat aus CV
          </Button>
        </div>

        {/* Table */}
        <div>
          <div
            className={cn(
              'grid gap-4 border-b border-cockpit-line px-3 pb-2.5',
              'font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint',
              GRID,
            )}
          >
            {COLUMNS.map((c) => (
              <div key={c} className={c === 'Verif.' ? 'text-right' : undefined}>
                {c}
              </div>
            ))}
          </div>

          {loading && rows.length === 0 && (
            <p className="py-16 text-center font-mono text-[13px] text-cockpit-faint">Lädt…</p>
          )}

          {!loading && rows.length === 0 && (
            <p className="py-16 text-center text-[14px] text-cockpit-dim">
              Keine Kandidaten gefunden
              {query ? ` für „${query}"` : ''}
              {skillFilter.size > 0 ? ` mit ${[...skillFilter].join(', ')}` : ''}.
            </p>
          )}

          {rows.map((c) => {
            const tone = verificationTone(c.verification)
            return (
              <div
                key={c.id}
                onClick={() => setSelected(c)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setSelected(c)}
                className={cn(
                  'grid cursor-pointer items-center gap-4 border-b border-cockpit-line px-3 py-3.5',
                  'transition-colors hover:bg-white/[0.03]',
                  GRID,
                )}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <Avatar initials={c.initials} tone={c.avatar} size="sm" />
                  <span className="truncate font-semibold leading-tight text-cockpit-text">
                    {c.name}
                  </span>
                </div>

                <div className="flex items-center">
                  {c.linkedinUrl ? (
                    <LinkedInMark href={c.linkedinUrl} />
                  ) : (
                    <span className="font-mono text-cockpit-faint">—</span>
                  )}
                </div>

                <a
                  className="truncate font-mono text-[13px] text-mint-400 hover:underline"
                  href={`mailto:${c.email}`}
                  onClick={(e) => e.stopPropagation()}
                >
                  {c.email}
                </a>

                <div className="truncate font-mono text-[13px] text-cockpit-dim">{c.phone}</div>

                <div className="min-w-0 text-[14px] leading-snug">
                  <div className="truncate font-semibold text-cockpit-text">{c.currentTitle}</div>
                  <div className="truncate text-cockpit-faint">
                    {c.currentCompany}
                    {c.tenure !== '—' && <span className="font-mono"> · {c.tenure}</span>}
                    {c.extraRoles > 0 && <span className="font-mono"> +{c.extraRoles}</span>}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {c.skills.slice(0, 2).map((s) => (
                    <Chip key={s.label}>{s.label}</Chip>
                  ))}
                  {c.extraSkills > 0 && (
                    <span className="font-mono text-[12px] text-cockpit-faint">
                      +{c.extraSkills}
                    </span>
                  )}
                </div>

                {/* Verification — live from the record, so no provenance mark. */}
                <div className="flex items-center justify-end gap-2">
                  <span className="h-[5px] w-10 overflow-hidden rounded-full bg-[#26281f]">
                    <span
                      className={cn('block h-full rounded-full', TONE_BAR[tone])}
                      style={{ width: `${Math.max(0, Math.min(100, c.verification))}%` }}
                    />
                  </span>
                  <span className={cn('w-9 text-right font-mono text-[13px]', TONE_TEXT[tone])}>
                    {c.verification}%
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {selected && (
        <CandidateDrawer
          candidate={selected}
          onClose={() => setSelected(null)}
          onSaved={(updated) => {
            setSelected(toCandidate(updated)) // reflect the edit in the open drawer
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
