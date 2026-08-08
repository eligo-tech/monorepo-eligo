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
export type ProcessStepKey =
  | 'vorgestellt'
  | 'feedback-1'
  | 'vorbereitung'
  | 'interview'
  | 'feedback-2'
  | 'final-vorb'
  | 'finaltermin'
  | 'offer'
  | 'vertrag'

export type StepState = 'done' | 'current' | 'blocked' | 'pending'

export interface ProcessStep {
  key: ProcessStepKey
  label: string
  state: StepState
  /** Mono line under the label, e.g. "27.06" or "15.07 · 10:00". */
  meta?: string
  /** Two-party sub-chips (Kand. / Kunde, Offer / Zusage) and whether each is met. */
  chips?: { label: string; done: boolean }[]
}

export interface ProcessCard {
  id: string
  candidateRef: string
  candidateName: string
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

// ── Kandidatenwelt · Profilvertrieb ─────────────────────────────────────────

/** The candidate the profile-sale screen is built around. */
export interface ProfileSubject {
  ref: string
  badge: string
  headline: string
  /** e.g. "Senior Cloud Architect · 9 J. Erfahrung · AWS / Kubernetes / Go · Wechselbereit". */
  summary: string
  optionCount: Figure
}

/** Left column: a hiring manager in our own database with an open role. */
export interface ManagerLead {
  id: string
  person: string
  role: string
  company: string
  openRole: string
  skills: string[]
  match: Figure
  /** Tone of address we have on file with this contact. */
  address: 'Sie' | 'Du'
}

/** Right column: a live vacancy found on the market (public sources only). */
export interface MarketRole {
  id: string
  title: string
  company: string
  /** e.g. "München · Gehalt passt · Quelle: LinkedIn Jobs". */
  meta: string
  source: string
  skills: string[]
  match: Figure
}

export interface ProfileSaleData {
  subject: ProfileSubject
  managers: ManagerLead[]
  market: MarketRole[]
}

// ── Command bar state ───────────────────────────────────────────────────────

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
  actions: NextAction[]
  profileSale: ProfileSaleData
}
