// The cockpit shell: graph-paper background, command bar, and the screen switch.
//
// Screens are declared in one array and reached by name from the Section picker
// in the command bar. Adding a surface means adding an entry plus a component;
// hash routing comes along for free.
//
// The arrow-cluster Navigator this used to carry is gone: paging blindly through
// screens to reach one you wanted is worse than choosing it from a list.

import { useCallback, useEffect, useState } from 'react'
import { cn } from '@/lib/cn'
import { CommandBar } from './CommandBar'
import { CockpitScreen } from './screens/CockpitScreen'
import { KandidatenScreen } from './screens/kandidaten/KandidatenScreen'
import { EinstellungenScreen } from './screens/EinstellungenScreen'
import { JobsScreen } from './screens/JobsScreen'
import { ManagerScreen } from './screens/ManagerScreen'
import { MarktScreen } from './screens/MarktScreen'
import { ProjekteScreen } from './screens/ProjekteScreen'
import type { SectionOption } from './SectionPicker'
import { useCockpitData } from './data/useCockpitData'
import { useMe } from './useMe'
import { useTypeface } from './useTypeface'

export type ScreenKey =
  | 'cockpit'
  | 'markt'
  | 'projekte'
  | 'managers'
  | 'jobs'
  | 'kandidaten'
  | 'einstellungen'

// The order the product reads in: the book of business, then the market it
// draws on, then the part of it this workspace watches — the funnel from
// "who is hiring" to "who do I call" — then the people and mandates inside it.
export const SCREENS: SectionOption<ScreenKey>[] = [
  { key: 'cockpit', label: 'Cockpit' },
  { key: 'markt', label: 'Markt' },
  { key: 'projekte', label: 'Projekte' },
  { key: 'managers', label: 'Manager', placeholder: true },
  { key: 'jobs', label: 'Jobs' },
  { key: 'kandidaten', label: 'Kandidaten' },
  { key: 'einstellungen', label: 'Einstellungen' },
]

export const isScreenKey = (v: string): v is ScreenKey =>
  SCREENS.some((s) => s.key === v)

/** Links and bookmarks from before Projekte replaced the flat Workspace list.
 *  One line is cheaper than a dead hash that silently lands on the cockpit. */
const RETIRED: Record<string, ScreenKey> = { workspace: 'projekte' }

/** `#cockpit/<jobId>`: the screen, then what it is focused on.
 *
 *  The per-job view belongs in the URL. A recruiter sends a colleague "look at
 *  the EM-Software search", and a view that exists only in component state can
 *  only be described, never linked. */
export const resolveScreen = (hash: string): ScreenKey | null => {
  const base = hash.split('/')[0]
  return isScreenKey(base) ? base : (RETIRED[base] ?? null)
}

/** The part after the screen, if any — today a mandate id on `#cockpit`. */
export const resolveDetail = (hash: string): string | null =>
  hash.split('/').slice(1).join('/') || null

export function CockpitShell({ initialScreen = 'cockpit' }: { initialScreen?: ScreenKey }) {
  const state = useCockpitData()
  const [typeface, setTypeface] = useTypeface()
  const me = useMe()
  const [screen, setScreen] = useState<ScreenKey>(initialScreen)
  const [detail, setDetail] = useState<string | null>(() =>
    resolveDetail(window.location.hash.replace('#', '')),
  )
  const [query, setQuery] = useState('')

  const goToScreen = useCallback((next: ScreenKey) => {
    setScreen(next)
    setDetail(null)
    window.location.hash = next
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  /** Focus one mandate inside the cockpit, or go back to the overall view. */
  const goToMandate = useCallback((id: string | null) => {
    setDetail(id)
    window.location.hash = id ? `cockpit/${id}` : 'cockpit'
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  /** Open or close a candidate record without leaving the screen. */
  const goToCandidate = useCallback((id: string | null) => {
    setDetail(id)
    window.location.hash = id ? `kandidaten/${id}` : 'kandidaten'
  }, [])

  // Keep in step with back/forward and hash edits.
  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace('#', '')
      const next = resolveScreen(h)
      if (next) {
        setScreen(next)
        setDetail(resolveDetail(h))
      }
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <div className="cockpit-root min-h-screen bg-cockpit-bg bg-grid bg-grid-cell font-sans text-cockpit-text">
      <CommandBar
        status={state.data.status}
        me={me}
        query={query}
        onQueryChange={setQuery}
        searchHint={
          screen === 'jobs' ? 'Mandate filtern: Firma, Titel, Ort …' : undefined
        }
        typeface={typeface}
        onTypefaceChange={setTypeface}
        screens={SCREENS}
        screen={screen}
        onScreenChange={goToScreen}
      />

      {/* The cockpit carries a left rail, which has to reach the window edge
          — a sidebar that starts where a centred container starts is a column
          floating in the page. So that screen gets the full width and places
          its own gutters; every other screen stays centred. */}
      <main
        className={cn(
          'pb-24 pt-8',
          screen === 'cockpit' ? 'px-0' : 'mx-auto max-w-[1560px] px-6',
        )}
      >
        {screen === 'cockpit' && (
          <CockpitScreen
            state={state}
            mandateId={detail}
            onSelectMandate={goToMandate}
            onGoToScreen={goToScreen}
          />
        )}
        {screen === 'markt' && <MarktScreen />}
        {screen === 'projekte' && <ProjekteScreen />}
        {screen === 'managers' && <ManagerScreen />}
        {screen === 'jobs' && (
          <JobsScreen query={query} onClearQuery={() => setQuery('')} />
        )}
        {screen === 'kandidaten' && (
          <KandidatenScreen
            candidateId={detail}
            onCandidateChange={goToCandidate}
          />
        )}
        {screen === 'einstellungen' && <EinstellungenScreen me={me} />}
      </main>
    </div>
  )
}
