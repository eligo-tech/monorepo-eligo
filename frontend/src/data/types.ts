// Domain types for the eligo-tech mockup.
// These intentionally mirror the backend canonical model (candidate / job /
// application / match) so the mock data can later be swapped for live API calls.

export type SkillTone = 'purple' | 'coral' | 'mint' | 'sky' | 'neutral'

export interface Skill {
  label: string
  tone: SkillTone
}

export interface Experience {
  company: string
  title: string
  period: string
  location: string
}

/** One role on the CV timeline: header + achievement highlights. */
export interface RoleEntry {
  title: string
  company: string
  location?: string
  period?: string
  highlights: string[]
}

export interface EducationEntry {
  degree: string
  institution?: string
  location?: string
  period?: string
}

/** Extended profile (aiFind field set) shown in the full candidate dossier. */
export interface CandidateProfile {
  firstName?: string
  lastName?: string
  sex?: string
  namePrefix?: string
  dateOfBirth?: string
  street?: string
  postalCode?: string
  city?: string
  country?: string
  linkedinUrl?: string
  xingUrl?: string
  industry?: string
  employmentType?: string
  willingToRelocate?: string
  noticePeriod?: string
  availability?: string
  totalYearsExperience?: string
  currentSalary?: number | null
  salaryExpectation?: number | null
  salaryCurrency?: string
  availabilityWeeks?: number | null
  workPermit?: string
  languages: string[]
  /** structured CV history (dates + highlights) */
  roles: RoleEntry[]
  education: EducationEntry[]
  motivation?: string
  source?: string
  /** all skills (the table only shows the first two) */
  allSkills: string[]
}

export interface Candidate {
  id: string
  name: string
  initials: string
  /** avatar background tone */
  avatar: string
  email: string
  phone: string
  linkedin?: boolean
  /** real LinkedIn profile URL, when known */
  linkedinUrl?: string
  currentTitle: string
  currentCompany: string
  tenure: string
  /** number of additional roles beyond the current one */
  extraRoles: number
  skills: Skill[]
  extraSkills: number
  location: string
  /** 0-100 — how much of the profile is verified against a real source */
  verification: number
  aiSummary: string
  stats: { avgTenure: string; current: string; total: string }
  experience: Experience[]
  /** extended fields for the full dossier view (live candidates only) */
  profile?: CandidateProfile
}

export type MatchStrength = 'very-strong' | 'strong' | 'moderate' | 'weak'

export interface MatchReason {
  title: string
  strength: MatchStrength
  detail: string
}

/** A single card on the pipeline (Kanban) board. */
export interface PipelineCard {
  id: string
  name: string
  initials: string
  avatar: string
  title: string
  location: string
  company: string
  sla: string
  linkedin?: boolean
}

export interface PipelineColumn {
  id: string
  title: string
  dotColor: string
  cards: PipelineCard[]
}

export interface FunnelStage {
  label: string
  value: number
}

export interface DwellStage {
  label: string
  /** relative bar height 0-1 */
  height: number
  caption: string
}