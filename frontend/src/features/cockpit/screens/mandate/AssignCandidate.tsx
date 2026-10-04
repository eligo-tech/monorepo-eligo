// "Kandidat zuordnen" — the same assignment, from the other end.
//
// Both directions are real work and neither substitutes for the other: after
// a Qualifikationsgespräch you are on the person and think of mandates, and
// while working a mandate you are on the search and think of people. Having
// only the first meant that filling a mandate required leaving it.
//
// The list is the pool, ranked by the shared scorer, with the people already
// on this mandate marked rather than hidden — "who is already on this?" is
// the question you ask just before "who else?".

import { useMemo, useState } from 'react'
import { Check, Search, UserPlus, X } from 'lucide-react'

import { api } from '@/api/client'
import type { CandidateDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { searchScore } from '@/lib/search'

export function AssignCandidate({
  jobId,
  assignedCandidateIds,
  onAssigned,
}: {
  jobId: string
  assignedCandidateIds: string[]
  onAssigned?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<string[]>([])

  const pool = useAsync(
    () =>
      open
        ? api.candidatesPage().catch(() => ({ items: [], total: 0 }))
        : Promise.resolve({ items: [] as CandidateDTO[], total: 0 }),
    [open],
  )

  const rows = useMemo(() => {
    const all = pool.data?.items ?? []
    const scored = all
      .map((c) => ({
        c,
        score: searchScore(
          [
            { text: c.full_name, weight: 3 },
            { text: c.current_title ?? '', weight: 3 },
            { text: (c.skills ?? []).join(' '), weight: 2.5 },
            { text: c.current_company ?? '', weight: 2 },
            { text: c.location ?? '', weight: 2 },
          ],
          query,
        ),
      }))
      .filter((r) => r.score > 0)
    if (query.trim()) scored.sort((a, b) => b.score - a.score)
    else scored.sort((a, b) => a.c.full_name.localeCompare(b.c.full_name, 'de'))
    return scored.map((r) => r.c).slice(0, 40)
  }, [pool.data, query])

  async function assign(candidate: CandidateDTO) {
    setBusy(candidate.id)
    try {
      await api.assignToJob(candidate.id, jobId)
      setDone((prev) => [...prev, candidate.id])
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
        className="flex items-center gap-1.5 rounded-lg border border-cockpit-line px-2.5 py-1.5 font-mono text-[12px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-mint-300"
      >
        <UserPlus className="h-3.5 w-3.5" /> Kandidat zuordnen
      </button>
    )
  }

  return (
    <div className="relative">
      <div className="absolute right-0 top-0 z-50 w-[26rem] rounded-xl border border-cockpit-line bg-cockpit-surface p-3 shadow-panel">
        <div className="mb-2 flex items-center gap-2">
          <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
            Kandidat zuordnen
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
            placeholder="Name, Titel, Skill oder Ort — Tippfehler erlaubt"
            className="w-full bg-transparent text-[13px] text-cockpit-text placeholder:text-cockpit-faint focus:outline-none"
          />
        </label>

        <div className="max-h-72 space-y-0.5 overflow-y-auto">
          {pool.loading && (
            <p className="px-2 py-3 font-mono text-[12px] text-cockpit-faint">lädt…</p>
          )}
          {!pool.loading && rows.length === 0 && (
            <p className="px-2 py-3 text-[13px] text-cockpit-faint">
              Kein Kandidat passt zu „{query}“.
            </p>
          )}
          {rows.map((c) => {
            const already = assignedCandidateIds.includes(c.id) || done.includes(c.id)
            return (
              <button
                key={c.id}
                type="button"
                disabled={already || busy !== null}
                onClick={() => void assign(c)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors',
                  already
                    ? 'cursor-default text-cockpit-faint'
                    : 'text-cockpit-dim hover:bg-white/[0.04] hover:text-cockpit-text',
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px]">{c.full_name}</span>
                  <span className="block truncate text-[11.5px] text-cockpit-faint">
                    {c.current_title || '—'}
                    {c.location ? ` · ${c.location}` : ''}
                  </span>
                </span>
                {already ? (
                  <span className="flex shrink-0 items-center gap-1 font-mono text-[11px] text-mint-400">
                    <Check className="h-3.5 w-3.5" /> im Prozess
                  </span>
                ) : (
                  <span className="shrink-0 font-mono text-[11px] text-cockpit-faint">
                    {busy === c.id ? 'ordnet zu…' : '+'}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
