// ELI-52: the command bar's search, as pure pieces — what to ask, where each
// hit opens, and how ↑/↓ move through the list. The fetching lives in
// `GlobalSearch.tsx`; the list's markup in `SearchResultsList.tsx`.

import type { SearchResultsDTO } from '@/api/types'

export type HitGroup = 'candidates' | 'jobs' | 'companies' | 'contacts'

export interface FlatHit {
  group: HitGroup
  id: string
  label: string
  subtitle: string | null
  /** A bus-dev contact taken from Markt, not yet a vetted manager. */
  lead: boolean
  /** Where the cockpit already shows this record — `#<screen>/<id>`. */
  hash: string
}

/** The order the dropdown reads in, and each group's screen. */
export const GROUPS: { key: HitGroup; screen: string }[] = [
  { key: 'candidates', screen: 'kandidaten' },
  // A mandate's workspace is the cockpit focused on it (`#cockpit/<jobId>`).
  { key: 'jobs', screen: 'cockpit' },
  { key: 'companies', screen: 'companies' },
  // Leads are managers rows too, and the manager page opens either.
  { key: 'contacts', screen: 'managers' },
]

/** Below two characters a term matches half the pool — nothing is asked. */
export const MIN_TERM = 2

export function searchTerm(raw: string): string | null {
  const term = raw.trim()
  return term.length >= MIN_TERM ? term : null
}

export function flattenHits(results: SearchResultsDTO | null): FlatHit[] {
  if (!results) return []
  return GROUPS.flatMap(({ key, screen }) =>
    (results[key] ?? []).map((hit) => ({
      group: key,
      id: hit.id,
      label: hit.label,
      subtitle: hit.subtitle,
      lead: 'kind' in hit && hit.kind === 'lead',
      hash: `${screen}/${hit.id}`,
    })),
  )
}

/** The next keyboard selection; -1 is "none", and the list wraps. */
export function moveSelection(current: number, key: 'ArrowDown' | 'ArrowUp', count: number): number {
  if (count === 0) return -1
  if (key === 'ArrowDown') return current < 0 ? 0 : (current + 1) % count
  return current <= 0 ? count - 1 : current - 1
}
