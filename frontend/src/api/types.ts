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
  verification_score: number
  /** Share of key fields that merely have a value. */
  completeness_score?: number // 0..1
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
  /** Every industry worked in — the document asks for "Branchen", plural. */
  industries?: string[] | null
  /** What the source called it ("Permanent", "Contract, Permanent"). */
  employment_type?: string | null
  /** The decidable form a filter can read. Null when nobody established it. */
  employment_form?: EmploymentForm | null
  willing_to_relocate?: string | null
  notice_period?: string | null
  availability?: string | null
  total_years_experience?: string | null
  current_salary?: number | null
  /** The floor the candidate named in the Qualifikationsgespräch;
   *  `salary_expectation` is the wish. Only the pair says whether a band works. */
  salary_minimum?: number | null
  /** The recruiter's summary of the conversation — holds across mandates. */
  profile_summary?: string | null
  /** "Schwerpunkte" — what the person is known for, as items. */
  focus_areas?: string[] | null
  /** "Technisches Know-how" in prose, qualifiers kept. Deliberately not
   *  `skills`: that list is what the deterministic hard filters read. */
  technical_profile?: string | null
  /** "Mi/Do ab 11 Uhr" — needed when booking a round. */
  interview_availability?: string | null
  /** Where else they are in process, in the candidate's own words. */
  other_processes?: string | null
  /** The companies behind that — countable across the pool, unlike prose. */
  other_process_companies?: string[] | null
  /** "Weitere relevante Punkte" — the open tail of the conversation. */
  other_notes?: string | null
  languages?: string[] | null
  education?: EducationDTO[] | string[] | null
  working_experience?: string[] | null
  motivation?: string | null
  source?: string | null
}

/** PATCH body for a manual recruiter edit — every field optional; only the
 *  fields present are applied. Mirrors backend CandidateUpdate. */
/** POST /erasure/{candidates|managers}/{id}. */
export interface EraseBody {
  /** Typed by the admin; must match the record's name. */
  confirm_name: string
  reason: 'erasure' | 'objection'
  /** The day the person asked, YYYY-MM-DD. */
  requested_on: string
}

/** One handled erasure request. Names nobody. */
export interface ErasureRequestDTO {
  id: string
  subject_type: 'candidate' | 'manager'
  reason: 'erasure' | 'objection'
  requested_on: string
  created_at: string
  executed_by_name: string | null
  /** Rows removed per table, `receipts_blacked_out`, `suppressions_written`. */
  counts: Record<string, number>
  /** Blocks lifted since because the person came back. */
  lifted: number
  last_lifted_at: string | null
  last_lifted_by: string | null
}

export interface CandidateUpdatePayload {
  /** The `updated_at` the editor was opened on. The server refuses the write
   *  with 409 if somebody else has committed one of the same fields since;
   *  omitting it means "write regardless", which is what the force-save path
   *  and every non-interactive caller do. */
  base_updated_at?: string
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
  industries?: string[]
  employment_type?: string | null
  employment_form?: EmploymentForm | null
  willing_to_relocate?: string | null
  notice_period?: string | null
  availability?: string | null
  total_years_experience?: string | null
  current_salary?: number | null
  salary_expectation?: number | null
  salary_minimum?: number | null
  profile_summary?: string | null
  /** "Schwerpunkte" — what the person is known for, as items. */
  focus_areas?: string[]
  /** "Technisches Know-how" in prose. Separate from `skills`. */
  technical_profile?: string | null
  interview_availability?: string | null
  other_processes?: string | null
  other_process_companies?: string[]
  /** "Weitere relevante Punkte", one per line. */
  other_notes?: string | null
  salary_currency?: string
  work_permit?: string
  source?: string | null
  motivation?: string | null
  skills?: string[]
  languages?: string[]
  education?: EducationDTO[]
  work_history?: WorkRoleDTO[]
  /** Setting the address of someone erased here is refused (409) unless they
   *  came back of their own accord. */
  override_suppression?: boolean
}

export interface CriteriaSuggestionDTO {
  skill: string
  /** Why it is proposed — "Der Titel nennt »Java«". */
  evidence: string
  /** How many of this workspace's candidates carry it. A criterion nobody
   *  has filters everyone out, so the number is part of the offer. */
  candidates: number
}

export interface JobDTO {
  id: string
  tenant_id: string
  title: string
  client_company_id: string
  /** The Ansprechpartner at the client — who briefed the mandate and who
   *  gets the shortlist. Null while nobody has been recorded. */
  manager_id?: string | null
  location: string | null
  location_radius_km: number | null
  must_have_skills: string[]
  required_certifications: string[]
  requires_work_permit: boolean
  salary_min: number | null
  salary_max: number | null
  salary_currency: string
  /** `active` or `inactive` (ELI-7). Inactive is final — see `ui/jobStatus`.
   *  A backend that has not deployed yet may still say `open`/`closed`, which
   *  is why nothing compares this against a literal. */
  status: string
  /** Set when this mandate was created as a copy of another one. */
  copied_from_job_id?: string | null
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
  /** The company NAME looks like a person's — a sole trader. A screen, not a verdict. */
  suspected_natural_person: boolean
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

/** One filter option and how many active postings carry it. */
export interface FacetValueDTO {
  value: string
  count: number
}

/** Filter options, derived from the corpus so none of them return nothing. */
export interface HubFacetsDTO {
  regions: FacetValueDTO[]
  berufsfelder: FacetValueDTO[]
  /** Job families — only "tech" today (open vacancies, not ads). */
  families?: FacetValueDTO[]
  /** Open ads not yet labelled by the nightly backfill. */
  families_pending?: number
}

/** Corpus-wide totals, counted in the database rather than over a page. */
export interface HubCorpusStatsDTO {
  companies: number
  /** Distinct employers after collapsing one-row-per-site fragmentation. */
  employers: number
  suspected_personal_data: number
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
  suspected_natural_person: boolean
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
/** One page of employer results. */
export interface HubSearchPageDTO {
  items: HubEmployerHitDTO[]
  /** Employers matching the query in total — not just on this page. */
  total: number
  /** Pass back as `cursor` for the next page; null means this was the last. */
  next_cursor: string | null
  /** Words the server re-spelled because the typed ones reached almost
   *  nothing. Shown, never applied silently. */
  corrections: QueryCorrectionDTO[]
}

export interface QueryCorrectionDTO {
  from: string
  to: string
}

/** One ad taken from Markt as a lead job (ELI-22). */
export interface AdoptPostingResultDTO {
  posting_id: string
  created: boolean
  job_id: string | null
  company_id: string | null
  /** "agency" | "not_found" when the ad was not taken. */
  skipped: string | null
}

export interface AdoptPostingsResultDTO {
  created: number
  existing: number
  skipped: number
  results: AdoptPostingResultDTO[]
}

/** What the corpus→CRM crossing produced. */
export interface AdoptResultDTO {
  company_id: string
  company_name: string
  hub_company_id: string
  manager_id: string | null
  /** True when the captured contact owes a GDPR Art. 14 notification. */
  art14_outstanding: boolean
}

/** A hiring manager — the person a mandate belongs to. Tenant-scoped only. */
export interface ManagerDTO {
  id: string
  company_id: string
  full_name: string
  first_name: string | null
  last_name: string | null
  role_title: string | null
  department: string | null
  email: string | null
  phone: string | null
  linkedin_url: string | null
  xing_url?: string | null
  facebook_url?: string | null
  /** Where this person's data came from — decides the Art. 14 obligation. */
  source: string
  source_detail: string | null
  art14_notified_at: string | null
  /** Derived server-side: a notice is owed and has not been sent. */
  art14_outstanding: boolean
  notes: string | null
  status: string
  created_at: string
  /** "MNGR197" — the reference a recruiter reads out on a call. */
  external_code?: string | null
  street?: string | null
  postal_code?: string | null
  city?: string | null
  country?: string | null
  /** What the person is open to — "Looks for: Contract". */
  looks_for?: string | null
  skills?: string[]
  tags?: string[]
  last_contact_at?: string | null
  /** Present only on the single-manager read; the list does not pay for them. */
  /** Contacts in this workspace sharing this e-mail. 1 = unique. */
  duplicate_count?: number
  job_count?: number
  open_job_count?: number
  note_count?: number
}

export interface ManagerInteractionDTO {
  id: string
  manager_id: string
  candidate_id: string | null
  job_id: string | null
  interaction_type: string
  occurred_at: string
  summary: string | null
  external_source?: string | null
}

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
  /** Full ad text. NULL until the nightly job has fetched it for this posting. */
  description: string | null
  /** The words that made this role match — present only when the term is in
   *  the ad body and not the title, i.e. only when the hit needs explaining. */
  match_snippet?: string | null
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
  /** The EMPLOYER's own ad, when the source supplies one. Often absent. */
  source_url: string | null
  /** The source's own page, derived server-side from the reference number. */
  detail_url: string | null
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
  /** The verbatim sentence the value was read from (Zeugnis/Zertifikat).
   *  The server drops any proposal whose sentence is not in the document. */
  evidence?: string | null
  /** A reading of the text rather than something it states — the grade
   *  decoded from Zeugnissprache. Never pre-ticked. */
  interpretation?: boolean
}

export interface CVExtractionResultDTO {
  document_name: string
  fields: CVFieldDTO[]
  review_items: string[]
  notes: string[]
  candidate_id: string | null
  text_chars: number
  /** The extracted address belongs to someone erased here: the day they asked. */
  suppressed_on?: string | null
}
/** The ad that names a contact, and the line that does. */
export interface ContactEvidenceDTO {
  posting_id: string
  posting_title: string
  /** Which public text named the person: the BA ad or the partner-board page. */
  origin: 'anzeige' | 'quelle'
  url: string | null
  posted_at: string | null
  is_active: boolean
  quote: string
}

/** A person a public job ad names as the contact. Nothing is stored until adopted. */
export interface ContactCandidateDTO {
  key: string
  full_name: string
  salutation: 'Frau' | 'Herr' | null
  first_name: string | null
  last_name: string
  role_title: string | null
  email: string | null
  phone: string | null
  /** Whether dialling reaches the person or the company's reception (ELI-22). */
  phone_kind?: 'direct' | 'switchboard' | null
  /** ELI-25: the recruiter's mobile, written beside the landline. */
  mobile?: string | null
  mention_count: number
  evidence: ContactEvidenceDTO[]
  /** Set when this workspace already holds the person as a manager. */
  manager_id: string | null
  /** ELI-25: "model" — proposed by the AI, checked word for word in the ad. */
  found_by?: 'rules' | 'model'
}

export interface CompanyContactsDTO {
  hub_company_id: string
  company_name: string
  company_id: string | null
  contacts: ContactCandidateDTO[]
  mailboxes: { email: string; mention_count: number }[]
  /** ELI-25: phone numbers / e-mails no recognised person claims. */
  unnamed?: UnnamedReachDTO[]
  postings_scanned: number
  postings_with_text: number
}

export interface UnnamedReachDTO {
  kind: 'phone' | 'email'
  value: string
  phone_kind: string | null
  mention_count: number
  quote: string
  url: string | null
  posting_title: string
}

/** One checklist step of a candidate's process — the tracker as data. */
export interface ProcessStepDTO {
  step_key: string
  label: string
  /** "appointment" (has a date/time) | "feedback" (pass/out) | "milestone". */
  kind: string
  /** Sort position within this process; the nine are spaced by ten. */
  position?: number
  /** True for a step this process added for itself. */
  custom?: boolean
  scheduled_at: string | null
  done_at: string | null
  /** "open" | "pass" | "out" — the tracker's uncoloured / green / red cell. */
  outcome: string
  note: string | null
}

/** The Kandidatenauswertung — one candidate measured against ONE mandate. */
export interface AssessmentDTO {
  /** Gesamtbewertung on the document's own scale, 0–10. */
  fit_score: number | null
  /** Kurzfazit, plus the paragraph that argues it. */
  verdict: string | null
  strengths: string[]
  risks: string[]
  /** Section C — written for the client's eyes, not internal notes. */
  client_summary: string | null
  technologies: string[]
  /** Provenance: "CV (Kurzversion) + Gesprächstranskript (18.09.2026)". */
  basis: string | null
  assessed_at: string | null
}

/** Section B of the Kandidatenauswertung: the PERSON, not the fit.
 *
 *  Carried on the process so a candidate's card opens with the summary
 *  already in hand. These are `candidates` columns mirrored read-only — the
 *  Gesprächszusammenfassung holds across every mandate they run on. */
export interface ProfileDTO {
  profile_summary: string | null
  /** "Schwerpunkte" — what the person is known for, as items. */
  focus_areas: string[]
  /** "Technisches Know-how" in prose. NOT `skills`, which the hard filters read. */
  technical_profile: string | null
  notice_period: string | null
  availability: string | null
  motivation: string | null
  interview_availability: string | null
  education: string[]
  /** "Weitere relevante Punkte", one per line. */
  other_notes: string | null
  other_processes: string | null
  other_process_companies: string[]
  salary_minimum: number | null
  salary_expectation: number | null
  current_salary: number | null
  salary_currency: string | null
}

export interface ProcessCandidateDTO {
  application_id: string
  candidate_id: string
  candidate_name: string
  stage: string
  presented_at: string | null
  next_appointment: string | null
  note: string | null
  steps: ProcessStepDTO[]
  /** Every step this process shows, in order: the nine-step template merged
   *  with what this process added, minus what it removed. Authoritative —
   *  the rows in `steps` exist only for steps someone has touched. */
  step_order?: string[]
  /** Null while nobody has assessed this candidate FOR THIS mandate. */
  assessment: AssessmentDTO | null
  /** The person's own summary — identical on every mandate they run on. */
  profile?: ProfileDTO
  /** Null when the figures to compare are not all there. */
  salary_fit: SalaryFitDTO | null
}

/** One mandate with every candidate running on it ("Laufende Prozesse"). */
export interface BriefingDTO {
  id: string
  /** Null when the briefing was written before a contact was recorded. */
  manager_id: string | null
  job_id: string | null
  candidate_id: string | null
  interaction_type: string
  occurred_at: string
  summary: string | null
}

/** The Kandidatenauswertung, written after a Qualifikationsgespräch. */
export interface AssessmentWriteDTO {
  fit_score?: number | null
  verdict?: string | null
  strengths?: string[]
  risks?: string[]
  client_summary?: string | null
  technologies?: string[]
  basis?: string | null
}

/** What a pasted Kandidatenauswertung was understood to say. Nothing is
 *  stored by parsing it: the form fills, the recruiter corrects and saves. */
export interface AuswertungParsedDTO {
  assessment: AssessmentWriteDTO
  profile: ProfileDTO
}

export interface ProcessJobDTO {
  job_id: string
  job_title: string
  company_id: string | null
  /** The mandate's own Ansprechpartner, not just someone at the client. */
  manager_id?: string | null
  company_name: string | null
  /** The Suchprofil — the other half of a mandate. */
  location: string | null
  must_have_skills: string[]
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  status: string | null
  candidates: ProcessCandidateDTO[]
}

/** What an uploaded file IS. Mirrors the backend's `DocumentKind`. */
export type DocumentKind = 'cv' | 'transkript' | 'zeugnis' | 'zertifikat' | 'sonstiges'

/** One file on a candidate — metadata only; the bytes come from its own URL. */
export interface CandidateDocumentDTO {
  id: string
  candidate_id: string
  kind: DocumentKind
  filename: string
  content_type: string
  byte_size: number
  created_at: string
}

/** Festanstellung, Freelance, or both — mirrors the backend's EmploymentForm. */
export type EmploymentForm = 'festanstellung' | 'freelance' | 'beides'

/** One company this tenant's candidates named as another active process.
 *  A business-development signal: whoever interviews the same profiles is a
 *  possible client. Sourced from what candidates said, not from a register. */
export interface CompetingEmployerDTO {
  company: string
  candidate_count: number
  candidates: string[]
}

/** Deterministic comparison of what a candidate needs with what a mandate
 *  pays. `negotiable` is a first-class answer, not a soft failure. */
export interface SalaryFitDTO {
  status: 'unknown' | 'fits' | 'negotiable' | 'above_band'
  detail: string | null
  minimum: number | null
  wish: number | null
}

/** PATCH body for a mandate's Suchprofil. Only what is sent is applied.
 *  `salary_max`, `location_radius_km` and `required_certifications` are hard
 *  filter inputs — editing them changes who the matcher excludes. */
export interface JobUpdatePayload {
  title?: string
  client_company_id?: string | null
  manager_id?: string | null
  location?: string | null
  location_radius_km?: number | null
  must_have_skills?: string[]
  required_certifications?: string[]
  requires_work_permit?: boolean
  salary_min?: number | null
  salary_max?: number | null
  salary_currency?: string
  status?: string
}

/** POST body for a new mandate. The title is the only thing truly required —
 *  a search can start before the band, the region or the contact are known,
 *  and refusing it would mean nothing gets written down at all. */
export interface JobCreatePayload {
  title: string
  client_company_id?: string | null
  manager_id?: string | null
  location?: string | null
  must_have_skills?: string[]
  salary_min?: number | null
  salary_max?: number | null
  salary_currency?: string
  status?: string
}

/** One data source a workspace has connected — its own ATS, today aiFind.
 *  The stored password is never part of this: `has_secret` is all the UI
 *  gets, because a value the API does not emit cannot leak. */
export interface TenantSourceDTO {
  id: string
  kind: string
  label: string | null
  username: string
  status: string
  has_secret: boolean
  /** Which instance of the source this workspace is on — the keys the
   *  connector declares in `config_needs`. Not secret: a hostname is not a
   *  credential, and the screen has to show which instance is connected. */
  config: Record<string, string>
  /** What the next run will fetch — "full" walks every manager and candidate
   *  for their details and notes, "basic" takes the lists only (ELI-14). */
  import_scope: string
  import_requested_at: string | null
  last_run_at: string | null
  last_result: Record<string, number | string>
  last_error: string | null
}

export interface AtsSourceDTO {
  /** Connector key — written to every row it imports. */
  key: string
  label: string
  /** One line saying what it is. */
  hint: string
  /** "pull" — the product reads it on a schedule with stored credentials.
   *  "file" — a human uploads an export; nothing is fetched. */
  mode: 'pull' | 'file'
  /** Which credential fields the form must ask for; empty for a file. */
  needs: string[]
  /** Non-secret instance settings the form must ask for — which tenant of a
   *  multi-tenant system this workspace is on. Empty for a source that has
   *  one address for everybody, which is most of them. */
  config_needs: string[]
}

export interface SourceCapabilitiesDTO {
  kinds: string[]
  /** What each connector is called and needs, so the UI names no system
   *  itself — the server's registry is the list. */
  sources?: AtsSourceDTO[]
  /** False when the server has no ELIGO_SECRET_KEY — no credential can be
   *  stored at all, and the form says so instead of failing on submit. */
  secrets_configured: boolean
}

// ── Importing a file a customer exported from their old system ──

export interface ImportEntityDTO {
  key: string
  label: string
  hint: string
  fields: { name: string; label: string; required: boolean }[]
}

export interface ImportRowPlanDTO {
  line: number
  /** "create" | "update" | "skip" */
  action: string
  reason: string | null
  values: Record<string, unknown>
}

export interface ImportPreviewDTO {
  entity: string
  /** How the file was read — "CSV · Trennzeichen „;" · cp1252". */
  note: string
  columns: string[]
  /** Column → canonical field. A suggestion the recruiter can correct. */
  mapping: Record<string, string>
  row_count: number
  counts: Record<string, number>
  sample: ImportRowPlanDTO[]
  problems: string[]
}

export interface ImportResultDTO {
  created: number
  updated: number
  skipped: number
  problems: string[]
}

/** Who the server thinks you are. Courtesy for the UI — never the control:
 *  every admin-only endpoint checks the same token itself. */
export interface MeDTO {
  tenant_id: string
  user_id: string | null
  name: string
  /** "admin" | "recruiter" */
  role: string
  /** False when the Clerk token carried no role claim at all. */
  role_known: boolean
}

/** A gated feature as `GET /features` reports it (backend `domain/features`). */
export interface FeatureStatusDTO {
  key: string
  /** German, from the server; rendered through `t()`. */
  label: string
  /** The operator released it for this workspace. */
  available: boolean
  /** Available AND an admin accepted the current terms. */
  enabled: boolean
  reason: string | null
  terms_version: string
  /** The binding German text the admin accepts. */
  terms: string
  accepted_by: string | null
  accepted_at: string | null
  /** For a feature reached from outside Eligo: the exact address to connect to. */
  connect_url: string | null
}

/** A change an AI client proposed (backend `domain/proposals`). Applied only
 *  when somebody in the workspace confirms it here. */
export interface ProposalDTO {
  id: string
  /** "step" | "candidate_note" */
  kind: string
  /** pending · confirmed · declined · stale · expired */
  status: string
  title: string
  tool: string
  /** The state the AI client saw. */
  before: Record<string, unknown>
  /** What confirming applies. */
  after: Record<string, unknown>
  reason: string | null
  asked_by_name: string | null
  client_id: string | null
  created_at: string
  expires_at: string
  decided_by_name: string | null
  decided_at: string | null
}

/** One line of a record's change history, from the receipt ledger. */
export interface HistoryEntryDTO {
  at: string
  actor: string
  agent: string
  field: string | null
  summary: string
  /** What the field became; null once its provenance record was erased, ""
   *  for a cleared field. Absent from a backend older than 2026-11-02. */
  value?: string | null
  source: string | null
}

/** One Art. 14 notice / opt-in request sent to one candidate.
 *
 *  `body` is the text as it was sent, with the opt-in token redacted to `…`:
 *  those links are the candidate's credential, and a recruiter holding them
 *  could answer on their behalf. */
export interface CandidateNoticeDTO {
  id: string
  candidate_id: string
  email: string
  /** pending · sent · failed · opted_in · opted_out */
  status: string
  subject: string
  body: string
  provider: string | null
  sent_at: string | null
  responded_at: string | null
  failure_reason: string | null
  requested_by: string | null
  created_at: string
}

/** Whether this deployment can send email at all. */
export interface NoticeCapabilityDTO {
  configured: boolean
  provider: string
  sender: string | null
}

/** One value read out of a job advert, and how plainly the advert said it. */
export interface ProposedValueDTO {
  value: string
  confidence: number
}

/** What a job advert appears to say (ELI-6). **Not** a mandate — reading an
 *  advert creates nothing. `must_have_skills` are hard filters that exclude
 *  candidates, so they arrive as suggestions a human ticks. */
export interface JobSpecProposalDTO {
  title: ProposedValueDTO | null
  location: ProposedValueDTO | null
  salary_min: ProposedValueDTO | null
  salary_max: ProposedValueDTO | null
  employment_form: ProposedValueDTO | null
  must_have_skills: ProposedValueDTO[]
  /** The advert's own words, so a proposal can be checked without reopening
   *  the link. */
  excerpt: string
  source_url: string | null
}


// ── Agency finder (Eligo's own leads; allowlisted workspaces only) ──

/** One signal behind a verdict or a score, with the evidence for it. */
export interface AgencyReasonDTO {
  code: string
  points: number | null
  evidence: Record<string, unknown>
}

export type AgencyVerdict = 'agency' | 'unclear' | 'client'

export interface AgencyProfileDTO {
  id: string
  group_key: string
  name: string
  primary_company_id: string
  verdict: AgencyVerdict
  score: number
  open_postings: number
  new_28d: number
  branches: number
  region: string | null
  city: string | null
  /** berufsfeld → open ads */
  fields: Record<string, number>
  reasons: AgencyReasonDTO[]
  /** UNVERIFIED — the agency's likely website, from its own ads, best first. */
  website_candidates: WebsiteCandidateDTO[]
  refreshed_at: string
}

export interface WebsiteCandidateDTO {
  domain: string
  /** Ads that name this domain. */
  ads: number
  /** The domain carries a distinctive word of the firm's name. */
  name_match: boolean
  /** Named like a known employer — probably the agency's client. */
  likely_client: boolean
  posting_ids: string[]
  /** Outcome of the Impressum check, once made. */
  check?: 'verified' | 'not_named' | 'no_impressum' | 'blocked' | 'error' | string | null
}

export interface AgencyPageDTO {
  items: AgencyProfileDTO[]
  limit: number
  offset: number
}

export interface AgencyDetailDTO {
  profile: AgencyProfileDTO
  branches: HubCompanyDTO[]
  postings: HubJobPostingDTO[]
  contacts: CompanyContactsDTO
}

/** ELI-23 "Kontakte": a contact taken from Markt, not yet a vetted manager. */
export interface ContactRowDTO {
  manager_id: string
  company_id: string
  company_name: string
  full_name: string
  role_title: string | null
  phone: string | null
  email: string | null
  linkedin_url: string | null
  xing_url: string | null
  added_at: string | null
  source: string
  source_detail: string | null
  art14_outstanding: boolean
  last_outcome: string | null
  last_call_at: string | null
  last_call_by: string | null
  next_action_at: string | null
  due: boolean
}

export interface CompanyFacetDTO {
  company_id: string
  name: string
  contacts: number
}

export interface ContactPageDTO {
  rows: ContactRowDTO[]
  total: number
  truncated: boolean
  companies: CompanyFacetDTO[]
}
