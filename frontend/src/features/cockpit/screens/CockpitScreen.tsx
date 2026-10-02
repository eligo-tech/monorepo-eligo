// The main cockpit scroll: what the system noticed, then where revenue stands,
// then which mandates are fillable, then the live processes, then what to do next.
//
// Two views, one screen. "Gesamt" is the book of business; picking a mandate
// narrows everything to that search (MandateView). The choice lives in the
// URL hash — `#cockpit/<jobId>` — so a per-job view can be sent to a
// colleague instead of described to them.

import { CompetitionSection } from '../sections/CompetitionSection'
import { JobScoringSection } from '../sections/JobScoringSection'
import { NextActionsSection } from '../sections/NextActionsSection'
import { ProcessSection } from '../sections/ProcessSection'
import { RevenueSection } from '../sections/RevenueSection'
import { SignalsPanel } from '../sections/SignalsPanel'
import { MandateView } from './MandateView'
import { cn } from '@/lib/cn'
import type { CockpitState } from '../data/useCockpitData'

export function CockpitScreen({
  state,
  mandateId,
  onSelectMandate,
}: {
  state: CockpitState
  /** The mandate in focus, from the hash. Null is the overall view. */
  mandateId?: string | null
  onSelectMandate?: (id: string | null) => void
}) {
  const { data, live, reload } = state
  const mandate = mandateId
    ? data.mandates.find((m) => m.id === mandateId)
    : undefined

  // A hash can name a mandate with nobody in play — a job opened from the
  // Jobs list before its first candidate is presented — or one that has
  // finished. Both get a sentence, not an empty screen.
  if (mandateId && !mandate) {
    return (
      <>
        <MandateSwitch
          state={state}
          mandateId={null}
          onSelectMandate={onSelectMandate}
        />
        <p className="mt-6 text-[15px] text-cockpit-dim">
          Für dieses Mandat läuft noch kein Prozess — sobald ein Kandidat
          vorgestellt ist, erscheint er hier.
        </p>
      </>
    )
  }

  if (mandate) {
    return (
      <>
        <MandateSwitch
          state={state}
          mandateId={mandateId ?? null}
          onSelectMandate={onSelectMandate}
        />
        <div className="mt-8">
          <MandateView
            mandate={mandate}
            onBack={() => onSelectMandate?.(null)}
            onChanged={reload}
          />
        </div>
      </>
    )
  }

  return (
    <>
      <MandateSwitch state={state} mandateId={null} onSelectMandate={onSelectMandate} />

      <div className="mt-8 space-y-10">
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
        <ProcessSection
          cards={data.processes}
          isLive={live.processes}
          onChanged={reload}
          onOpenMandate={onSelectMandate}
        />
        <CompetitionSection />
        <NextActionsSection actions={data.actions} />
      </div>
    </>
  )
}

/**
 * Gesamt ⇄ one mandate.
 *
 * A row of chips rather than a dropdown: the mandates ARE the book of
 * business, and a recruiter should see how many searches are running without
 * opening anything. It scrolls horizontally once there are more than a screen
 * holds, which is the same thing the tracker does on paper.
 */
function MandateSwitch({
  state,
  mandateId,
  onSelectMandate,
}: {
  state: CockpitState
  mandateId: string | null
  onSelectMandate?: (id: string | null) => void
}) {
  const { mandates } = state.data
  if (!onSelectMandate || mandates.length === 0) return null

  return (
    <div className="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-1">
      <ViewChip
        active={mandateId === null}
        onClick={() => onSelectMandate(null)}
        label="Gesamt"
      />
      <span className="mx-1 h-4 w-px shrink-0 bg-cockpit-line" />
      {mandates.map((m) => (
        <ViewChip
          key={m.id}
          active={m.id === mandateId}
          onClick={() => onSelectMandate(m.id)}
          label={`${m.client} · ${m.title}`}
          count={m.cards.length}
        />
      ))}
    </div>
  )
}

function ViewChip({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean
  onClick: () => void
  label: string
  count?: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'shrink-0 whitespace-nowrap rounded-lg border px-3 py-1.5 font-mono text-[12px] transition-colors',
        active
          ? 'border-cockpit-edge bg-white/[0.07] text-cockpit-text'
          : 'border-cockpit-line text-cockpit-dim hover:text-cockpit-text',
      )}
    >
      {label}
      {count !== undefined && (
        <span className="ml-1.5 text-cockpit-faint">{count}</span>
      )}
    </button>
  )
}
