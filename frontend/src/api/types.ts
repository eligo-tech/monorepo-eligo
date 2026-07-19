// Backend DTOs — mirror the FastAPI response_model schemas under /api/v1.
// Captured from live responses; keep in sync with backend/app/domain/*/schemas.py.

/** One structured role from the CV (dates + achievement highlights). Legacy
 *  rows may instead carry `{ company, years }`. */
export interface WorkRoleDTO {
  title?: string
  company?: string
  location?: string
  start_date?: string
  end_date?: string
  highlights?: string[]
  years?: number // legacy shape
}

export interface EducationDTO {
  degree?: string
  institution?: string
  location?: string
  start_date?: string
  end_date?: string
}

export interface CandidateDTO {
  id: string
  tenant_id: string
  full_name: string
  email: string
  phone: string | null
  current_title: string | null
  current_company: string | null
  location: string | null
  skills: string[]
  work_history: WorkRoleDTO[]
  salary_expectation: number | null
  salary_currency: string
  availability_weeks: number | null
  work_permit: string
  merged_identities: string[]
  verification_score: number // 0..1
  created_at: string
  updated_at: string

  // Extended profile (aiFind field set) — all optional/nullable.
  first_name?: string | null
  last_name?: string | null
  sex?: string | null
  name_prefix?: string | null
  date_of_birth?: string | null
  street?: string | null
  postal_code?: string | null
  city?: string | null
  country?: string | null
  linkedin_url?: string | null
  xing_url?: string | null
  industry?: string | null
  employment_type?: string | null
  willing_to_relocate?: string | null
  notice_period?: string | null
  availability?: string | null
  total_years_experience?: string | null
  current_salary?: number | null
  languages?: string[] | null
  education?: EducationDTO[] | string[] | null
  working_experience?: string[] | null
  motivation?: string | null
  source?: string | null
}

export interface JobDTO {
  id: string
  tenant_id: string
  title: string
  client_company_id: string
  location: string | null
  location_radius_km: number | null
  must_have_skills: string[]
  required_certifications: string[]
  requires_work_permit: boolean
  salary_min: number | null
  salary_max: number | null
  salary_currency: string
  status: string
  created_at: string
  updated_at: string
}

export interface ApplicationDTO {
  id: string
  tenant_id: string
  candidate_id: string
  job_id: string
  status: string
  stage: string
  notes: string | null
  history: { at: string; event: string }[]
  created_at: string
  updated_at: string
}

export interface BoardColumnDTO {
  stage: string
  label: string
  applications: ApplicationDTO[]
}

export interface PipelineBoardDTO {
  columns: BoardColumnDTO[]
}

export type BackendStrength = 'strong' | 'moderate' | 'weak'

export interface MatchReasonDTO {
  title: string
  strength: BackendStrength
  evidence: string
}

export interface MatchResultDTO {
  candidate_id: string
  job_id: string
  passed_hard_filters: boolean
  hard_filter_failures: string[]
  score: number // 0..1
  strength: BackendStrength
  reasons: MatchReasonDTO[]
  ranker: string
}

export interface FunnelStageDTO {
  key: string
  label: string
  count: number
}

export interface DwellStageDTO {
  key: string
  label: string
  avg_days: number
  count: number
}

export interface ReportingSummaryDTO {
  total_candidates: number
  open_jobs: number
  total_applications: number
  placements: number
  avg_verification: number
}

export interface ReportingOverviewDTO {
  funnel: FunnelStageDTO[]
  dwell: DwellStageDTO[]
  summary: ReportingSummaryDTO
}

export interface CVFieldDTO {
  field: string
  label: string
  value: string
  confidence: number // 0..1
  needs_review: boolean
}

export interface CVExtractionResultDTO {
  document_name: string
  fields: CVFieldDTO[]
  review_items: string[]
  notes: string[]
  candidate_id: string | null
  text_chars: number
}