import React from 'react'
import ReactDOM from 'react-dom/client'
import { ClerkProvider } from '@clerk/clerk-react'
import App from './App'
import { clerkKey } from './auth/config'
import { ClerkTokenBridge } from './auth/ClerkTokenBridge'
import './index.css'

// With a Clerk key, wrap in ClerkProvider + bridge the session token into the
// API client. Without one, render the app bare (no-login demo mode).
const tree = clerkKey ? (
  <ClerkProvider
    publishableKey={clerkKey}
    afterSignOutUrl="/"
    // After sign-in/up, land in the app (Kandidaten) — not back on the marketing page.
    signInForceRedirectUrl="/#Kandidaten"
    signUpForceRedirectUrl="/#Kandidaten"
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
