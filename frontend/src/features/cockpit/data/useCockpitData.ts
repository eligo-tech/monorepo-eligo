// Hybrid loader for the cockpit.
//
// The mock baseline is the floor: `data` is never null, so the surface renders
// completely on first paint and stays intact if the backend is down. Live calls
// then overlay the sections the API can actually serve, per section — one failing
// endpoint degrades one section, not the screen.

import { useAsync } from '@/hooks/useAsync'
import { api } from '@/api/client'
import type { JobDTO, MatchResultDTO } from '@/api/types'
import { MOCK_COCKPIT } from './mock'
import { toJobScores, toProcessCards } from './adapters'
import type { CockpitData } from './types'

/** Which sections are showing live data — drives the section-header hints. */
export interface LiveSections {
  processes: boolean
  jobScores: boolean
}

export interface CockpitState {
  data: CockpitData
  loading: boolean
  live: LiveSections
}

/**
 * Jobscoring needs one /matching/job call per mandate. The mockup shows eight
 * rows, so we score the eight most recent open mandates and leave the rest off
 * the board rather than firing an unbounded number of requests.
 */
const JOBSCORING_LIMIT = 8

const settled = async <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null)

async function loadCockpit(): Promise<CockpitState> {
  const [board, candidates, jobs, companies, reporting] = await Promise.all([
    settled(api.board()),
    settled(api.candidates()),
    settled(api.jobs()),
    settled(api.companies()),
    settled(api.reportingOverview()),
  ])

  const data: CockpitData = { ...MOCK_COCKPIT }
  const live: LiveSections = { processes: false, jobScores: false }

  // ── 03 Laufende Prozesse ──
  // Needs the board plus the records it references. An empty join (no
  // presented/interview/placed applications yet) keeps the demo cards rather
  // than showing an empty board.
  if (board && candidates && jobs && companies) {
    const cards = toProcessCards(board, candidates, jobs, companies, reporting?.dwell ?? [])
    if (cards.length > 0) {
      data.processes = cards
      live.processes = true
    }
  }

  // ── 02 Jobscoring ──
  if (jobs) {
    const open: JobDTO[] = jobs
      .filter((j) => j.status === 'open')
      .slice(0, JOBSCORING_LIMIT)
    if (open.length > 0) {
      const matches: (MatchResultDTO[] | null)[] = await Promise.all(
        open.map((j) => settled(api.matchJob(j.id))),
      )
      if (matches.some((m) => m !== null)) {
        data.jobScores = toJobScores(open, matches)
        live.jobScores = true
      }
    }
  }

  return { data, loading: false, live }
}

const FALLBACK: CockpitState = {
  data: MOCK_COCKPIT,
  loading: true,
  live: { processes: false, jobScores: false },
}

/** Cockpit data, mock-backed and progressively overlaid with live values. */
export function useCockpitData(): CockpitState {
  const { data, loading } = useAsync(loadCockpit, [])
  if (!data) return { ...FALLBACK, loading }
  return { ...data, loading }
}
