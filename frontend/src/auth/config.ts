// Clerk auth is opt-in: it activates only when a publishable key is provided
// (frontend/.env → VITE_CLERK_PUBLISHABLE_KEY). Without it the app runs in the
// no-login, single-default-tenant demo mode — nothing else changes.
export const clerkKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined
export const authEnabled = Boolean(clerkKey)
