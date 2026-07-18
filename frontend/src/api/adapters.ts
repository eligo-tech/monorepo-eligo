// Adapters: backend DTOs → the view models the components already render.
// This keeps the presentation layer stable while the data source moves from
// mock fixtures to the live API.
import type {
  Candidate,
  DwellStage,
  FunnelStage,
  MatchReason,
  MatchStrength,
  PipelineCard,
  PipelineColumn,
  Skill,
  SkillTone,
} from '@/data/types'
import type {
  CandidateDTO,
  DwellStageDTO,
  FunnelStageDTO,
  MatchReasonDTO,
  MatchResultDTO,
  PipelineBoardDTO,
} from './types'

const AVATAR_TONES = [
  'bg-brand-500',
  'bg-sky-600',
  'bg-pink-700',
  'bg-violet-600',
  'bg-fuchsia-700',
  'bg-orange-500',
  'bg-blue-700',
  'bg-emerald-600',
  'bg-teal-600',
  'bg-rose-500',
]

const SKILL_TONES: SkillTone[] = ['purple', 'coral', 'mint', 'sky']

const STAGE_DOTS: Record<string, string> = {
  bewerbung: 'bg-brand-500',
  long_list: 'bg-sky-600',
  short_list: 'bg-rose-500',
  benchmark: 'bg-accent-500',
  awaiting_feedback: 'bg-violet-600',
  hold: 'bg-slate-400',
}

/** Stable non-negative hash of a string (for deterministic colour picks). */
function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

const avatarTone = (seed: string) => AVATAR_TONES[hash(seed) % AVATAR_TONES.length]
const skillTone = (label: string): SkillTone => SKILL_TONES[hash(label) % SKILL_TONES.length]
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const toSkills = (labels: string[]): Skill[] =>
  labels.map((l) => ({ label: cap(l), tone: skillTone(l) }))

function tenureYears(dto: CandidateDTO): number {
  return dto.work_history.reduce((n, w) => n + (w.years || 0), 0)
}

const fmtYears = (y: number) => (y > 0 ? `${y} J` : '—')

const strengthMap: Record<MatchReasonDTO['strength'], MatchStrength> = {
  strong: 'strong',
  moderate: 'moderate',
  weak: 'weak',
}

/** Candidate DTO → list/detail view model. */
export function toCandidate(dto: CandidateDTO): Candidate {
  const total = tenureYears(dto)
  const current = dto.work_history[0]?.years ?? 0
  const avg = dto.work_history.length ? Math.round(total / dto.work_history.length) : 0
  return {
    id: dto.id,
    name: dto.full_name,
    initials: initialsOf(dto.full_name),
    avatar: avatarTone(dto.id),
    email: dto.email,
    phone: dto.phone ?? '—',
    linkedin: true,
    currentTitle: dto.current_title ?? '—',
    currentCompany: dto.current_company ?? '—',
    tenure: current ? `${current} J` : '—',
    extraRoles: Math.max(0, dto.work_history.length - 1),
    skills: toSkills(dto.skills.slice(0, 2)),
    extraSkills: Math.max(0, dto.skills.length - 2),
    location: dto.location ?? '—',
    verification: Math.round(dto.verification_score * 100),
    aiSummary: synthSummary(dto),
    stats: { avgTenure: fmtYears(avg), current: fmtYears(current), total: fmtYears(total) },
    experience: dto.work_history.map((w, i) => ({
      company: w.company,
      title: i === 0 ? (dto.current_title ?? 'Rolle') : 'Frühere Rolle',
      period: `${w.years} Jahr(e)`,
      location: dto.location ?? '—',
    })),
  }
}

/** A short German summary synthesised from structured fields (placeholder for the
 *  LLM-authored KI-Zusammenfassung the backend will provide later). */
function synthSummary(dto: CandidateDTO): string {
  const role = dto.current_title ?? 'Fachkraft'
  const company = dto.current_company ? ` bei ${dto.current_company}` : ''
  const yrs = tenureYears(dto)
  const skills = dto.skills.slice(0, 4).map(cap).join(', ')
  return `${role}${company}${dto.location ? ` in ${dto.location}` : ''} mit ${yrs} Jahr(en) Erfahrung. Schwerpunkte: ${skills || '—'}.`
}

export function toMatchReasons(reasons: MatchReasonDTO[]): MatchReason[] {
  return reasons.map((r) => ({
    title: r.title,
    strength: strengthMap[r.strength],
    detail: r.evidence,
  }))
}

/** Overall match badge label from a MatchResult. */
export function overallStrength(result: MatchResultDTO): MatchStrength {
  if (!result.passed_hard_filters) return 'weak'
  return strengthMap[result.strength]
}

/** Reporting funnel DTO → chart model ({label, value}). */
export function toFunnel(stages: FunnelStageDTO[]): FunnelStage[] {
  return stages.map((s) => ({ label: s.label, value: s.count }))
}

/** Reporting dwell DTO → bar model, normalising avg_days to a 0-1 bar height. */
export function toDwell(stages: DwellStageDTO[]): DwellStage[] {
  const max = Math.max(1, ...stages.map((s) => s.avg_days))
  return stages.map((s) => ({
    label: s.label,
    height: s.avg_days / max,
    caption: s.avg_days > 0 ? `${s.avg_days}T` : '—',
  }))
}

/** Pipeline board DTO → Kanban columns, joining candidate details by id. */
export function toPipelineColumns(
  board: PipelineBoardDTO,
  candidatesById: Map<string, CandidateDTO>,
): PipelineColumn[] {
  return board.columns.map((col) => ({
    id: col.stage,
    title: col.label,
    dotColor: STAGE_DOTS[col.stage] ?? 'bg-slate-400',
    cards: col.applications.map((app): PipelineCard => {
      const c = candidatesById.get(app.candidate_id)
      const name = c?.full_name ?? 'Unbekannt'
      return {
        id: app.id,
        name,
        initials: initialsOf(name),
        avatar: avatarTone(app.candidate_id),
        title: c?.current_title ?? '—',
        location: c?.location ?? '—',
        company: c?.current_company ?? '—',
        sla: '10min',
        linkedin: true,
      }
    }),
  }))
}