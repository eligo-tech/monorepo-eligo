import { useEffect, useState } from 'react'
import { Sidebar } from './components/Sidebar'
import { TopNav, type Tab } from './components/TopNav'
import { CandidatesView } from './features/candidates/CandidatesView'
import { MatchingView } from './features/matching/MatchingView'
import { PipelineView } from './features/pipeline/PipelineView'
import { ReportingView } from './features/reporting/ReportingView'
import { LandingPage } from './landing/LandingPage'

// Maps the active tab to the record highlighted in the sidebar rail.
const sidebarKeyForTab: Record<Tab, string> = {
  Kandidaten: 'Kandidaten',
  Matching: 'Kandidaten',
  Pipeline: 'Jobs',
  Reporting: 'Berichte',
}

const TABS: Tab[] = ['Kandidaten', 'Matching', 'Pipeline', 'Reporting']

const hashTab = (): Tab | null => {
  const h = decodeURIComponent(window.location.hash.replace('#', '')) as Tab
  return TABS.includes(h) ? h : null
}

export default function App() {
  // Marketing landing page at "/"; the dashboard shows once a tab hash is set.
  const [route, setRoute] = useState<Tab | null>(hashTab)

  useEffect(() => {
    const onHash = () => setRoute(hashTab())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  if (route === null) {
    return <LandingPage onEnterApp={() => (window.location.hash = 'Kandidaten')} />
  }

  return <Dashboard tab={route} />
}

function Dashboard({ tab: initial }: { tab: Tab }) {
  const [tab, setTab] = useState<Tab>(initial)
  const [lang, setLang] = useState<'DE' | 'EN'>('DE')

  const changeTab = (t: Tab) => {
    setTab(t)
    window.location.hash = t
  }

  return (
    <div className="flex h-screen gap-3 overflow-hidden bg-page p-3">
      <Sidebar activeKey={sidebarKeyForTab[tab]} />

      <main className="relative flex-1 overflow-hidden">
        <TopNav active={tab} onChange={changeTab} lang={lang} onLangChange={setLang} />

        <div className="h-full overflow-hidden rounded-card bg-white shadow-card">
          {tab === 'Kandidaten' && <CandidatesView />}
          {tab === 'Matching' && <MatchingView />}
          {tab === 'Pipeline' && <PipelineView />}
          {tab === 'Reporting' && <ReportingView />}
        </div>
      </main>
    </div>
  )
}