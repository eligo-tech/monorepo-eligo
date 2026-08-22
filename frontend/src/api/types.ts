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

/** PATCH body for a manual recruiter edit — every field optional; only the
 *  fields present are applied. Mirrors backend CandidateUpdate. */
export interface CandidateUpdatePayload {
  full_name?: string
  email?: string | null
  phone?: string | null
  current_title?: string | null
  current_company?: string | null
  location?: string | null
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
  salary_expectation?: number | null
  salary_currency?: string
  work_permit?: string
  source?: string | null
  motivation?: string | null
  skills?: string[]
  languages?: string[]
  education?: EducationDTO[]
  work_history?: WorkRoleDTO[]
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

export interface CompanyDTO {
  id: string
  tenant_id: string
  name: string
  domain: string | null
  industry: string | null
  location: string | null
  is_client: boolean
  source: string | null
  bd_signals: Record<string, unknown>
  created_at: string
  updated_at: string
}

/**
 * A company in the SHARED information hub — the market corpus, not the CRM.
 *
 * Carries no `tenant_id`: public facts are identical for every workspace, so
 * they are stored once. What a tenant makes of a corpus company (`tracked`,
 * and the link row behind it) is the tenant-scoped part.
 *
 * `resolution_basis` is which rung of the deterministic identity ladder matched
 * (vat > register > domain > name_place). Surfaced in the UI because an identity
 * proven by VAT id is a different claim from one assumed from name + postcode.
 */
export interface HubCompanyDTO {
  id: string
  name: string
  normalized_name: string
  legal_form: string | null
  dedupe_key: string
  resolution_basis: 'vat' | 'register' | 'domain' | 'name_place'
  website_domain: string | null
  street: string | null
  postal_code: string | null
  city: string | null
  region: string | null
  country: string | null
  latitude: number | null
  longitude: number | null
  register_court: string | null
  register_number: string | null
  vat_id: string | null
  vat_verified_at: string | null
  industry: string | null
  source: string
  open_postings_count: number
  bd_signals: Record<string, unknown>
  first_seen_at: string
  last_seen_at: string
  created_at: string
  updated_at: string
  /** Whether THIS workspace has an overlay row for this corpus company. */
  tracked: boolean
}

/**
 * Outcome of one ingest slice.
 *
 * Returned by `POST /hub/ingest`, which only the scheduled job calls — the UI
 * never triggers ingestion (see ARCHITECTURE.md, RULE 1). Kept here so the
 * contract is typed in one place.
 */
export interface HubIngestSummaryDTO {
  source: string
  /** True when a recent identical fetch was reused and no request was made. */
  skipped: boolean
  skipped_reason: string | null
  /** Age of the reused fetch, so the UI can phrase it in its own language. */
  reused_age_minutes: number | null
  observation_id: string
  fetched: number
  total_available: number | null
  companies_created: number
  companies_matched: number
  postings_created: number
  postings_updated: number
  rejected: { external_id: string | null; company: string | null; reason: string }[]
  notes: string[]
}

/** One filter option and how many active postings carry it. */
export interface FacetValueDTO {
  value: string
  count: number
}

/** Filter options, derived from the corpus so none of them return nothing. */
export interface HubFacetsDTO {
  regions: FacetValueDTO[]
  berufsfelder: FacetValueDTO[]
}

/** Corpus-wide totals, counted in the database rather than over a page. */
export interface HubCorpusStatsDTO {
  companies: number
  /** Distinct employers after collapsing one-row-per-site fragmentation. */
  employers: number
  hiring: number
  open_postings: number
  cities: number
  unverified_identity: number
  sources: number
  last_ingest_at: string | null
}

/** One employer in a search result — a rollup across sites, not a corpus row. */
export interface HubEmployerHitDTO {
  normalized_name: string
  name: string
  /** How many corpus rows (branches/sites) this employer collapses into. */
  sites: number
  open_roles: number
  cities: string[]
  city_count: number
  resolution_basis: 'vat' | 'register' | 'domain' | 'name_place'
  website_domain: string | null
  hub_company_ids: string[]
  /** The roles that justify the hit — the answer carries its own evidence. */
  matching_roles: HubJobPostingDTO[]
  tracked: boolean
}

/**
 * A standing market question belonging to this workspace.
 *
 * Two jobs: re-run it against the corpus, and — because `crawl_enabled` puts it
 * in the nightly job's directive union — deepen the corpus where this workspace
 * actually recruits. Saving one crawls nothing; the scheduled job acts on it.
 */
export interface SavedSearchDTO {
  id: string
  tenant_id: string
  label: string
  q: string | null
  city: string | null
  regions: string[]
  berufsfelder: string[]
  radius_km: number | null
  min_roles: number
  crawl_enabled: boolean
  last_crawled_at: string | null
  last_result_count: number | null
  created_at: string
  updated_at: string
}

/** One workspace's relationship to a corpus company — the tenant boundary. */
export interface HubCompanyLinkDTO {
  id: string
  tenant_id: string
  hub_company_id: string
  /** The tenant's own CRM company row, once adopted. */
  company_id: string | null
  relationship: 'watching' | 'prospect' | 'client' | 'ignored'
  note: string | null
  created_at: string
  updated_at: string
}

/** One external posting in the hub — a market signal, never a client mandate. */
export interface HubJobPostingDTO {
  id: string
  hub_company_id: string
  observation_id: string | null
  title: string
  description: string | null
  occupation: string | null
  /** Coarse occupational field — stamped from the crawl shard, not the record. */
  berufsfeld: string | null
  /** Bundesland from the record's own address. */
  region: string | null
  employment_type: string | null
  location_text: string | null
  postal_code: string | null
  city: string | null
  country: string | null
  latitude: number | null
  longitude: number | null
  remote_possible: boolean | null
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  posted_at: string | null
  expires_at: string | null
  source: string
  source_url: string | null
  external_id: string
  first_seen_at: string
  last_seen_at: string
  is_active: boolean
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