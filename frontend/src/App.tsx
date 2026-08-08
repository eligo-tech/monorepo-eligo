import { useEffect, useState } from 'react'
import { CockpitShell, isScreenKey, type ScreenKey } from './features/cockpit/CockpitShell'
import { LandingPage } from './landing/LandingPage'
import { authEnabled } from './auth/config'
import { AuthGate } from './auth/AuthGate'

const DEFAULT_SCREEN: ScreenKey = 'cockpit'

/** Which cockpit screen the URL asks for; null means the marketing landing page. */
const hashScreen = (): ScreenKey | null => {
  const h = decodeURIComponent(window.location.hash.replace('#', ''))
  return isScreenKey(h) ? h : null
}

export default function App() {
  // Marketing landing page at "/"; the cockpit shows once a screen hash is set.
  const [route, setRoute] = useState<ScreenKey | null>(hashScreen)

  useEffect(() => {
    const onHash = () => setRoute(hashScreen())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  if (route === null) {
    // Landing stays public in both modes.
    return <LandingPage onEnterApp={() => (window.location.hash = DEFAULT_SCREEN)} />
  }

  // With Clerk on, the cockpit requires sign-in + an active organization (tenant).
  return authEnabled ? (
    <AuthGate>
      <CockpitShell initialScreen={route} />
    </AuthGate>
  ) : (
    <CockpitShell initialScreen={route} />
  )
}
