// The cockpit shell: graph-paper background, command bar, and the screen switch.
//
// Screens are declared in one array and reached by name from the Section picker
// in the command bar. Adding a surface means adding an entry plus a component;
// hash routing comes along for free.
//
// The arrow-cluster Navigator this used to carry is gone: paging blindly through
// screens to reach one you wanted is worse than choosing it from a list.

import { useCallback, useEffect, useState } from 'react'
import { CommandBar } from './CommandBar'
import { CockpitScreen } from './screens/CockpitScreen'
import { KandidatenScreen } from './screens/kandidaten/KandidatenScreen'
import { JobsScreen } from './screens/JobsScreen'
import { ManagerScreen } from './screens/ManagerScreen'
import { MarktScreen } from './screens/MarktScreen'
import type { SectionOption } from './SectionPicker'
import { useCockpitData } from './data/useCockpitData'
import { useTypeface } from './useTypeface'

export type ScreenKey = 'cockpit' | 'markt' | 'managers' | 'jobs' | 'kandidaten'

// The order the product reads in: the book of business, then the market it
// draws on, then the people and mandates inside it.
export const SCREENS: SectionOption<ScreenKey>[] = [
  { key: 'cockpit', label: 'Cockpit' },
  { key: 'markt', label: 'Markt' },
  { key: 'managers', label: 'Manager', placeholder: true },
  { key: 'jobs', label: 'Jobs' },
  { key: 'kandidaten', label: 'Kandidaten' },
]

export const isScreenKey = (v: string): v is ScreenKey =>
  SCREENS.some((s) => s.key === v)

export function CockpitShell({ initialScreen = 'cockpit' }: { initialScreen?: ScreenKey }) {
  const state = useCockpitData()
  const [typeface, setTypeface] = useTypeface()
  const [screen, setScreen] = useState<ScreenKey>(initialScreen)
  const [query, setQuery] = useState('')

  const goToScreen = useCallback((next: ScreenKey) => {
    setScreen(next)
    window.location.hash = next
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  // Keep in step with back/forward and hash edits.
  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace('#', '')
      if (isScreenKey(h)) setScreen(h)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <div className="cockpit-root min-h-screen bg-cockpit-bg bg-grid bg-grid-cell font-sans text-cockpit-text">
      <CommandBar
        status={state.data.status}
        query={query}
        onQueryChange={setQuery}
        typeface={typeface}
        onTypefaceChange={setTypeface}
        screens={SCREENS}
        screen={screen}
        onScreenChange={goToScreen}
      />

      <main className="mx-auto max-w-[1560px] px-6 pb-24 pt-8">
        {screen === 'cockpit' && <CockpitScreen state={state} />}
        {screen === 'markt' && <MarktScreen />}
        {screen === 'managers' && <ManagerScreen />}
        {screen === 'jobs' && <JobsScreen />}
        {screen === 'kandidaten' && <KandidatenScreen />}
      </main>
    </div>
  )
}
