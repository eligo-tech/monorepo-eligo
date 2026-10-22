// Clerk auth is opt-in: it activates only when a publishable key is provided
// (frontend/.env → VITE_CLERK_PUBLISHABLE_KEY). Without it the app runs in the
// no-login, single-default-tenant demo mode — nothing else changes.
export const clerkKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined
export const authEnabled = Boolean(clerkKey)

// Where somebody who cannot get in should write. Optional on purpose: an
// address invented in the source is worse than none, because it reads as a
// promise the product then fails to keep. Unset, the admission screen names
// eligo-tech and offers no link.
export const supportEmail =
  (import.meta.env.VITE_SUPPORT_EMAIL as string | undefined)?.trim() || undefined
