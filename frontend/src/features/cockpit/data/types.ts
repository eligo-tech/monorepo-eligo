// View models for the cockpit surface.
//
// Two rules run through this file:
//
//  1. **Provenance is part of the data, not a rendering afterthought.** The
//     product invariant (see the repo CLAUDE.md) is that every displayed claim
//     is evidence-backed. Sections the backend cannot yet serve — revenue
//     targets, learned deal-chance, detected signals — are still rendered, but
//     they carry `provenance: 'demo'` so the UI can mark them and nobody
//     mistakes a demo figure for a verified one.
//  2. **Shapes anticipate the API.** Where an endpoint exists today the fields
//     mirror its DTO (see src/api/types.ts); where it doesn't, the shape is what
//     we would want the endpoint to return.

/** Where a displayed figure came from. `demo` values get a visible marker. */
export type Provenance = 'live' | 'demo'

/** A number plus where it came from — the atom every cockpit figure is built on. */
export interface Figure {
  value: number
  provenance: Provenance
  /** Short human explanation of the source, shown on hover. */
  source?: string
}

export const live = (value: number, source?: string): Figure => ({
  value,
  provenance: 'live',
  source,
})
export const demo = (value: number, source?: string): Figure => ({
  value,
  provenance: 'demo',
  source,
})

// ── Erkannte Signale ────────────────────────────────────────────────────────

export type SignalKind = 'email' | 'note' | 'calendar' | 'crm'

export interface SignalItem {
  id: string
  kind: SignalKind
  /** Mono chip on the left, e.g. "E-Mail · vor 2 Std". */
  label: string
  /** Body copy; `refs` are highlighted as record ids inside it. */
  text: string
  refs: string[]
  /** Label of the primary action, e.g. "Übernehmen" / "Prüfen". */
  action: string
  provenance: Provenance
}

// ── 01 Umsatz & Potenzial ───────────────────────────────────────────────────

export type PeriodKey = 'jahr' | 'quartal' | 'monat' | 'tag'

/** One row of the "Kurz vor Abschluss" list — a deal about to land. */
export interface ClosingDeal {
  id: string
  candidateRef: string
  /** Set when the deal came from a real process: the record to open. Demo
   *  rows have no person behind the ref. */
  candidateId?: string
  candidateName?: string
  /** The mandate this run belongs to, for the cockpit link. */
  jobId?: string
  mandateRef: string
  client: string
  fee: Figure
  /** e.g. "diesen Monat" */
  timing: string
  chance: Figure
  /** Optional extra chip, e.g. "mündl. Zusage". */
  note?: string
}

export interface RevenuePanel {
  key: PeriodKey
  /** Caption under the gauge value, e.g. "JULI". */
  caption: string
  actual: Figure
  potential: Figure
  /** Target for the gauge's fill percentage. */
  target: Figure
  yearActual: Figure
  yearTarget: Figure
  closing: ClosingDeal[]
  /** "Weitere Pipeline" footer. */
  pipelineTotal: Figure
  pipelineWeighted: Figure
}

/** A slide in the 01 carousel. `revenue` slides render the full panel; others
 *  are declared-but-empty extension points so the dots in the mockup are real. */
export interface KpiSlide {
  id: string
  title: string
  kind: 'revenue' | 'placeholder'
  /** Present when kind === 'revenue'. */
  panels?: Record<PeriodKey, RevenuePanel>
  /** Present when kind === 'placeholder'. */
  hint?: string
}

// ── 02 Jobscoring ───────────────────────────────────────────────────────────

export interface JobScore {
  id: string
  mandateRef: string
  title: string
  /** 0-100 Besetzbarkeit. */
  score: Figure
  /** Change since the last data run; null when unknown. */
  delta: Figure | null
  /** 0-100 deal-chance with the hiring manager ("M" column). */
  managerChance: Figure | null
}

// ── 03 Laufende Prozesse ────────────────────────────────────────────────────

/** The nine steps of a live placement process, as drawn in the mockups. */
/** The nine canonical steps, plus the tracker's repeat interview rounds
 *  ("interviewtermin_3"): a third round happens, and a closed union would have
 *  to drop it. */
export type ProcessStepKey =
  | 'vorgestellt'
  | 'feedback-1'
  | 'interview'
  | 'vorbereitung'
  | 'feedback-2'
  | 'finaltermin'
  | 'final-vorb'
  | 'offer'
  | 'vertrag'
  | `interviewtermin_${number}`

/** `out` is the tracker's red cell: the client said no and the process stops.
 *  Distinct from `blocked`, where someone still owes us an answer. */
export type StepState = 'done' | 'current' | 'blocked' | 'pending' | 'out'

export interface ProcessStep {
  key: ProcessStepKey
  label: string
  state: StepState
  /** Mono line under the label, e.g. "27.06" or "15.07 · 10:00". */
  meta?: string
  /** Two-party sub-chips (Kand. / Kunde, Offer / Zusage) and whether each is met. */
  chips?: { label: string; done: boolean }[]
  /** The stored values behind the step, when it came from the record. The
   *  editor needs what IS, not the formatted caption. */
  scheduledAt?: string | null
  doneAt?: string | null
  outcome?: 'open' | 'pass' | 'out'
  note?: string | null
}

/** The Kandidatenauswertung, as the cockpit shows it: this candidate measured
 *  against THIS mandate. Absent while nobody has written one — "not assessed"
 *  and "assessed, no score" are different statements. */
export interface CandidateAssessment {
  /** Gesamtbewertung on the recruiter's own scale, 0–10. */
  fitScore: number | null
  /** Kurzfazit, followed by the paragraph that argues it. */
  verdict: string | null
  strengths: string[]
  risks: string[]
  /** Written for the client's eyes — never mixed with internal notes. */
  clientSummary: string | null
  technologies: string[]
  /** Provenance: what the assessment was read from, and when. */
  basis: string | null
  assessedAt: string | null
}

/** Section B of the Kandidatenauswertung: the PERSON, not their fit for one
 *  mandate. The same object appears on every process this candidate runs —
 *  a Gesprächszusammenfassung that differed per mandate would be two answers
 *  to one question. */
export interface CandidateProfile {
  /** "Zusammenfassung des Profils" — the paragraph the card leads with. */
  summary: string | null
  /** "Schwerpunkte". */
  focusAreas: string[]
  /** "Technisches Know-how" in prose, qualifiers kept. */
  technicalProfile: string | null
  noticePeriod: string | null
  availability: string | null
  motivation: string | null
  interviewAvailability: string | null
  education: string[]
  /** "Weitere relevante Punkte", one per line. */
  otherNotes: string | null
  otherProcesses: string | null
  otherProcessCompanies: string[]
  salaryMinimum: number | null
  salaryExpectation: number | null
  currentSalary: number | null
  salaryCurrency: string | null
}

export interface ProcessCard {
  id: string
  /** The mandate this run belongs to, when the card comes from the record.
   *  Demo cards have none — there is no job row behind them. */
  jobId?: string
  candidateRef: string
  candidateName: string
  /** The person behind the process, so the card can open their record.
   *  Absent on demo cards: there is nobody to open. */
  candidateId?: string
  role: string
  mandateRef: string
  client: string
  /** e.g. "Ø 9 T bis Offer" — derived from reporting dwell times when live. */
  paceLabel: string
  pacePro: Provenance
  /** Ring percentage, top-left of the card. */
  progress: Figure
  fee: Figure
  /** Status pill next to the title, e.g. "Mündl. Zusage · Vertrag ausstehend". */
  statusNote?: string
  steps: ProcessStep[]
  /** True when the card is one process in the record, so its steps can be
   *  edited. Demo cards and the coarse board join are read-only: there is no
   *  row to write to. */
  editable?: boolean
  assessment?: CandidateAssessment
  /** The person behind the process. Absent on demo cards. */
  profile?: CandidateProfile
  /** Deterministic: what the candidate needs vs. what the mandate pays.
   *  Absent when the figures to compare are not all on the record. */
  salaryFit?: SalaryFit
}

/** The money question, decided in code rather than by a model. */
export interface SalaryFit {
  status: 'fits' | 'negotiable' | 'above_band'
  detail?: string
}

/** One mandate: what is being searched for, and who is running on it.
 *
 *  The cockpit's second view. The overall view answers "where does the book of
 *  business stand"; this one answers "where does THIS search stand" — the
 *  question a client asks on the phone, and the one the flat list of cards
 *  could only be read sideways to answer. */
export interface Mandate {
  /** The job id when the mandate comes from the record, else its display ref. */
  id: string
  /** Set ONLY when this mandate is a real job row — demo cards have none, and
   *  anything that queries the record by id must not be handed a "#A-1f24". */
  jobId?: string
  ref: string
  title: string
  client: string
  /** The client company's id, when the mandate comes from the record — the
   *  workspace loads its Stammdaten and manager from it. */
  companyId?: string
  /** The Suchprofil. Null/empty where the mandate carries none yet — shown as
   *  a gap to fill, never invented. */
  location: string | null
  mustHave: string[]
  salaryMin: number | null
  salaryMax: number | null
  salaryCurrency: string | null
  status: string | null
  cards: ProcessCard[]
}

// ── Nächste beste Aktionen ──────────────────────────────────────────────────

export type ActionCategory = 'business-dev' | 'abschluss' | 'freigabe' | 'datenlauf' | 'feedback'

export interface NextAction {
  id: string
  title: string
  detail: string
  category: ActionCategory
  provenance: Provenance
}

export interface CockpitStatus {
  /** "Datenlauf fällig · N Änderungen" */
  pendingChanges: Figure
  humanInTheLoop: boolean
  /** Tone of address the outreach agent uses by default. */
  address: 'Sie' | 'Du'
  /** Initials shown in the command bar when Clerk is off. */
  initials: string
}

// ── The whole surface ───────────────────────────────────────────────────────

export interface CockpitData {
  status: CockpitStatus
  signals: SignalItem[]
  slides: KpiSlide[]
  jobScores: JobScore[]
  processes: ProcessCard[]
  /** The same processes, grouped the way the tracker groups them. */
  mandates: Mandate[]
  actions: NextAction[]
}
