// ELI-52: the command bar's dropdown — hits grouped by kind, one selected.
// Presentational: the parent fetches and owns the selection.

import { Fragment } from 'react'

import { t } from '@/i18n'
import { cn } from '@/lib/cn'

import type { FlatHit, HitGroup } from './globalSearch'

const HEADINGS: Record<HitGroup, () => string> = {
  candidates: () => t('Kandidaten'),
  jobs: () => t('Mandate'),
  companies: () => t('Unternehmen'),
  contacts: () => t('Leads & Manager'),
}

export function SearchResultsList({
  hits,
  active,
  loading,
  failed,
  term,
  onPick,
  onHover,
  listId,
}: {
  hits: FlatHit[]
  active: number
  loading: boolean
  failed: boolean
  term: string
  onPick: (hit: FlatHit) => void
  onHover: (index: number) => void
  listId?: string
}) {
  if (hits.length === 0) {
    return (
      <div className="px-4 py-3 font-mono text-[13px] text-cockpit-faint">
        {loading
          ? t('Suche …')
          : failed
            ? t('Suche fehlgeschlagen')
            : t('Keine Treffer für „{q}“', { q: term })}
      </div>
    )
  }

  return (
    <ul id={listId} role="listbox" className="max-h-[70vh] overflow-y-auto py-1">
      {hits.map((hit, i) => (
        <Fragment key={`${hit.group}/${hit.id}`}>
          {(i === 0 || hits[i - 1].group !== hit.group) && (
            <li
              role="presentation"
              className="px-4 pb-1 pt-2.5 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint"
            >
              {HEADINGS[hit.group]()}
            </li>
          )}
          <li
            id={listId ? `${listId}-${i}` : undefined}
            role="option"
            aria-selected={i === active}
            // mousedown, not click: the input's blur would close the list first.
            onMouseDown={(e) => {
              e.preventDefault()
              onPick(hit)
            }}
            onMouseEnter={() => onHover(i)}
            className={cn(
              'mx-1 flex cursor-pointer items-baseline gap-2 rounded-lg px-3 py-1.5',
              i === active ? 'bg-cockpit-raised ring-1 ring-mint-600/50' : 'hover:bg-cockpit-raised/60',
            )}
          >
            <span className="truncate text-[14.5px] text-cockpit-text">{hit.label}</span>
            {hit.lead && (
              <span className="shrink-0 rounded border border-gold-600/45 px-1.5 font-mono text-[10.5px] text-gold-300">
                {t('Lead')}
              </span>
            )}
            {hit.subtitle && (
              <span className="truncate font-mono text-[12px] text-cockpit-faint">{hit.subtitle}</span>
            )}
          </li>
        </Fragment>
      ))}
    </ul>
  )
}
