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
  ProcessCandidateDTO,
  ProcessJobDTO,
  ProcessStepDTO,
} from '@/api/types'
import { buildSteps, PROCESS_STEPS } from './mock'
import {
  demo,
  live,
  type CandidateAssessment,
  type Figure,
  type JobScore,
  type Mandate,
  type ProcessCard,
  type ProcessStep,
} from './types'

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
  const days = Math.round(relevant.reduce((sum, d) => sum + d.avg_days, 0))
  // Zero is not a measurement: with one week of imported history the dwell
  // query returns rows whose average is 0, and "Ø 0 T bis Offer" reads like a
  // claim that placements are instant.
  if (relevant.length === 0 || days === 0) {
    return { label: 'Ø — T bis Offer', provenance: 'demo' }
  }
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
        jobId: job?.id,
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
 * Cards from the recruiter's own tracker (`/pipeline/processes`).
 *
 * This is the faithful path: the backend stores a row per step with its date
 * and its verdict, so a card can say "presented 28.07., interview 14.08.,
 * client said yes, final 17.09." instead of the single word "interview".
 * `toProcessCards` above is the older, coarser join and stays for workspaces
 * that have applications but no steps yet.
 *
 * Three states carry the tracker's meaning: a green cell is `done`, a red one
 * is `out` (the process ended there), and the first unfinished step after the
 * last done one is what we are waiting on.
 */
export function processCardsFromSteps(
  processes: ProcessJobDTO[],
  dwell: DwellStageDTO[],
): ProcessCard[] {
  const pace = paceLabel(dwell)
  const cards: ProcessCard[] = []

  for (const job of processes) {
    for (const person of job.candidates) {
      const byKey = new Map(person.steps.map((s) => [s.step_key, s]))
      const out = person.steps.find((s) => s.outcome === 'out')

      // Walk the canonical nine, then append any extra interview round the
      // tracker recorded (a third appointment) right after the final one.
      const keys: string[] = PROCESS_STEPS.map((s) => s.key)
      const extra = person.steps
        .map((s) => s.step_key)
        .filter((k) => k.startsWith('interviewtermin_'))
        .sort()
      keys.splice(keys.indexOf('finaltermin') + 1, 0, ...extra)

      let reached = -1
      const steps: ProcessStep[] = keys.map((key, i) => {
        const row = byKey.get(key)
        const label =
          row?.label ?? PROCESS_STEPS.find((s) => s.key === key)?.label ?? key
        const done = !!row && (row.done_at !== null || row.outcome === 'pass')
        if (done) reached = i
        const state: ProcessStep['state'] =
          row?.outcome === 'out' ? 'out' : done ? 'done' : 'pending'
        return {
          key: key as ProcessStep['key'],
          label,
          state,
          chips: stepChips(key, row),
          meta: stepMeta(row),
          scheduledAt: row?.scheduled_at ?? null,
          doneAt: row?.done_at ?? null,
          outcome: (row?.outcome as ProcessStep['outcome']) ?? 'open',
          note: row?.note ?? null,
        }
      })
      // The step after the last completed one is the one in play — unless the
      // process is over, in which case nothing is.
      const next = steps.findIndex((s, i) => i > reached && s.state === 'pending')
      if (!out && next !== -1) {
        steps[next] = {
          ...steps[next],
          state: byKey.get(steps[next].key)?.scheduled_at ? 'current' : 'current',
        }
      }

      cards.push({
        id: person.application_id,
        jobId: job.job_id,
        candidateRef: candidateRef(person.candidate_id),
        candidateName: person.candidate_name,
        role: job.job_title,
        mandateRef: mandateRef(job.job_id),
        client: job.company_name ?? '—',
        paceLabel: pace.label,
        pacePro: pace.provenance,
        progress: live(
          Math.round(((reached + 1) / steps.length) * 100),
          'Aus den abgehakten Prozess-Schritten',
        ),
        fee: demo(0, 'Kein Honorarmodell hinterlegt'),
        statusNote: out
          ? `Abgesagt · ${out.label}`
          : person.next_appointment
            ? `Nächster Termin ${dateTimeDe(person.next_appointment)}`
            : undefined,
        steps,
        editable: true,
        assessment: toAssessment(person.assessment),
        salaryFit:
          person.salary_fit && person.salary_fit.status !== 'unknown'
            ? {
                status: person.salary_fit.status,
                detail: person.salary_fit.detail ?? undefined,
              }
            : undefined,
      })
    }
  }

  // Grouped by mandate (the tracker's own shape), furthest along first inside.
  return cards.sort(
    (a, b) =>
      a.mandateRef.localeCompare(b.mandateRef) || b.progress.value - a.progress.value,
  )
}

/** The design's sub-chips under a step: who has delivered.
 *
 *  The record holds ONE verdict per step, and the tracker's green/red cell is
 *  the CLIENT's (see backend `pipeline/steps.py`). So the Kunde chip lights
 *  from that verdict and the Kandidat chip stays unlit until there is a field
 *  that actually records what the candidate said — lighting both would claim
 *  feedback nobody collected. "Offer & Zusage" is a single milestone in this
 *  model, so both of its chips follow it.
 */
function stepChips(
  key: string,
  row: ProcessStepDTO | undefined,
): ProcessStep['chips'] {
  const passed = row?.outcome === 'pass'
  if (key === 'feedback-1') return [{ label: 'Kunde', done: passed }]
  if (key === 'feedback-2') {
    return [
      { label: 'Kand.', done: false },
      { label: 'Kunde', done: passed },
    ]
  }
  if (key === 'offer') {
    const done = passed || !!row?.done_at
    return [
      { label: 'Offer', done },
      { label: 'Zusage', done },
    ]
  }
  return undefined
}

function toAssessment(
  dto: ProcessCandidateDTO['assessment'],
): CandidateAssessment | undefined {
  if (!dto) return undefined
  return {
    fitScore: dto.fit_score,
    verdict: dto.verdict,
    strengths: dto.strengths ?? [],
    risks: dto.risks ?? [],
    clientSummary: dto.client_summary,
    technologies: dto.technologies ?? [],
    basis: dto.basis,
    assessedAt: dto.assessed_at,
  }
}

/**
 * The cards, grouped into mandates — the cockpit's per-job view.
 *
 * Grouping runs off the cards rather than the DTOs so the demo baseline gets
 * the view too: a card with no `jobId` is grouped by its mandate ref and the
 * Suchprofil simply stays empty. The alternative — a per-job view that exists
 * only when the backend answers — would make the switch appear and disappear.
 */
export function mandatesFromCards(
  cards: ProcessCard[],
  jobs: ProcessJobDTO[] = [],
): Mandate[] {
  const profile = new Map(jobs.map((j) => [j.job_id, j]))
  const out = new Map<string, Mandate>()

  for (const card of cards) {
    const id = card.jobId ?? card.mandateRef
    const dto = card.jobId ? profile.get(card.jobId) : undefined
    const mandate = out.get(id) ?? {
      id,
      ref: card.mandateRef,
      title: card.role,
      client: card.client,
      location: dto?.location ?? null,
      mustHave: dto?.must_have_skills ?? [],
      salaryMin: dto?.salary_min ?? null,
      salaryMax: dto?.salary_max ?? null,
      salaryCurrency: dto?.salary_currency ?? null,
      status: dto?.status ?? null,
      cards: [],
    }
    mandate.cards.push(card)
    out.set(id, mandate)
  }

  // Furthest-along mandate first, the way the design orders the cockpit list:
  // the search closest to a placement is the one worth looking at. Ties go to
  // the busier mandate, then alphabetically so the order is stable.
  const best = (m: Mandate) => Math.max(...m.cards.map((c) => c.progress.value))
  return [...out.values()].sort(
    (a, b) =>
      best(b) - best(a) ||
      b.cards.length - a.cards.length ||
      a.title.localeCompare(b.title),
  )
}

/** The recruiter's clock. Appointments are agreed in German local time, and a
 *  cockpit that renders them in the viewer's zone would show a Munich
 *  interview at the wrong hour to anyone travelling. */
const TZ = 'Europe/Berlin'

/** "14.08. · 10:30", or the plain date when no time was agreed — midnight is
 *  how a date-only cell ("25.08.") arrives. */
function dateTimeDe(iso: string): string {
  const when = new Date(iso)
  const date = when.toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    timeZone: TZ,
  })
  const time = when.toLocaleTimeString('de-DE', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: TZ,
  })
  return time === '00:00' ? date : `${date} · ${time}`
}

/**
 * The mono caption under a step: when it is (or was), and what was noted.
 *
 * Both, not one of them. The note used to be dropped whenever the step also
 * carried a done date, so a recruiter who wrote "blabla test" against a date
 * saw only the date and reasonably concluded the note had not saved.
 */
function stepMeta(row: ProcessStepDTO | undefined): string | undefined {
  if (!row) return undefined
  const when = row.scheduled_at ?? row.done_at
  const parts = [when ? dateTimeDe(when) : null, row.note].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : undefined
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
