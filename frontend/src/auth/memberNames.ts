import { useMemo } from 'react'
import { useOrganization } from '@clerk/clerk-react'

import { authEnabled } from './config'

// ELI-50. The backend records who acted as `actor_name`, taken from the
// session token (`backend/app/core/auth.py:_actor_name`). A default Clerk
// session token carries no name claim, so that falls back to the Clerk user
// id — and "· user_3LC4zJ88…" is what the Leads list printed. There is no
// users table: membership lives in Clerk, and the active organization's
// member list (which the browser already holds a session for) is the one
// place that maps an id to a person. A name the backend did record passes
// through untouched; an id nobody can name is not shown at all.

/** A Clerk user id, e.g. `user_3LC4zJ88lXZQ3nkU7HHtROiru6X`. */
export const isClerkUserId = (value: string) => /^user_[A-Za-z0-9]+$/.test(value)

/** What to call the author: the member's name, else the recorded name, else
 *  nothing — never the raw id. */
export function actorLabel(raw: string | null | undefined, names: ReadonlyMap<string, string>): string | null {
  const value = raw?.trim()
  if (!value) return null
  return names.get(value) ?? (isClerkUserId(value) ? null : value)
}

interface MemberPublicData {
  userId?: string | null
  firstName?: string | null
  lastName?: string | null
  identifier?: string | null
}

/** user id → readable name (full name, else the sign-in identifier). */
export function memberNameMap(members: readonly (MemberPublicData | null | undefined)[]): Map<string, string> {
  const out = new Map<string, string>()
  for (const m of members) {
    if (!m?.userId) continue
    const name = [m.firstName, m.lastName].filter(Boolean).join(' ').trim() || m.identifier?.trim()
    if (name) out.set(m.userId, name)
  }
  return out
}

const NOBODY: ReadonlyMap<string, string> = new Map()

function useClerkMemberNames(): ReadonlyMap<string, string> {
  const { memberships } = useOrganization({ memberships: { pageSize: 100 } })
  const data = memberships?.data
  return useMemo(() => memberNameMap((data ?? []).map((m) => m.publicUserData)), [data])
}

// Without a Clerk key there is no ClerkProvider (demo mode), and calling a
// Clerk hook would throw. `authEnabled` is fixed at build time, so the choice
// of hook never changes between renders.
const useMemberNames: () => ReadonlyMap<string, string> = authEnabled ? useClerkMemberNames : () => NOBODY

/** `label(raw)` — the readable author for a recorded actor name or id. */
export function useActorLabel(): (raw: string | null | undefined) => string | null {
  const names = useMemberNames()
  return useMemo(() => (raw: string | null | undefined) => actorLabel(raw, names), [names])
}
