// Adapters: backend DTOs → the view models the components already render.
// This keeps the presentation layer stable while the data source moves from
// mock fixtures to the live API.
import type {
  Candidate,
  CandidateProfile,
  DwellStage,
  EducationEntry,
  FunnelStage,
  RoleEntry,
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
  EducationDTO,
  FunnelStageDTO,
  MatchReasonDTO,
  MatchResultDTO,
  PipelineBoardDTO,
  WorkRoleDTO,
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

/** Join a role's date span into a display period, e.g. "Mar 2024 – Present". */
function period(start?: string, end?: string): string | undefined {
  const s = start?.trim()
  const e = end?.trim()
  if (s && e) return `${s} – ${e}`
  return s || e || undefined
}

/** Backend work_history → structured timeline roles. Tolerates the legacy
 *  `{ company, years }` shape (renders it as a bare company + tenure). */
function toRoles(history: WorkRoleDTO[]): RoleEntry[] {
  return history
    .map((w) => ({
      title: (w.title ?? '').trim(),
      company: (w.company ?? '').trim(),
      location: w.location?.trim() || undefined,
      period: period(w.start_date, w.end_date) ?? (w.years ? `${w.years} J` : undefined),
      highlights: (w.highlights ?? []).map((h) => h.trim()).filter(Boolean),
    }))
    .filter((r) => r.title || r.company)
}

function toEducation(entries: CandidateDTO['education']): EducationEntry[] {
  if (!entries?.length) return []
  // Legacy rows stored education as plain strings.
  if (typeof entries[0] === 'string') {
    return (entries as string[])
      .map((s) => s.trim())
      .filter(Boolean)
      .map((degree) => ({ degree }) as EducationEntry)
  }
  return (entries as EducationDTO[])
    .map((e) => ({
      degree: (e.degree ?? '').trim(),
      institution: e.institution?.trim() || undefined,
      location: e.location?.trim() || undefined,
      period: period(e.start_date, e.end_date),
    }))
    .filter((e) => e.degree || e.institution)
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
  const linkedinUrl = normalizeUrl(dto.linkedin_url)
  return {
    id: dto.id,
    name: dto.full_name,
    initials: initialsOf(dto.full_name),
    avatar: avatarTone(dto.id),
    email: dto.email,
    phone: dto.phone ?? '—',
    linkedin: Boolean(linkedinUrl),
    linkedinUrl,
    createdAt: dto.created_at,
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
    experience: toRoles(dto.work_history).map((r) => ({
      company: r.company || '—',
      title: r.title || (dto.current_title ?? 'Rolle'),
      period: r.period ?? '',
      location: r.location ?? dto.location ?? '—',
    })),
    profile: toProfile(dto),
  }
}

/** Ensure a stored URL is absolute so the anchor navigates off-app. */
function normalizeUrl(raw: string | null | undefined): string | undefined {
  const v = raw?.trim()
  if (!v) return undefined
  return /^https?:\/\//i.test(v) ? v : `https://${v}`
}

/** Backend candidate → the extended dossier profile (all fields optional). */
function toProfile(dto: CandidateDTO): CandidateProfile {
  return {
    firstName: dto.first_name ?? undefined,
    lastName: dto.last_name ?? undefined,
    sex: dto.sex ?? undefined,
    namePrefix: dto.name_prefix ?? undefined,
    dateOfBirth: dto.date_of_birth ?? undefined,
    street: dto.street ?? undefined,
    postalCode: dto.postal_code ?? undefined,
    city: dto.city ?? undefined,
    country: dto.country ?? undefined,
    linkedinUrl: normalizeUrl(dto.linkedin_url),
    xingUrl: normalizeUrl(dto.xing_url),
    industry: dto.industry ?? undefined,
    employmentType: dto.employment_type ?? undefined,
    willingToRelocate: dto.willing_to_relocate ?? undefined,
    noticePeriod: dto.notice_period ?? undefined,
    availability: dto.availability ?? undefined,
    totalYearsExperience: dto.total_years_experience ?? undefined,
    currentSalary: dto.current_salary ?? undefined,
    salaryExpectation: dto.salary_expectation ?? undefined,
    salaryCurrency: dto.salary_currency,
    availabilityWeeks: dto.availability_weeks ?? undefined,
    workPermit: dto.work_permit,
    languages: dto.languages ?? [],
    roles: toRoles(dto.work_history),
    education: toEducation(dto.education),
    motivation: dto.motivation ?? undefined,
    source: dto.source ?? undefined,
    allSkills: dto.skills,
  }
}

/** A short German summary synthesised from structured fields (placeholder for the
 *  LLM-authored KI-Zusammenfassung the backend will provide later). */
function synthSummary(dto: CandidateDTO): string {
  const role = dto.current_title ?? 'Fachkraft'
  const company = dto.current_company ? ` bei ${dto.current_company}` : ''
  const yrs = tenureYears(dto)
  const exp = yrs > 0 ? ` mit ${yrs} Jahr(en) Erfahrung` : ''
  const skills = dto.skills.slice(0, 4).map(cap).join(', ')
  const focus = skills ? ` Schwerpunkte: ${skills}.` : ''
  return `${role}${company}${dto.location ? ` in ${dto.location}` : ''}${exp}.${focus}`
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