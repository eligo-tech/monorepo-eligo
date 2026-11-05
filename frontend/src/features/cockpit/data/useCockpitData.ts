// Hybrid loader for the cockpit.
//
// `data` is never null, so the surface renders on first paint. The baseline is
// the mock book in the no-login demo build and an EMPTY workspace once someone
// is signed in (see `cockpitBaseline`). Live calls then overlay the sections the
// API can actually serve, per section — one failing endpoint degrades one
// section, not the screen.

import { useCallback, useState } from 'react'

import { useAsync } from '@/hooks/useAsync'
import { api } from '@/api/client'
import { authEnabled } from '@/auth/config'
import type { JobDTO, MatchResultDTO } from '@/api/types'
import { MOCK_COCKPIT } from './mock'
import {
  closingDealsFromCards,
  mandatesFromCards,
  processCardsFromSteps,
  toJobScores,
  toProcessCards,
} from './adapters'
import type { ClosingDeal, CockpitData, Figure } from './types'
import { isLive } from '../ui/jobStatus'

/** Which sections are showing live data — drives the section-header hints. */
export interface LiveSections {
  processes: boolean
  jobScores: boolean
  /** "Kurz vor Abschluss" — real runs past their final appointment. */
  closing: boolean
  /** A real workspace whose processes could not be loaded at all. */
  unavailable: boolean
  /** A real workspace whose Jobscoring could not be computed. */
  scoresUnavailable: boolean
}

export interface CockpitState {
  data: CockpitData
  loading: boolean
  live: LiveSections
  /** Re-fetch after a write, so an edited step shows its new state without a
   *  page reload. */
  reload: () => void
}

/**
 * Jobscoring needs one /matching/job call per mandate. The mockup shows eight
 * rows, so we score the eight most recent open mandates and leave the rest off
 * the board rather than firing an unbounded number of requests.
 */
const JOBSCORING_LIMIT = 8

const settled = async <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null)

/** The calls the cockpit makes — a parameter so a test can stand in for it. */
export type CockpitClient = Pick<
  typeof api,
  'processes' | 'board' | 'candidates' | 'jobs' | 'companies' | 'reportingOverview' | 'matchJob'
>

/** What the cockpit shows before (or without) live data.
 *
 *  The demo build keeps the full mock book. A signed-in workspace starts
 *  empty instead: a demo card there looks like a real process but has nothing
 *  behind it to save to, so an empty workspace read as "this user cannot
 *  edit". Revenue figures and the change count have no backend yet, so
 *  they read zero rather than an invented number. */
export function cockpitBaseline(demo: boolean): CockpitData {
  if (demo) return { ...MOCK_COCKPIT }
  return {
    ...MOCK_COCKPIT,
    status: { ...MOCK_COCKPIT.status, pendingChanges: zero(MOCK_COCKPIT.status.pendingChanges) },
    signals: [],
    actions: [],
    processes: [],
    mandates: [],
    jobScores: [],
    slides: withClosing(MOCK_COCKPIT.slides, []).map((slide) =>
      slide.panels
        ? {
            ...slide,
            panels: Object.fromEntries(
              Object.entries(slide.panels).map(([key, panel]) => [
                key,
                {
                  ...panel,
                  actual: zero(panel.actual),
                  potential: zero(panel.potential),
                  target: zero(panel.target),
                  yearActual: zero(panel.yearActual),
                  yearTarget: zero(panel.yearTarget),
                  pipelineTotal: zero(panel.pipelineTotal),
                  pipelineWeighted: zero(panel.pipelineWeighted),
                },
              ]),
            ) as typeof slide.panels,
          }
        : slide,
    ),
  }
}

/** A demo figure with nothing in it — keeps its "Demo" provenance, drops the
 *  invented number. */
const zero = (figure: Figure): Figure => ({ ...figure, value: 0 })

/** The same "Kurz vor Abschluss" list on every period: it is a state of the
 *  process, not of the month being looked at. */
function withClosing(slides: CockpitData['slides'], closing: ClosingDeal[]) {
  return slides.map((slide) =>
    slide.panels
      ? {
          ...slide,
          panels: Object.fromEntries(
            Object.entries(slide.panels).map(([key, panel]) => [key, { ...panel, closing }]),
          ) as typeof slide.panels,
        }
      : slide,
  )
}

export async function loadCockpit(
  client: CockpitClient,
  demo: boolean,
): Promise<Omit<CockpitState, 'reload'>> {
  const [processes, board, candidates, jobs, companies, reporting] = await Promise.all([
    settled(client.processes()),
    settled(client.board()),
    settled(client.candidates()),
    settled(client.jobs()),
    settled(client.companies()),
    settled(client.reportingOverview()),
  ])

  const data: CockpitData = cockpitBaseline(demo)
  const live: LiveSections = {
    processes: false,
    jobScores: false,
    closing: false,
    unavailable: false,
    scoresUnavailable: false,
  }

  // ── 03 Laufende Prozesse ──
  // Two sources, in order of fidelity. The recruiter's tracker
  // (`/pipeline/processes`) carries a row per step with its date and verdict,
  // so cards can show what actually happened. Where a workspace has
  // applications but no steps yet, the coarse board join still produces cards
  // from the Kanban stage alone. An empty result leaves the baseline: demo
  // cards in the demo build, an empty board in a real workspace.
  const fromSteps = processes ? processCardsFromSteps(processes, reporting?.dwell ?? []) : []
  if (fromSteps.length > 0) {
    data.processes = fromSteps
    live.processes = true
  } else if (board && candidates && jobs && companies) {
    const cards = toProcessCards(board, candidates, jobs, companies, reporting?.dwell ?? [])
    if (cards.length > 0) {
      data.processes = cards
      live.processes = true
    }
  }

  // The tracker did not answer and the board had nothing to stand in for it:
  // say so, rather than an empty board that reads as "nothing is running".
  if (!demo && !live.processes && !processes) {
    live.unavailable = true
  }

  // The per-job view groups whatever cards we ended up with — live ones carry
  // their mandate's Suchprofil, demo ones group by their ref alone.
  data.mandates = mandatesFromCards(data.processes, processes ?? [])

  // ── 01 Kurz vor Abschluss ──
  // Derived from the same cards: a process past its final appointment and
  // short of a contract. Same rule as everywhere in this file — live if there
  // is anything to show, otherwise the baseline stays. The fee and the chance remain `demo` either way: no Honorarmodell,
  // no signal store.
  const closing = closingDealsFromCards(data.processes)
  if (closing.length > 0) {
    data.slides = withClosing(data.slides, closing)
    live.closing = true
  }

  // ── 02 Jobscoring ──
  if (jobs) {
    // Live business, via the one helper that knows the vocabulary. This read
    // `=== 'open'`, which silently left out every mandate somebody had marked
    // as actively worked — the jobscoring section then scored the quietest
    // mandates in the book.
    const open: JobDTO[] = jobs
      .filter((j) => isLive(j.status))
      .slice(0, JOBSCORING_LIMIT)
    if (open.length > 0) {
      const matches: (MatchResultDTO[] | null)[] = await Promise.all(
        open.map((j) => settled(client.matchJob(j.id))),
      )
      if (matches.some((m) => m !== null)) {
        data.jobScores = toJobScores(open, matches)
        live.jobScores = true
      } else if (!demo) {
        live.scoresUnavailable = true
      }
    }
  }

  if (!jobs && !demo) live.scoresUnavailable = true

  return { data, loading: false, live }
}

/** Cockpit data: the demo floor in the no-login demo build, an empty
 *  workspace otherwise, progressively overlaid with live values. */
export function useCockpitData(): CockpitState {
  const [key, setKey] = useState(0)
  const demo = !authEnabled
  // keepPrevious: a reload after a step edit keeps the cards on screen until
  // the fresh ones arrive, instead of blanking to "noch kein Prozess".
  const { data, loading } = useAsync(() => loadCockpit(api, demo), [key], {
    keepPrevious: true,
  })
  const reload = useCallback(() => setKey((k) => k + 1), [])
  if (!data)
    return {
      data: cockpitBaseline(demo),
      loading,
      live: {
        processes: false,
        jobScores: false,
        closing: false,
        unavailable: false,
        scoresUnavailable: false,
      },
      reload,
    }
  return { ...data, loading, reload }
}
