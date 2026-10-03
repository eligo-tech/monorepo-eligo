// The mandate list, on the left, open or shut.
//
// It used to be a row of chips built from the running processes — dynamic,
// but only ever nine of seventy-six mandates, because a chip row cannot hold
// more and a mandate with nobody in process had no chip at all. That is the
// wrong way round: a search with no candidates yet is exactly the one you
// open.
//
// So: every mandate, searchable, the ones in process first because that is
// where today's work is. Collapsible, and it remembers — a panel that
// reopens itself on every page load is a panel you close twice.

import { useEffect, useMemo, useState } from 'react'
import { PanelLeftClose, PanelLeftOpen, Search } from 'lucide-react'

import { cn } from '@/lib/cn'
import type { Mandate } from '../data/types'

const STORAGE_KEY = 'eligo.mandateDrawer.open'

/** Remembered per browser; a closed panel stays closed. Storage can throw in
 *  a private window, so the default survives that rather than the screen. */
function useRemembered(key: string, fallback: boolean) {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored === null ? fallback : stored === 'true'
    } catch {
      return fallback
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(key, String(value))
    } catch {
      /* private window — the choice simply does not persist */
    }
  }, [key, value])
  return [value, setValue] as const
}

function matches(mandate: Mandate, query: string): boolean {
  if (!query) return true
  const haystack = `${mandate.title} ${mandate.client} ${mandate.ref}`.toLowerCase()
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term))
}

function Row({
  mandate,
  active,
  onSelect,
}: {
  mandate: Mandate
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? 'true' : undefined}
      className={cn(
        'flex w-full items-baseline gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors',
        active
          ? 'bg-white/[0.07] text-cockpit-text'
          : 'text-cockpit-dim hover:bg-white/[0.03] hover:text-cockpit-text',
      )}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px]">{mandate.title}</span>
        <span className="block truncate text-[11.5px] text-cockpit-faint">
          {mandate.client}
        </span>
      </span>
      {mandate.cards.length > 0 && (
        <span className="shrink-0 font-mono text-[11px] text-mint-400">
          {mandate.cards.length}
        </span>
      )}
    </button>
  )
}

export function MandateDrawer({
  mandates,
  activeIds,
  onSelect,
}: {
  /** Every mandate in the workspace, in process or not. */
  mandates: Mandate[]
  /** What the cockpit is currently showing — one, several, or none. */
  activeIds: string[]
  onSelect: (id: string | null) => void
}) {
  const [open, setOpen] = useRemembered(STORAGE_KEY, true)
  const [query, setQuery] = useState('')

  const { running, rest } = useMemo(() => {
    const visible = mandates.filter((m) => matches(m, query))
    return {
      running: visible.filter((m) => m.cards.length > 0),
      rest: visible.filter((m) => m.cards.length === 0),
    }
  }, [mandates, query])

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Mandate einblenden"
        className="sticky top-24 flex h-fit shrink-0 items-center gap-2 rounded-lg border border-cockpit-line px-2 py-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
      >
        <PanelLeftOpen className="h-4 w-4" />
        <span className="[writing-mode:vertical-rl]">Mandate</span>
      </button>
    )
  }

  return (
    <aside className="sticky top-24 flex h-fit max-h-[calc(100vh-8rem)] w-[248px] shrink-0 flex-col rounded-xl border border-cockpit-line bg-cockpit-inset">
      <div className="flex items-center gap-2 border-b border-cockpit-line px-3 py-2">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          Mandate
        </span>
        <span className="font-mono text-[11px] text-cockpit-faint">
          {mandates.length}
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          title="Mandate ausblenden"
          className="ml-auto text-cockpit-faint transition-colors hover:text-cockpit-text"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      <label className="flex items-center gap-2 border-b border-cockpit-line px-3 py-2">
        <Search className="h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Mandat oder Firma…"
          className="w-full bg-transparent text-[12.5px] text-cockpit-text placeholder:text-cockpit-faint focus:outline-none"
        />
      </label>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <button
          type="button"
          onClick={() => onSelect(null)}
          aria-current={activeIds.length === 0 ? 'true' : undefined}
          className={cn(
            'mb-1 w-full rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors',
            activeIds.length === 0
              ? 'bg-white/[0.07] text-cockpit-text'
              : 'text-cockpit-dim hover:bg-white/[0.03] hover:text-cockpit-text',
          )}
        >
          Gesamt
          <span className="block text-[11.5px] text-cockpit-faint">
            Alle laufenden Prozesse
          </span>
        </button>

        {running.length > 0 && (
          <>
            <p className="px-2.5 pb-1 pt-3 font-mono text-[10.5px] uppercase tracking-[0.1em] text-cockpit-faint">
              Im Prozess · {running.length}
            </p>
            {running.map((mandate) => (
              <Row
                key={mandate.id}
                mandate={mandate}
                active={activeIds.includes(mandate.id)}
                onSelect={() => onSelect(mandate.id)}
              />
            ))}
          </>
        )}

        {rest.length > 0 && (
          <>
            <p className="px-2.5 pb-1 pt-3 font-mono text-[10.5px] uppercase tracking-[0.1em] text-cockpit-faint">
              Ohne Prozess · {rest.length}
            </p>
            {rest.map((mandate) => (
              <Row
                key={mandate.id}
                mandate={mandate}
                active={activeIds.includes(mandate.id)}
                onSelect={() => onSelect(mandate.id)}
              />
            ))}
          </>
        )}

        {running.length === 0 && rest.length === 0 && (
          <p className="px-2.5 py-6 text-center text-[12.5px] text-cockpit-faint">
            Kein Mandat passt zu „{query}".
          </p>
        )}
      </div>
    </aside>
  )
}
