// The main cockpit scroll: what the system noticed, then where revenue stands,
// then which mandates are fillable, then the live processes, then what to do next.

import { JobScoringSection } from '../sections/JobScoringSection'
import { NextActionsSection } from '../sections/NextActionsSection'
import { ProcessSection } from '../sections/ProcessSection'
import { RevenueSection } from '../sections/RevenueSection'
import { SignalsPanel } from '../sections/SignalsPanel'
import type { CockpitState } from '../data/useCockpitData'

export function CockpitScreen({ state }: { state: CockpitState }) {
  const { data, live } = state

  return (
    <div className="space-y-10">
      <header id="section-signals" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Cockpit
        </h1>
        <p className="mt-2 max-w-xl text-[16px] leading-relaxed text-cockpit-dim">
          Ein lebendiges System: es liest mit, hält jeden Prozess aktuell und erkennt, wo
          Umsatz entsteht.
        </p>
      </header>

      <SignalsPanel signals={data.signals} />
      <RevenueSection slides={data.slides} />
      <JobScoringSection rows={data.jobScores} isLive={live.jobScores} />
      <ProcessSection cards={data.processes} isLive={live.processes} />
      <NextActionsSection actions={data.actions} />
    </div>
  )
}
