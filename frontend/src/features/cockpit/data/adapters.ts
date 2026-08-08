// Backend DTOs → cockpit view models.
//
// Same role as src/api/adapters.ts for the light views: keep the presentation
// layer stable while the data source moves. Everything produced here is tagged
// `live`; fields the backend has no concept of stay on the mock baseline.

import type {
  ApplicationDTO,
  CandidateDTO,
  CompanyDTO,
  DwellStageDTO,
  JobDTO,
  MatchResultDTO,
  PipelineBoardDTO,
} from '@/api/types'
import { buildSteps, PROCESS_STEPS } from './mock'
import { demo, live, type Figure, type JobScore, type ProcessCard } from './types'

/**
 * Backend `PipelineStage` → index of the furthest *done* step in the cockpit's
 * nine-step process (see PROCESS_STEPS in mock.ts).
 *
 * The mockup's process is the post-presentation half of a placement, so the three
 * pre-presentation stages and `rejected` have no card on this board and are
 * absent from this table. Steps between two anchors (Feedback, Vorbereitung,
 * Final-Vorb., Finaltermin) have no backend representation yet and therefore
 * render as pending.
 *
 * Widening backend/app/domain/common/enums.py::PipelineStage later is a
 * one-entry-per-stage change here and nothing else.
 */
export const STAGE_TO_STEP: Record<string, number> = {
  presented: 0, // Vorgestellt
  interview: 3, // … through Interview
  placed: 8, // all nine done
}

/** Stages that belong on "Laufende Prozesse" at all. */
export const isRunningStage = (stage: string): boolean => stage in STAGE_TO_STEP

/**
 * Placement fee as a share of the role's upper salary band. There is no fee model
 * in the backend, so this is a single named assumption rather than a figure
 * scattered through the UI — change it here, or delete it once real fee data
 * lands, and every Fee-Potenzial in the cockpit follows.
 */
export const FEE_RATE = 0.22

const feeFromJob = (job: JobDTO | undefined): Figure =>
  job?.salary_max
    ? demo(
        Math.round((job.salary_max * FEE_RATE) / 1000) * 1000,
        `${Math.round(FEE_RATE * 100)} % von € ${job.salary_max.toLocaleString('de-DE')} (Annahme, kein Honorarmodell)`,
      )
    : demo(0, 'Kein Gehaltsband am Mandat hinterlegt')

/** Short mandate reference from a uuid — "#A-1f4c" reads like the mockup's ids. */
const mandateRef = (jobId: string): string => `#A-${jobId.slice(0, 4)}`
const candidateRef = (candidateId: string): string => `#K-${candidateId.slice(0, 4)}`

/**
 * "Ø N T bis Offer" — how long the record says it takes to get from presentation
 * to an offer, summed over the dwell times of the stages in between.
 */
export function paceLabel(dwell: DwellStageDTO[]): { label: string; provenance: 'live' | 'demo' } {
  const relevant = dwell.filter((d) => d.key === 'presented' || d.key === 'interview')
  if (relevant.length === 0) return { label: 'Ø — T bis Offer', provenance: 'demo' }
  const days = Math.round(relevant.reduce((sum, d) => sum + d.avg_days, 0))
  return { label: `Ø ${days} T bis Offer`, provenance: 'live' }
}

/** Progress ring: share of the nine steps that are done. */
const progressFor = (reached: number): number =>
  Math.round(((reached + 1) / PROCESS_STEPS.length) * 100)

/**
 * Join the board against candidates, jobs and companies into process cards.
 * Applications whose stage is pre-presentation or rejected are dropped, matching
 * what the mockup's "Laufende Prozesse" actually shows.
 */
export function toProcessCards(
  board: PipelineBoardDTO,
  candidates: CandidateDTO[],
  jobs: JobDTO[],
  companies: CompanyDTO[],
  dwell: DwellStageDTO[],
): ProcessCard[] {
  const byCandidate = new Map(candidates.map((c) => [c.id, c]))
  const byJob = new Map(jobs.map((j) => [j.id, j]))
  const byCompany = new Map(companies.map((co) => [co.id, co]))
  const pace = paceLabel(dwell)

  const apps: ApplicationDTO[] = board.columns
    .filter((col) => isRunningStage(col.stage))
    .flatMap((col) => col.applications)

  return apps
    .map((app) => {
      const reached = STAGE_TO_STEP[app.stage]
      const candidate = byCandidate.get(app.candidate_id)
      const job = byJob.get(app.job_id)
      const company = job ? byCompany.get(job.client_company_id) : undefined
      // A placed application has nothing left to mark; anything earlier is
      // waiting on the next step.
      const marker = reached === PROCESS_STEPS.length - 1 ? 'pending' : 'current'

      return {
        id: app.id,
        candidateRef: candidateRef(app.candidate_id),
        candidateName: candidate?.full_name ?? 'Unbekannt',
        role: job?.title ?? candidate?.current_title ?? '—',
        mandateRef: job ? mandateRef(job.id) : '#A-????',
        client: company?.name ?? job?.location ?? '—',
        paceLabel: pace.label,
        pacePro: pace.provenance,
        progress: live(progressFor(reached), 'Aus der Pipeline-Stage abgeleitet'),
        fee: feeFromJob(job),
        steps: buildSteps(reached, marker),
      } satisfies ProcessCard
    })
    // Furthest along first, like the mockup.
    .sort((a, b) => b.progress.value - a.progress.value)
}

/**
 * Besetzbarkeit per mandate: the mean of the top three candidate match scores
 * that cleared the job's hard filters. Scoring the *pool* against the mandate is
 * exactly what "how fillable is this?" means, and it comes straight out of the
 * existing matching engine — deterministic filters first, ranking after.
 */
export function toJobScores(jobs: JobDTO[], matches: (MatchResultDTO[] | null)[]): JobScore[] {
  return jobs
    .map((job, i) => {
      const passing = (matches[i] ?? [])
        .filter((m) => m.passed_hard_filters)
        .sort((a, b) => b.score - a.score)
        .slice(0, 3)

      const score =
        passing.length > 0
          ? live(
              Math.round((passing.reduce((s, m) => s + m.score, 0) / passing.length) * 100),
              `Ø der ${passing.length} besten Matches, die alle harten Kriterien erfüllen`,
            )
          : live(0, 'Kein Kandidat erfüllt die harten Kriterien')

      return {
        id: job.id,
        mandateRef: mandateRef(job.id),
        title: job.title,
        score,
        // Both need a learned-signal store the backend does not have. Rendered
        // as "—" rather than invented.
        delta: null,
        managerChance: null,
      } satisfies JobScore
    })
    .sort((a, b) => b.score.value - a.score.value)
}
