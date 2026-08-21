// The cockpit shell: graph-paper background, command bar, and the screen switch.
//
// This replaces the sidebar + pill-tab shell. Screens are declared in one array,
// so extending the cockpit to further recruitment surfaces (Mandate, BD, …) means
// adding an entry plus a component — the navigator, hash routing and keyboard
// paging come along for free.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { CommandBar } from './CommandBar'
import { CockpitScreen, COCKPIT_SECTIONS } from './screens/CockpitScreen'
import { KandidatenScreen, KANDIDATEN_SECTIONS } from './screens/kandidaten/KandidatenScreen'
import { KandidatenweltScreen, KANDIDATENWELT_SECTIONS } from './screens/KandidatenweltScreen'
import { MarktScreen, MARKT_SECTIONS } from './screens/MarktScreen'
import { useCockpitData } from './data/useCockpitData'
import { useTypeface } from './useTypeface'

export type ScreenKey = 'cockpit' | 'kandidaten' | 'kandidatenwelt' | 'markt'

interface ScreenDef {
  key: ScreenKey
  /** Anchor ids in document order — what the navigator's ↑/↓ steps through. */
  sections: string[]
}

// Left to right, the drill-down the product tells: the whole book of business →
// the pool it draws on → one candidate's world → the market outside it.
export const SCREENS: ScreenDef[] = [
  { key: 'cockpit', sections: COCKPIT_SECTIONS },
  { key: 'kandidaten', sections: KANDIDATEN_SECTIONS },
  { key: 'kandidatenwelt', sections: KANDIDATENWELT_SECTIONS },
  { key: 'markt', sections: MARKT_SECTIONS },
]

export const isScreenKey = (v: string): v is ScreenKey =>
  SCREENS.some((s) => s.key === v)

export function CockpitShell({ initialScreen = 'cockpit' }: { initialScreen?: ScreenKey }) {
  const state = useCockpitData()
  const [typeface, setTypeface] = useTypeface()
  const [screen, setScreen] = useState<ScreenKey>(initialScreen)
  const [query, setQuery] = useState('')

  const index = SCREENS.findIndex((s) => s.key === screen)
  const sections = SCREENS[index].sections

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

  /** Scroll to the section before/after whichever one is nearest the top. */
  const stepSection = useCallback(
    (delta: 1 | -1) => {
      const tops = sections.map((id) => {
        const el = document.getElementById(id)
        return el ? el.getBoundingClientRect().top : Number.POSITIVE_INFINITY
      })
      // "Current" = the last section whose top is at or above the fold line.
      let current = 0
      tops.forEach((top, i) => {
        if (top <= 120) current = i
      })
      const target = Math.max(0, Math.min(sections.length - 1, current + delta))
      document.getElementById(sections[target])?.scrollIntoView({ behavior: 'smooth' })
    },
    [sections],
  )

  const nav = useMemo(
    () => ({
      onPrevScreen: () => index > 0 && goToScreen(SCREENS[index - 1].key),
      onNextScreen: () => index < SCREENS.length - 1 && goToScreen(SCREENS[index + 1].key),
      onPrevSection: () => stepSection(-1),
      onNextSection: () => stepSection(1),
      onReset: () => window.scrollTo({ top: 0, behavior: 'smooth' }),
      canPrevScreen: index > 0,
      canNextScreen: index < SCREENS.length - 1,
    }),
    [index, goToScreen, stepSection],
  )

  return (
    <div className="cockpit-root min-h-screen bg-cockpit-bg bg-grid bg-grid-cell font-sans text-cockpit-text">
      <CommandBar
        status={state.data.status}
        query={query}
        onQueryChange={setQuery}
        typeface={typeface}
        onTypefaceChange={setTypeface}
        nav={nav}
      />

      <main className="mx-auto max-w-[1560px] px-6 pb-24 pt-8">
        {screen === 'cockpit' && <CockpitScreen state={state} />}
        {screen === 'kandidaten' && <KandidatenScreen />}
        {screen === 'kandidatenwelt' && (
          <KandidatenweltScreen data={state.data.profileSale} />
        )}
        {screen === 'markt' && <MarktScreen />}
      </main>
    </div>
  )
}
