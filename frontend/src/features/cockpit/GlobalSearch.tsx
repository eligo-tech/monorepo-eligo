// ELI-52: the command bar's search box. It was "noch ohne Funktion" on every
// screen but Mandate; now typing (≥2 characters, debounced) lists this
// workspace's candidates, mandates, companies and contacts, and ↑/↓/Enter or a
// click opens the record where the cockpit already shows it.
//
// Where a screen gives the box its own meaning (`suggest` false — today the
// Mandate list, which filters on it), the term still reaches that screen and
// no dropdown covers the list it is filtering.

import { t } from '@/i18n'

import { Search } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { api } from '@/api/client'
import type { SearchResultsDTO } from '@/api/types'
import { flattenHits, moveSelection, searchTerm, type FlatHit } from './ui/globalSearch'
import { SearchResultsList } from './ui/SearchResultsList'

const DEBOUNCE_MS = 220
const LIST_ID = 'cockpit-search-results'

export function GlobalSearch({
  query,
  onQueryChange,
  placeholder,
  suggest,
  onOpen,
}: {
  query: string
  onQueryChange: (q: string) => void
  placeholder: string
  suggest: boolean
  /** Open a record by its cockpit hash, e.g. `kandidaten/<id>`. */
  onOpen: (hash: string) => void
}) {
  const [results, setResults] = useState<SearchResultsDTO | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const input = useRef<HTMLInputElement>(null)

  const term = suggest ? searchTerm(query) : null

  useEffect(() => {
    setActive(-1)
    if (!term) {
      setResults(null)
      setLoading(false)
      setFailed(false)
      return
    }
    setLoading(true)
    setFailed(false)
    const abort = new AbortController()
    const timer = window.setTimeout(() => {
      api
        .search(term, { signal: abort.signal })
        .then((r) => {
          setResults(r)
          // A step taken while the old list showed points into the old list.
          setActive(-1)
          setLoading(false)
        })
        .catch(() => {
          if (abort.signal.aborted) return
          setResults(null)
          setFailed(true)
          setLoading(false)
        })
    }, DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      abort.abort()
    }
  }, [term])

  const hits = flattenHits(results)
  const showList = open && term !== null

  const pick = (hit: FlatHit) => {
    onOpen(hit.hash)
    onQueryChange('')
    setOpen(false)
    input.current?.blur()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!term) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setOpen(true)
      setActive((i) => moveSelection(i, e.key as 'ArrowDown' | 'ArrowUp', hits.length))
    } else if (e.key === 'Enter') {
      const hit = hits[active >= 0 ? active : 0]
      if (hit && !loading) {
        e.preventDefault()
        pick(hit)
      }
    } else if (e.key === 'Escape') {
      if (open) {
        e.preventDefault()
        setOpen(false)
      } else {
        onQueryChange('')
      }
    }
  }

  return (
    <div className="relative flex min-w-[18rem] flex-1 items-center 2xl:max-w-[30rem]">
      <Search className="pointer-events-none absolute left-4 h-[17px] w-[17px] text-cockpit-faint" />
      <input
        ref={input}
        value={query}
        onChange={(e) => {
          onQueryChange(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label={placeholder}
        role={suggest ? 'combobox' : undefined}
        aria-expanded={suggest ? showList : undefined}
        aria-controls={suggest ? LIST_ID : undefined}
        aria-activedescendant={showList && active >= 0 ? `${LIST_ID}-${active}` : undefined}
        autoComplete="off"
        className="w-full rounded-xl border border-cockpit-line bg-cockpit-inset py-2.5 pl-11 pr-4 text-[15px] text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none"
      />
      {showList && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-[max(100%,30rem)] max-w-[calc(100vw-2rem)] rounded-xl border border-cockpit-line bg-cockpit-surface shadow-panel">
          <SearchResultsList
            listId={LIST_ID}
            hits={hits}
            active={active}
            loading={loading}
            failed={failed}
            term={term}
            onPick={pick}
            onHover={setActive}
          />
          {hits.length > 0 && (
            <div className="border-t border-cockpit-line px-4 py-1.5 font-mono text-[11px] text-cockpit-faint">
              {t('↑/↓ wählen · Enter öffnen · Esc schließen')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
