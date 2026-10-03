// "Änderungsverlauf" — the receipt ledger, finally visible.
//
// Every verified change has been recorded since the first commit and nothing
// in the product ever showed it. That is a strange gap for a system whose
// claim is that each value is evidence-backed: the evidence existed and only
// a SQL client could read it.
//
// One line per written change: when, who, which field, what it became. An
// agent's work is attributed to the agent, a person's to the name the token
// gave — never to "unknown" by accident.

import { useEffect, useState } from 'react'
import { History } from 'lucide-react'

import { api } from '@/api/client'
import type { HistoryEntryDTO } from '@/api/types'
import { cn } from '@/lib/cn'

/** "human_verified" → a person stood behind it; anything else is a machine. */
const SOURCE_LABEL: Record<string, string> = {
  human_verified: 'Mensch',
  llm_extraction: 'KI-Extraktion',
  third_party: 'Drittquelle',
  public_web: 'Öffentliche Quelle',
  self_reported: 'Selbstauskunft',
}

function when(iso: string): string {
  return new Date(iso).toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Berlin',
  })
}

/** `write current_title='Lead Engineer'` → `Lead Engineer`. The field name is
 *  shown separately, so repeating it in the line is noise. */
function value(entry: HistoryEntryDTO): string {
  const match = /^write\s+[\w.]+=(.*)$/.exec(entry.summary)
  const raw = match ? match[1] : entry.summary
  return raw.replace(/^['"]|['"]$/g, '')
}

export function HistoryTrail({
  entityType,
  entityId,
  limit = 8,
  className,
}: {
  entityType: 'candidate' | 'job'
  entityId: string
  limit?: number
  className?: string
}) {
  const [entries, setEntries] = useState<HistoryEntryDTO[] | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .history(entityType, entityId)
      .then((rows) => alive && setEntries(rows))
      .catch(() => alive && setEntries([]))
    return () => {
      alive = false
    }
  }, [entityType, entityId])

  if (entries === null) return null
  const shown = expanded ? entries : entries.slice(0, limit)

  return (
    <section className={cn('space-y-2', className)}>
      <h2 className="mb-3 flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.12em] text-mint-400">
        <History className="h-4 w-4" /> Änderungsverlauf
      </h2>

      {entries.length === 0 ? (
        <p className="text-[13px] italic text-cockpit-faint">
          Noch keine protokollierte Änderung. Jede verifizierte Änderung
          erscheint hier mit Zeitpunkt und Urheber.
        </p>
      ) : (
        <>
          <ul className="space-y-1.5">
            {shown.map((entry, i) => (
              <li
                key={`${entry.at}-${i}`}
                className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 border-b border-cockpit-line/60 pb-1.5 text-[13px] last:border-b-0"
              >
                <span className="font-mono text-[11.5px] text-cockpit-faint">
                  {when(entry.at)}
                </span>
                <span className="text-cockpit-text">{entry.actor}</span>
                {entry.field && (
                  <span className="font-mono text-[11.5px] text-cockpit-dim">
                    {entry.field}
                  </span>
                )}
                <span className="min-w-0 flex-1 truncate text-cockpit-dim">
                  {value(entry)}
                </span>
                {entry.source && entry.source !== 'human_verified' && (
                  <span className="font-mono text-[11px] text-gold-300">
                    {SOURCE_LABEL[entry.source] ?? entry.source}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {entries.length > limit && (
            <button
              type="button"
              onClick={() => setExpanded((open) => !open)}
              className="font-mono text-[11.5px] text-cockpit-faint transition-colors hover:text-cockpit-text"
            >
              {expanded
                ? 'weniger zeigen'
                : `alle ${entries.length} Einträge zeigen`}
            </button>
          )}
        </>
      )}
    </section>
  )
}
