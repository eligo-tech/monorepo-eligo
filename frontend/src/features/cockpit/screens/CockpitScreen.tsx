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
import { MandateDrawer } from './MandateDrawer'
import { MandateView } from './MandateView'
import { cn } from '@/lib/cn'
import { useMemo } from 'react'

import { api } from '@/api/client'
import { useAsync } from '@/hooks/useAsync'
import { mandateFromJob } from '../data/adapters'
import type { CockpitState } from '../data/useCockpitData'
import type { ScreenKey } from '../CockpitShell'

export function CockpitScreen({
  state,
  mandateId,
  onSelectMandate,
  onGoToScreen,
}: {
  state: CockpitState
  /** The mandate in focus, from the hash. Null is the overall view. */
  mandateId?: string | null
  onSelectMandate?: (id: string | null) => void
  /** Jump to a neighbouring work surface (the design's compass). */
  onGoToScreen?: (screen: ScreenKey) => void
}) {
  const { data, live, reload } = state

  // Every mandate the workspace has, not only the nine someone is running
  // on: choosing a mandate to work ON is exactly the case where the process
  // list is empty. `/jobs` is the full set; the process-derived ones carry
  // the candidate counts, so they win on merge.
  const { data: allJobs } = useAsync(() => api.jobs().catch(() => []), [])
  const { data: allCompanies } = useAsync(() => api.companies().catch(() => []), [])

  const mandates = useMemo(() => {
    const byId = new Map(data.mandates.map((m) => [m.id, m]))
    const companyName = new Map((allCompanies ?? []).map((c) => [c.id, c.name]))
    for (const job of allJobs ?? []) {
      if (byId.has(job.id)) continue
      byId.set(job.id, mandateFromJob(job, companyName.get(job.client_company_id) ?? null))
    }
    return [...byId.values()]
  }, [data.mandates, allJobs, allCompanies])

  // The hash carries one id or several, comma-separated: `#cockpit/<id>` is
  // one mandate's workspace, `#cockpit/<id>,<id>` the overall view narrowed
  // to a shortlist picked on the Jobs screen.
  const selectedIds = useMemo(
    () => (mandateId ? mandateId.split(',').filter(Boolean) : []),
    [mandateId],
  )
  const selection = useMemo(
    () => mandates.filter((m) => selectedIds.includes(m.id)),
    [mandates, selectedIds],
  )
  const mandate = selectedIds.length === 1 ? selection[0] : undefined

  // The workspace's Stammdaten need the client record and its manager. Both
  // are fetched only while a mandate is in focus — the overall view has no
  // use for them, and the cockpit's rule is one failing call degrades one
  // panel, so each is settled to undefined rather than thrown.
  const company = (allCompanies ?? []).find((c) => c.id === mandate?.companyId)
  const { data: manager } = useAsync(
    () =>
      mandate?.companyId
        ? api
            .managers({ companyId: mandate.companyId, limit: 1 })
            .then((rows) => rows[0])
        : Promise.resolve(undefined),
    [mandate?.companyId],
  )

  const drawer = onSelectMandate ? (
    <MandateDrawer
      mandates={mandates}
      activeIds={selectedIds}
      onSelect={onSelectMandate}
    />
  ) : null

  // Several mandates: the book of business, narrowed to the shortlist. The
  // sections below read the same data, so only `mandates` changes — there is
  // no second "filtered cockpit" to keep in step with this one.
  if (selection.length > 1) {
    const shortlist = {
      ...data,
      mandates: selection,
      processes: selection.flatMap((m) => m.cards),
    }
    return (
      <div className="flex gap-5 xl:gap-7">
        {drawer}
        <div className="mx-auto min-w-0 max-w-[1560px] flex-1 space-y-10 px-6">
          <header className="flex flex-wrap items-center gap-3">
            <h1 className="text-[32px] font-semibold leading-tight tracking-tight text-cockpit-text">
              {selection.length} Mandate
            </h1>
            <span className="font-mono text-[12px] text-cockpit-faint">
              {selection.map((m) => m.title).join(' · ')}
            </span>
            <button
              type="button"
              onClick={() => onSelectMandate?.(null)}
              className="ml-auto font-mono text-[12px] text-cockpit-faint transition-colors hover:text-cockpit-text"
            >
              Auswahl aufheben
            </button>
          </header>

          <ProcessSection
            mandates={selection}
            isLive={live.processes}
            onChanged={reload}
            onOpenMandate={onSelectMandate}
          />
          <NextActionsSection actions={shortlist.actions} />
        </div>
      </div>
    )
  }

  // A hash can name a mandate that no longer exists — a deleted job, or a
  // link from another workspace. That gets a sentence, not an empty screen.
  if (mandateId && !mandate) {
    return (
      <div className="flex gap-5 xl:gap-7">
        {drawer}
        <p className="mx-auto min-w-0 max-w-[1560px] flex-1 px-6 text-[15px] text-cockpit-dim">
          Dieses Mandat gibt es in diesem Workspace nicht (mehr) — links eines
          auswählen.
        </p>
      </div>
    )
  }

  if (mandate) {
    return (
      <div className="flex gap-5 xl:gap-7">
        {drawer}
        <div className="mx-auto min-w-0 max-w-[1560px] flex-1 px-6">
          <MandateView
            mandate={mandate}
            company={company ?? undefined}
            manager={manager ?? undefined}
            onBack={() => onSelectMandate?.(null)}
            onChanged={reload}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-5 xl:gap-7">
      {drawer}

      <div className="mx-auto min-w-0 max-w-[1560px] flex-1 space-y-10 px-6">
        <header id="section-signals" className="scroll-mt-24">
          <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint-400">
            Kommandozentrale
          </span>
          <h1 className="mt-1.5 text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
            Cockpit
          </h1>
          <p className="mt-2 max-w-xl text-[16px] leading-relaxed text-cockpit-dim">
            Ein lebendiges System: es liest mit, hält jeden Prozess aktuell und erkennt, wo
            Umsatz entsteht.
          </p>
        </header>

        {/* The design's order, and it is an argument: what came in, what it is
            worth, where the work stands, what to do next — and only then the
            scoring, which is a view ON that work rather than part of it. */}
        <SignalsPanel signals={data.signals} />
        <RevenueSection slides={data.slides} closingIsLive={live.closing} />
        <ProcessSection
          mandates={data.mandates}
          isLive={live.processes}
          onChanged={reload}
          onOpenMandate={onSelectMandate}
        />
        <NextActionsSection actions={data.actions} />
        <JobScoringSection rows={data.jobScores} isLive={live.jobScores} />
        <CompetitionSection />
        <WorldStrip onGo={onGoToScreen} />
      </div>
    </div>
  )
}

/**
 * The design's compass, flattened into a strip: the work surfaces that sit
 * around the cockpit. The directions are the mock's own (→ Kandidatenwelt,
 * ← Business Development, ↑ Mandat & Kandidatensuche), kept so the two read
 * as one product even though this app routes by hash rather than by grid.
 */
function WorldStrip({ onGo }: { onGo?: (screen: ScreenKey) => void }) {
  if (!onGo) return null
  const WORLDS: { screen: ScreenKey; dir: string; label: string; dot: string }[] = [
    { screen: 'kandidaten', dir: '→', label: 'Kandidatenwelt', dot: 'bg-coral-400' },
    { screen: 'markt', dir: '←', label: 'Business Development', dot: 'bg-gold-400' },
    { screen: 'jobs', dir: '↑', label: 'Mandat & Kandidatensuche', dot: 'bg-lav-400' },
  ]
  return (
    <div className="flex flex-wrap gap-2.5 border-t border-cockpit-line pt-5">
      {WORLDS.map((world) => (
        <button
          key={world.screen}
          type="button"
          onClick={() => onGo(world.screen)}
          className="flex items-center gap-2 rounded-lg border border-cockpit-line bg-cockpit-surface px-3.5 py-2.5 text-[12.5px] text-cockpit-text transition-all hover:-translate-y-0.5 hover:border-cockpit-edge"
        >
          <span className={cn('h-2.5 w-2.5 rounded-[3px]', world.dot)} />
          <span className="font-mono text-[12px] text-cockpit-faint">{world.dir}</span>
          {world.label}
        </button>
      ))}
    </div>
  )
}

