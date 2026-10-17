import React from 'react'
import ReactDOM from 'react-dom/client'
import { ClerkProvider } from '@clerk/clerk-react'
import App from './App'
import { clerkKey } from './auth/config'
import { ClerkTokenBridge } from './auth/ClerkTokenBridge'
import { initLang } from './i18n'
// Self-hosted faces for the cockpit typeface switch (no CDN at runtime).
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/700.css'
import './index.css'

// Tell the document which language it is in. The language itself was
// already decided when `src/i18n` was first imported — before any module
// could call `t()` while loading — so this only sets <html lang>.
initLang()

// With a Clerk key, wrap in ClerkProvider + bridge the session token into the
// API client. Without one, render the app bare (no-login demo mode).
const tree = clerkKey ? (
  <ClerkProvider
    publishableKey={clerkKey}
    afterSignOutUrl="/"
    // After sign-in/up, land in the app (Kandidaten) — not back on the marketing page.
    signInForceRedirectUrl="/#cockpit"
    signUpForceRedirectUrl="/#cockpit"
  >
    <ClerkTokenBridge />
    <App />
  </ClerkProvider>
) : (
  <App />
)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{tree}</React.StrictMode>,
)
