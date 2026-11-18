import { useUser } from '@clerk/clerk-react'

import { authEnabled } from './config'

// ELI-20. The cover sheet's "Kontakt" box names the person who downloads it.
// The session token carries no name or e-mail by default (see memberNames.ts,
// ELI-50), but the browser holds the signed-in user from Clerk, so that is
// where both come from. The recruiter can still overwrite them in the dialog.

export interface SignedInContact {
  name: string
  email: string
}

interface ClerkUserLike {
  fullName?: string | null
  firstName?: string | null
  lastName?: string | null
  primaryEmailAddress?: { emailAddress?: string | null } | null
}

/** Name and primary e-mail of a Clerk user; empty strings when unknown. */
export function contactFromUser(user: ClerkUserLike | null | undefined): SignedInContact {
  if (!user) return { name: '', email: '' }
  const name =
    user.fullName?.trim() || [user.firstName, user.lastName].filter(Boolean).join(' ').trim()
  return { name, email: user.primaryEmailAddress?.emailAddress?.trim() ?? '' }
}

function useClerkContact(): SignedInContact {
  const { user } = useUser()
  return contactFromUser(user)
}

const NOBODY: SignedInContact = { name: '', email: '' }

// Without a Clerk key there is no ClerkProvider (demo mode) and a Clerk hook
// would throw; `authEnabled` is fixed at build time.
export const useSignedInContact: () => SignedInContact = authEnabled ? useClerkContact : () => NOBODY
