// Thin typed fetch client for the Eligo Labs backend.
// Base path is /api/v1; the Vite dev server proxies /api → http://localhost:8000.
import type {
  ConsultantDTO,
  TargetDTO,
  TargetWritePayload,
  TeamDTO,
  TrackingDTO,
  TrackingPeriod,
  TrackingTilesDTO,
  AgencyDetailDTO,
  BrandingDTO,
  BrandingWrite,
  CoverSheetParams,
  CoverSheetPreviewDTO,
  AgencyPageDTO,
  AgencyVerdict,
  EraseBody,
  ErasureRequestDTO,
  JobSpecProposalDTO,
  CandidateDTO,
  CandidateUpdatePayload,
  CompanyDTO,
  CompanyOverviewRowDTO,
  CreatorDTO,
  CompanyPageDTO,
  CompanyStatus,
  NewCompanyPayload,
  CVExtractionResultDTO,
  HubCompanyLinkDTO,
  HubCorpusStatsDTO,
  AdoptPostingsResultDTO,
  AdoptResultDTO,
  ContactPageDTO,
  FollowUpDTO,
  FollowUpSuggestionDTO,
  FollowUpWrite,
  ManagerDTO,
  RemoveReason,
  LeadCreateBody,
  LeadPrefillDTO,
  ManagerPhoneDTO,
  ManagerInteractionDTO,
  HubSearchPageDTO,
  HubFacetsDTO,
  SavedSearchDTO,
  CompanyContactsDTO,
  AssessmentDTO,
  AssessmentWriteDTO,
  JobCreatePayload,
  AuswertungParsedDTO,
  EvaluationDTO,
  EvaluationPromptDTO,
  EvaluationProviderDTO,
  BriefingDTO,
  CriteriaSuggestionDTO,
  JobDTO,
  MatchResultDTO,
  PipelineBoardDTO,
  CandidateDocumentDTO,
  CandidateNoticeDTO,
  DoNotContactDTO,
  CompetingEmployerDTO,
  DocumentKind,
  HistoryEntryDTO,
  ImportEntityDTO,
  ImportPreviewDTO,
  ImportResultDTO,
  MeDTO,
  FeatureStatusDTO,
  ProposalDTO,
  NoticeCapabilityDTO,
  SourceCapabilitiesDTO,
  TenantSourceDTO,
  JobUpdatePayload,
  ProcessJobDTO,
  ProcessStepDTO,
  ReportingOverviewDTO,
  SwitchboardDTO,
  SearchResultsDTO,
} from './types'

// Dev: '/api/v1' (Vite proxies to :8000). Prod: set VITE_API_BASE_URL to the
// deployed backend, e.g. https://monorepo-eligo-production.up.railway.app/api/v1
const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

// When Clerk auth is active a token getter is registered here (see
// auth/ClerkTokenBridge); every request then carries the session JWT so the
// backend can resolve the tenant. Without it, requests go out unauthenticated
// (the default-tenant demo mode).
let tokenGetter: (() => Promise<string | null>) | null = null
export function setAuthTokenGetter(fn: (() => Promise<string | null>) | null): void {
  tokenGetter = fn
}
async function authHeaders(): Promise<Record<string, string>> {
  if (!tokenGetter) return {}
  const token = await tokenGetter().catch(() => null)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()), ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new ApiError(res.status, body || res.statusText)
  }
  return res.json() as Promise<T>
}

/** POST a file plus form fields. Shared by every upload: the browser must
 *  set the multipart boundary itself, so no content-type header here. */
async function upload<T>(
  path: string,
  file: File,
  fields: Record<string, string>,
): Promise<T> {
  const body = new FormData()
  body.append('file', file)
  for (const [key, value] of Object.entries(fields)) body.append(key, value)
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    body,
    headers: await authHeaders(),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new ApiError(res.status, detail || res.statusText)
  }
  return res.json() as Promise<T>
}

export const api = {
  /** The pool, with the size of the WHOLE pool alongside it.
   *
   *  The cockpit searches and filters these rows in the browser, so a page
   *  that is smaller than the pool makes every search a search of the first
   *  N names — a failure that looks exactly like an empty result. The count
   *  comes from `X-Total-Count`, and the screen compares the two. */
  candidatesPage: async (
    limit = 1000,
  ): Promise<{ items: CandidateDTO[]; total: number }> => {
    const res = await fetch(`${BASE}/candidates?limit=${limit}`, {
      headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    })
    if (!res.ok) {
      throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
    }
    const items = (await res.json()) as CandidateDTO[]
    // A proxy that strips the header must not be read as "the pool is empty".
    const header = Number(res.headers.get('X-Total-Count'))
    return { items, total: Number.isFinite(header) && header > 0 ? header : items.length }
  },

  candidates: () => request<CandidateDTO[]>('/candidates?limit=1000'),

  /** ELI-52: the command bar's search — this workspace's candidates,
   *  mandates, companies and contacts by name, a few of each. Never Markt. */
  search: (q: string, init?: RequestInit) =>
    request<SearchResultsDTO>(`/search?q=${encodeURIComponent(q)}`, init),

  /** Fetch a single candidate's full record (used to seed the edit form). */
  candidate: (id: string) => request<CandidateDTO>(`/candidates/${id}`),

  /** A new client. Needed before a mandate can hang off one, and there was
   *  no way to do it from the UI at all. */
  createCompany: (body: Partial<NewCompanyPayload> & { name: string }) =>
    request<CompanyDTO>('/companies', {
      method: 'POST',
      body: JSON.stringify({ is_client: true, ...body }),
    }),

  /** ELI-43: Lead / Kunde on the company page — a receipt names the person. */
  setCompanyStatus: (id: string, status: CompanyStatus) =>
    request<CompanyPageDTO>(`/companies/${id}/status`, {
      method: 'PUT',
      body: JSON.stringify({ status }),
    }),

  /** ELI-64: "Rahmenvertrag abgeschlossen am" — null takes it back. */
  setFrameworkContract: (id: string, signedOn: string | null) =>
    request<CompanyPageDTO>(`/companies/${id}/framework-contract`, {
      method: 'PUT',
      body: JSON.stringify({ signed_on: signedOn }),
    }),

  /** ELI-15/64: Ist vs. Ziel, goals and the Prozess funnel for one period. */
  tracking: (period: TrackingPeriod, who = 'team') =>
    request<TrackingDTO>(
      `/activity/tracking?period=${encodeURIComponent(period)}&who=${encodeURIComponent(who)}`,
    ),
  consultants: () => request<ConsultantDTO[]>('/activity/consultants'),
  /** ELI-74, admin only: every person's figures side by side. `members` are
   *  the workspace's member ids, so somebody with nothing recorded still
   *  gets a row. */
  trackingTeam: (period: TrackingPeriod, members: readonly string[] = []) => {
    const q = new URLSearchParams({ period })
    for (const m of members) q.append('members', m)
    return request<TeamDTO>(`/activity/tracking/team?${q.toString()}`)
  },
  targets: () => request<TargetDTO[]>('/activity/targets'),
  /** Admin only. */
  setTarget: (body: TargetWritePayload) =>
    request<TargetDTO>('/activity/targets', { method: 'PUT', body: JSON.stringify(body) }),
  deleteTarget: async (id: string): Promise<void> => {
    // 204, no body — `request` would try to parse one.
    const res = await fetch(`${BASE}/activity/targets/${id}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    })
    if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
  },
  /** Which tracking tiles THIS person shows on the Cockpit. */
  trackingTiles: () => request<TrackingTilesDTO>('/activity/preferences'),
  setTrackingTiles: (tiles: string[]) =>
    request<TrackingTilesDTO>('/activity/preferences', {
      method: 'PUT',
      body: JSON.stringify({ tiles }),
    }),

  /** A new mandate. `POST /jobs` has always existed; nothing called it. */
  createJob: (body: JobCreatePayload) =>
    request<JobDTO>('/jobs', { method: 'POST', body: JSON.stringify(body) }),

  /** Apply a manual recruiter edit. Each changed field is committed through the
   *  backend verification gate as a human-verified change (with a receipt). */
  updateCandidate: (id: string, patch: CandidateUpdatePayload) =>
    request<CandidateDTO>(`/candidates/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  /** Write somebody down who has no CV and came from no import (ELI-17).
   *
   *  `source` is quoted verbatim into the Art. 14 notice the person
   *  receives, so it carries human words ("Empfehlung"), never a code. */
  createCandidate: (body: {
    full_name: string
    email?: string
    phone?: string
    current_title?: string
    current_company?: string
    location?: string
    skills?: string[]
    salary_expectation?: number | null
    /** `WorkPermitStatus` value; omitted, the backend stores `unknown`. */
    work_permit?: string
    source?: string
    /** Erased here on request and come back of their own accord (409 otherwise). */
    override_suppression?: boolean
  }) =>
    request<CandidateDTO>('/candidates', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Fetch the original uploaded CV (PDF) for a candidate. null if none on file. */
  async candidateCv(id: string): Promise<Blob | null> {
    const res = await fetch(`${BASE}/candidates/${id}/cv`, { headers: await authHeaders() })
    if (res.status === 404) return null
    if (!res.ok) throw new ApiError(res.status, res.statusText)
    return res.blob()
  },
  /** The workspace's mandates. `status` filters in the DATABASE: the list is
   *  capped, so filtering what already arrived shows "the active ones among
   *  the first hundred" and labels them the active ones. */
  jobs: (status?: string) =>
    request<JobDTO[]>(`/jobs${status ? `?status=${encodeURIComponent(status)}` : ''}`),

  /** Reuse an old mandate — "alte Jobs als Kopie wiederverwenden" (ELI-7).
   *
   *  The Suchprofil comes across; the pipeline, the briefings and the feedback
   *  do not. This is the way back from `inactive`, which cannot be reopened. */
  copyJob: (jobId: string, title?: string) =>
    request<JobDTO>(`/jobs/${jobId}/copy`, {
      method: 'POST',
      body: JSON.stringify(title ? { title } : {}),
    }),

  /** Read a job advert into a proposed Suchprofil (ELI-6).
   *
   *  Creates nothing: the answer fills the form in and the recruiter saves
   *  it. Pass `url` for a link, or `text` when the advert sits behind a
   *  login or a portal that renders in JavaScript — which most German
   *  applicant-tracking portals do. */
  parseJobSpec: (body: { url?: string; text?: string }) =>
    request<JobSpecProposalDTO>('/jobs/parse-spec', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Muss-Kriterien the mandate's own title names, drawn from the workspace's
   *  skill vocabulary. Proposals — a human clicks the ones that are really
   *  non-negotiable, because a hard criterion excludes people. */
  criteriaSuggestions: (jobId: string) =>
    request<CriteriaSuggestionDTO[]>(`/jobs/${jobId}/criteria-suggestions`),
  /** Client + prospect companies — used to name the client on a mandate. */
  /** The tenant's own accounts. `limit` matters: the default is 100 and an
   *  imported book runs to hundreds, so a caller building a name lookup must
   *  ask for all of them or most rows resolve to nothing. */
  companies: (limit = 500) => request<CompanyDTO[]>(`/companies?limit=${limit}`),
  /** Corpus totals, counted server-side. Never derive these from a page. */
  hubStats: () => request<HubCorpusStatsDTO>('/hub/stats'),

  /** Filter options with counts, taken from the corpus itself. */
  hubFacets: () => request<HubFacetsDTO>('/hub/facets'),

  /**
   * Search the corpus. Returns EMPLOYERS rolled up across their sites, each
   * carrying the roles that made it match.
   */
  hubSearch: (params: {
    q?: string
    city?: string
    regions?: string[]
    berufsfelder?: string[]
    /** Job families, e.g. ['tech'] (backend `hub/families.py`). */
    families?: string[]
    minRoles?: number
    limit?: number
    cursor?: string | null
    minRelevance?: number
    /** false asks for the literal query — "trotzdem nach „muenchen" suchen". */
    correct?: boolean
    /** ELI-27: leave out firms whose name marks staffing or placement. */
    excludeAgencies?: boolean
    /** ELI-27: employer by open ads in the corpus — s · m · l · xl. */
    sizes?: string[]
    /** ELI-54: headcount buckets ("51-150", "10001+"); unknown size is left out. */
    employees?: string[]
  }) => {
    const qs = new URLSearchParams()
    if (params.q) qs.set('q', params.q)
    if (params.city) qs.set('city', params.city)
    // Repeated params, not comma-joined: a Berufsfeld contains commas
    // ("Krankenpflege, Rettungsdienst und Geburtshilfe").
    params.regions?.forEach((r) => qs.append('region', r))
    params.berufsfelder?.forEach((b) => qs.append('berufsfeld', b))
    params.families?.forEach((f) => qs.append('family', f))
    if (params.minRoles) qs.set('min_roles', String(params.minRoles))
    qs.set('limit', String(params.limit ?? 40))
    if (params.cursor) qs.set('cursor', params.cursor)
    if (params.minRelevance && params.minRelevance > 1)
      qs.set('min_relevance', String(params.minRelevance))
    if (params.correct === false) qs.set('correct', 'false')
    if (params.excludeAgencies) qs.set('exclude_agencies', 'true')
    params.sizes?.forEach((s) => qs.append('size', s))
    params.employees?.forEach((e) => qs.append('employees', e))
    return request<HubSearchPageDTO>(`/hub/search?${qs}`)
  },

  /** Ads selected on Markt → Jobs as leads, their employer adopted (ELI-22). */
  adoptHubPostings: (postingIds: string[]) =>
    request<AdoptPostingsResultDTO>('/hub/postings/adopt', {
      method: 'POST',
      body: JSON.stringify({ posting_ids: postingIds }),
    }),

  /**
   * Take a corpus employer into this workspace, optionally with a contact.
   * The crossing from shared observation to system-of-record — it goes through
   * the verification gate server-side and leaves a receipt.
   */
  adoptHubCompany: (
    hubCompanyId: string,
    manager?: {
      full_name: string
      role_title?: string | null
      email?: string | null
      phone?: string | null
      source?: string
      source_detail?: string | null
    } | null,
  ) =>
    request<AdoptResultDTO>(`/hub/companies/${hubCompanyId}/adopt`, {
      method: 'POST',
      body: JSON.stringify({ manager: manager ?? null }),
    }),

  /** Contacts in this workspace. `q` matches name, role or company. */
  /** The contact pool plus its true size — same contract as `candidatesPage`,
   *  and for the same reason: the screen ranks these rows in the browser. */
  managersPage: async (
    limit = 1000,
    createdBy = '',
  ): Promise<{ items: ManagerDTO[]; total: number }> => {
    // ELI-23: the Manager screen lists vetted managers; bus-dev contacts from
    // Markt have their own list until they are moved over.
    // ELI-69: `createdBy` — an account id or "me" ("Angelegt von").
    const by = createdBy ? `&created_by=${encodeURIComponent(createdBy)}` : ''
    const res = await fetch(`${BASE}/managers?limit=${limit}&stage=manager${by}`, {
      headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    })
    if (!res.ok) {
      throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
    }
    const items = (await res.json()) as ManagerDTO[]
    const header = Number(res.headers.get('X-Total-Count'))
    return { items, total: Number.isFinite(header) && header > 0 ? header : items.length }
  },

  managers: (params?: { q?: string; companyId?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.q) qs.set('q', params.q)
    if (params?.companyId) qs.set('company_id', params.companyId)
    qs.set('limit', String(params?.limit ?? 200))
    return request<ManagerDTO[]>(`/managers?${qs}`)
  },

  /** Add a contact at one of this workspace's own companies. */
  createManager: (body: {
    company_id: string
    full_name: string
    first_name?: string | null
    last_name?: string | null
    role_title?: string | null
    department?: string | null
    email?: string | null
    phone?: string | null
    linkedin_url?: string | null
    source?: string
    source_detail?: string | null
    /** Erased here on request and come back of their own accord (409 otherwise). */
    override_suppression?: boolean
  }) => request<ManagerDTO>('/managers', { method: 'POST', body: JSON.stringify(body) }),

  /** ELI-45: correct a contact's details. Send only what changed — a new
   *  e-mail or direct number of someone erased here is refused (409) unless
   *  `override_suppression` says they came back of their own accord. The
   *  answer carries no counts (job_count etc.): merge, do not replace. */
  updateManager: (
    id: string,
    patch: {
      role_title?: string | null
      department?: string | null
      email?: string | null
      phone?: string | null
      /** ELI-46: the whole list, replacing the stored one. Not with `phone`. */
      phones?: ManagerPhoneDTO[]
      linkedin_url?: string | null
      /** ELI-66: every field of a lead — name, company, XING, address. */
      full_name?: string
      first_name?: string | null
      last_name?: string | null
      company_id?: string
      xing_url?: string | null
      street?: string | null
      postal_code?: string | null
      city?: string | null
      override_suppression?: boolean
    },
  ) => request<ManagerDTO>(`/managers/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  /** People we hold data on who have not been informed (GDPR Art. 14). */
  managersOwingArt14: () => request<ManagerDTO[]>('/managers/art14-outstanding'),

  manager: (id: string) => request<ManagerDTO>(`/managers/${id}`),

  /** ELI-33: Unternehmen — every company here with counts, A–Z. */
  companiesOverview: (createdBy = '') =>
    request<CompanyOverviewRowDTO[]>(
      createdBy ? `/companies/overview?created_by=${encodeURIComponent(createdBy)}` : '/companies/overview',
    ),

  /** ELI-69: the accounts that added leads, managers or companies in this
   *  workspace — the choices of "Angelegt von". */
  creators: (kind: 'leads' | 'managers' | 'companies') =>
    request<CreatorDTO[]>(
      kind === 'companies'
        ? '/companies/creators'
        : `/managers/creators?stage=${kind === 'leads' ? 'bus_dev' : 'manager'}`,
    ),

  /** ELI-33: one company — managers, leads, mandates, Impressum switchboard. */
  companyPage: (id: string) => request<CompanyPageDTO>(`/companies/${id}/page`),

  /** ELI-39: website, VAT id and register from the company's Impressum, with
   *  the page and fetch date — null while none is verified. Read only. */
  companyRegister: (id: string) => request<SwitchboardDTO | null>(`/companies/${id}/register`),

  /** ELI-33 2b: "Das ist unser Unternehmen" — link these Markt sites. */
  confirmMarketLink: (id: string, hubCompanyIds: string[], dismissIds: string[] = []) =>
    request<CompanyPageDTO>(`/companies/${id}/market-links`, {
      method: 'POST',
      body: JSON.stringify({ hub_company_ids: hubCompanyIds, dismiss_ids: dismissIds }),
    }),

  /** ELI-33 2b: "Keiner davon" — never suggested again. */
  dismissMarketSites: (id: string, hubCompanyIds: string[]) =>
    request<CompanyPageDTO>(`/companies/${id}/market-dismissals`, {
      method: 'POST',
      body: JSON.stringify({ hub_company_ids: hubCompanyIds }),
    }),

  /** ELI-33: undo a wrong link (the daily job does not put it back). */
  undoMarketLink: (id: string) => request<CompanyPageDTO>(`/companies/${id}/market-links`, { method: 'DELETE' }),

  managerInteractions: (id: string) =>
    request<ManagerInteractionDTO[]>(`/managers/${id}/interactions`),

  /** ELI-40: the Termine tab — this manager's meetings, booked or held. */
  managerAppointments: (id: string) =>
    request<ManagerInteractionDTO[]>(`/managers/${id}/appointments`),

  /** File one touch on this manager by hand — the call that just happened,
   *  rather than the one an import will bring tomorrow. */
  logManagerInteraction: (
    id: string,
    body: {
      interaction_type: string
      summary: string
      occurred_at?: string
      candidate_id?: string | null
      job_id?: string | null
      /** ELI-22: how a call ended, and when to call again. */
      outcome?: string | null
      next_action_at?: string | null
      /** ELI-32: the person asked not to be contacted again. */
      do_not_contact?: boolean
    },
  ) =>
    request<ManagerInteractionDTO>(`/managers/${id}/interactions`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Kontakte (ELI-23): contacts taken from Markt (stage bus_dev) — open call-backs first (ELI-38), then newest. */
  callListContacts: (params: { companyId?: string; q?: string; dueOnly?: boolean; notes?: 'none' | 'with'; noInterest?: boolean; createdBy?: string }) => {
    const qs = new URLSearchParams()
    if (params.companyId) qs.set('company_id', params.companyId)
    if (params.q) qs.set('q', params.q)
    if (params.dueOnly) qs.set('due_only', 'true')
    // ELI-62: "Noch keine Notiz" / "Mit Notizen".
    if (params.notes) qs.set('notes', params.notes)
    // ELI-60: only the leads with "Kein Interesse" (hidden otherwise).
    if (params.noInterest) qs.set('no_interest', 'true')
    // ELI-69: "Angelegt von" — an account id or "me".
    if (params.createdBy) qs.set('created_by', params.createdBy)
    return request<ContactPageDTO>(`/hub/call-list/contacts?${qs}`)
  },

  /** ELI-44: Wiedervorlagen — by default this workspace's open ones, soonest first. */
  followUps: (params: { status?: 'open' | 'done' | 'all'; managerId?: string; candidateId?: string } = {}) => {
    const qs = new URLSearchParams()
    if (params.status) qs.set('status', params.status)
    if (params.managerId) qs.set('manager_id', params.managerId)
    if (params.candidateId) qs.set('candidate_id', params.candidateId)
    return request<FollowUpDTO[]>(`/follow-ups?${qs}`)
  },

  createFollowUp: (body: FollowUpWrite) =>
    request<FollowUpDTO>('/follow-ups', { method: 'POST', body: JSON.stringify(body) }),

  /** Move, edit, mark done (`status: 'done'`) or reopen. */
  updateFollowUp: (
    id: string,
    body: { due_date?: string; due_time?: string | null; text?: string; status?: 'open' | 'done' },
  ) => request<FollowUpDTO>(`/follow-ups/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  /** Admins only (ELI-27) — a 403 otherwise; everyone else marks it done. */
  deleteFollowUp: async (id: string): Promise<void> => {
    const res = await fetch(`${BASE}/follow-ups/${id}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    })
    if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
  },

  /** The follow-up dates a note names, resolved against the note's day.
   *  Reads only — the recruiter confirms by creating one. */
  suggestFollowUps: (text: string, referenceDate: string) =>
    request<{ suggestions: FollowUpSuggestionDTO[] }>('/follow-ups/suggest', {
      method: 'POST',
      body: JSON.stringify({ text, reference_date: referenceDate }),
    }),

  /** ELI-65 "+ Lead": a lead entered by hand. 409 `lead_exists` names the
   *  person already held at that company. */
  createLead: (body: LeadCreateBody) =>
    request<ManagerDTO>('/managers/leads', { method: 'POST', body: JSON.stringify(body) }),

  /** ELI-73: fill "+ Lead" from a job ad — a link Markt holds, or the pasted
   *  text. A proposal; the link is looked up, never opened. */
  prefillLead: (body: { url?: string; text?: string }) =>
    request<LeadPrefillDTO>('/managers/leads/prefill', { method: 'POST', body: JSON.stringify(body) }),

  /** ELI-23: move a bus-dev contact to Managers after the first contact. */
  promoteManager: (id: string) => request<ManagerDTO>(`/managers/${id}/promote`, { method: 'POST' }),

  /** ELI-78: "Zu Leads" — a manager added by hand, not contacted yet, back to
   *  Leads. 409 `{code}` once contacted, owning a mandate or imported. */
  managerToLead: (id: string) => request<ManagerDTO>(`/managers/${id}/to-lead`, { method: 'POST' }),

  /** ELI-66: "Entfernen" — off the Leads list with a reason; hidden, never
   *  deleted, undone by `reviveLead`. */
  removeLead: (id: string, reason: RemoveReason, note?: string) =>
    request<ManagerDTO>(`/managers/${id}/remove`, {
      method: 'POST',
      body: JSON.stringify({ reason, note: note || null }),
    }),

  /** ELI-60: "Wieder als Lead aufnehmen" — clears "Kein Interesse". */
  reviveLead: (id: string) => request<ManagerDTO>(`/managers/${id}/no-interest`, { method: 'DELETE' }),

  /** Records that the subject has been informed. Its own call, not a PATCH
   *  field: it asserts something happened in the world. */
  markManagerArt14Notified: (id: string) =>
    request<ManagerDTO>(`/managers/${id}/art14-notified`, { method: 'POST' }),

  /** This workspace's standing market questions. */
  savedSearches: () => request<SavedSearchDTO[]>('/searches'),

  /** Save a standing question. Crawls nothing — the nightly job acts on it. */
  createSavedSearch: (body: {
    label: string
    q?: string | null
    city?: string | null
    regions?: string[]
    berufsfelder?: string[]
    min_roles?: number
  }) =>
    request<SavedSearchDTO>('/searches', { method: 'POST', body: JSON.stringify(body) }),

  async deleteSavedSearch(id: string): Promise<void> {
    const res = await fetch(`${BASE}/searches/${id}`, {
      method: 'DELETE',
      headers: await authHeaders(),
    })
    if (!res.ok) throw new ApiError(res.status, res.statusText)
  },

  /** Agency finder: ranked agencies, best first. 404 outside the
   *  `agency_finder_tenants` allowlist — see `agencyCopy.probeAgencyFinder`. */
  agencies: (params: {
    verdict: AgencyVerdict[]
    region?: string
    berufsfeld?: string
    includeChains?: boolean
    limit?: number
    offset?: number
  }) => {
    const q = new URLSearchParams()
    for (const v of params.verdict) q.append('verdict', v)
    if (params.region) q.set('region', params.region)
    if (params.berufsfeld) q.set('berufsfeld', params.berufsfeld)
    if (params.includeChains) q.set('include_chains', 'true')
    q.set('limit', String(params.limit ?? 50))
    q.set('offset', String(params.offset ?? 0))
    return request<AgencyPageDTO>(`/hub/agencies?${q.toString()}`)
  },
  agency: (id: string) => request<AgencyDetailDTO>(`/hub/agencies/${id}`),
  /** Take an agency into this workspace as a lead — the same receipted
   *  crossing as an employer. 409 when it is already in the CRM. */
  adoptAgency: (
    id: string,
    manager?: { full_name: string; role_title?: string | null; email?: string | null; phone?: string | null; source?: string; source_detail?: string | null } | null,
  ) =>
    request<AdoptResultDTO>(`/hub/agencies/${id}/adopt`, {
      method: 'POST',
      body: JSON.stringify({ manager: manager ?? null }),
    }),
  /** Authenticated GET of the first agency — whether this workspace may see
   *  the agency finder at all. Only the status matters. */
  agencyProbe: async (): Promise<Response> =>
    fetch(`${BASE}/hub/agencies?limit=1`, { headers: await authHeaders() }),

  /** People an employer's public ads name as contacts. Reads the corpus;
   *  fetches and stores nothing. */
  hubCompanyContacts: (id: string) =>
    request<CompanyContactsDTO>(`/hub/companies/${id}/contacts`),

  /** Mark this workspace's interest in a corpus company. Idempotent. */
  trackHubCompany: (id: string, relationship: HubCompanyLinkDTO['relationship'] = 'watching') =>
    request<HubCompanyLinkDTO>(`/hub/companies/${id}/track`, {
      method: 'PUT',
      body: JSON.stringify({ relationship }),
    }),

  /** Drop the overlay row. The shared corpus company itself is untouched. */
  async untrackHubCompany(id: string): Promise<void> {
    const res = await fetch(`${BASE}/hub/companies/${id}/track`, {
      method: 'DELETE',
      headers: await authHeaders(),
    })
    if (!res.ok) throw new ApiError(res.status, res.statusText)
  },
  board: () => request<PipelineBoardDTO>('/pipeline/board'),

  /** "Laufende Prozesse": mandates with their candidates and the nine steps,
   *  as the recruiter's tracker records them. */
  processes: () => request<ProcessJobDTO[]>('/pipeline/processes'),

  /** What was said ABOUT a mandate — the briefing call and what followed. */
  jobBriefings: (jobId: string) =>
    request<BriefingDTO[]>(`/jobs/${jobId}/briefings`),

  /** Every Gesprächsnotiz on one candidate, newest first.
   *
   *  The rows live in `manager_interactions` — the table has carried a
   *  nullable `candidate_id` since it was created and not one of the 366
   *  imported notes ever filled it (ELI-9). */
  candidateInteractions: (id: string) =>
    request<ManagerInteractionDTO[]>(`/candidates/${id}/interactions`),

  /** File one touch on this candidate — a call, a message, or a call that
   *  went unanswered. */
  logCandidateInteraction: (
    id: string,
    body: {
      interaction_type: string
      summary: string
      occurred_at?: string
      job_id?: string | null
      /** ELI-32: the person asked not to be contacted again. */
      do_not_contact?: boolean
    },
  ) =>
    request<ManagerInteractionDTO>(`/candidates/${id}/interactions`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Write down a briefing. The contact is optional: the conversation that
   *  defines a mandate often happens before anyone is in the record. */
  addBriefing: (
    jobId: string,
    body: {
      summary: string
      occurred_at?: string
      manager_id?: string | null
      interaction_type?: string
    },
  ) =>
    request<BriefingDTO>(`/jobs/${jobId}/briefings`, {
      method: 'POST',
      body: JSON.stringify({ interaction_type: 'briefing', ...body }),
    }),

  /** The Kandidatenauswertung for one candidate on one mandate. A full
   *  replacement: a half-updated verdict is worse than none. */
  setAssessment: (applicationId: string, body: AssessmentWriteDTO) =>
    request<AssessmentDTO>(`/pipeline/applications/${applicationId}/assessment`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  /** What was said about the CANDIDATES on this mandate, newest first. */
  jobFeedback: (jobId: string) =>
    request<BriefingDTO[]>(`/jobs/${jobId}/feedback`),

  /** One remark about one candidate. A row per remark — it used to be
   *  written into the process step's single `note`, where the second
   *  remark replaced the first. */
  addFeedback: (
    jobId: string,
    body: {
      summary: string
      candidate_id: string
      occurred_at?: string
      manager_id?: string | null
    },
  ) =>
    request<BriefingDTO>(`/jobs/${jobId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ interaction_type: 'feedback', ...body }),
    }),

  /** Read a pasted Kandidatenauswertung into form fields. Stores nothing:
   *  the recruiter sees what was understood, corrects it, and saves. */
  parseAuswertung: (text: string) =>
    request<AuswertungParsedDTO>('/pipeline/auswertung/parse', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  /** The Bewertungs-Prompt for one candidate on one mandate (ELI-41):
   *  assembled by code, for the recruiter to paste into Claude. */
  evaluationPrompt: (applicationId: string) =>
    request<EvaluationPromptDTO>(
      `/pipeline/applications/${applicationId}/bewertung-prompt`,
    ),

  /** Is a model configured for the in-app evaluation (ELI-42)? */
  evaluationProvider: () =>
    request<EvaluationProviderDTO>('/pipeline/evaluation/provider'),

  /** The open AI evaluation of one process; rejects (404) when none. */
  evaluation: (applicationId: string) =>
    request<EvaluationDTO>(`/pipeline/applications/${applicationId}/evaluation`),

  /** Ask the model. The result is a PROPOSAL — confirm or decline it via
   *  `confirmProposal` / `declineProposal`; nothing is stored before. */
  evaluate: (applicationId: string) =>
    request<EvaluationDTO>(`/pipeline/applications/${applicationId}/evaluation`, {
      method: 'POST',
    }),

  /** Put a candidate on a mandate. Idempotent per pair — assigning twice
   *  returns the existing process rather than making a second one. */
  assignToJob: (candidateId: string, jobId: string) =>
    request<{ id: string }>('/pipeline/applications', {
      method: 'POST',
      body: JSON.stringify({ candidate_id: candidateId, job_id: jobId }),
    }),

  /** Set a date, a verdict ("pass"/"out") or a note on one step. */
  setProcessStep: (
    applicationId: string,
    stepKey: string,
    body: {
      scheduled_at?: string | null
      done_at?: string | null
      outcome?: 'open' | 'pass' | 'out' | null
      note?: string | null
      /** Fields to empty. Omitting a field means "unchanged", so taking a
       *  value back needs saying so. */
      clear?: ('scheduled_at' | 'done_at' | 'note' | 'fee_eur')[]
      /** ELI-64: Honorar (€) — only on the Vertrag step. */
      fee_eur?: number | null
    },
  ) =>
    request<ProcessStepDTO>(
      `/pipeline/applications/${applicationId}/steps/${stepKey}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    ),
  /** Add a step to ONE process, after the step `after` names (null = first).
   *  The nine are a template; a Probearbeitstag is this process's own. */
  addProcessStep: (applicationId: string, body: { label: string; after?: string | null }) =>
    request<ProcessStepDTO>(`/pipeline/applications/${applicationId}/steps`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Take a step out of ONE process. 409 when it already happened — clear the
   *  entry first; the tracker must not be able to deny the past. */
  removeProcessStep: async (applicationId: string, stepKey: string): Promise<void> => {
    const res = await fetch(
      `${BASE}/pipeline/applications/${applicationId}/steps/${stepKey}`,
      { method: 'DELETE', headers: await authHeaders() },
    )
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new ApiError(res.status, body || res.statusText)
    }
  },

  /** Rank the candidate pool against one job (hard filters → soft ranking). */
  matchJob: (jobId: string, includeRejected = true) =>
    request<MatchResultDTO[]>('/matching/job', {
      method: 'POST',
      body: JSON.stringify({ job_id: jobId, include_rejected: includeRejected }),
    }),
  /** Erase a person from this workspace (GDPR Art. 17/21). Admins only;
   *  cannot be undone. */
  eraseCandidate: (id: string, body: EraseBody) =>
    request<ErasureRequestDTO>(`/erasure/candidates/${id}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  eraseManager: (id: string, body: EraseBody) =>
    request<ErasureRequestDTO>(`/erasure/managers/${id}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  /** The handled requests. Names nobody. */
  erasureRequests: () => request<ErasureRequestDTO[]>('/erasure/requests'),

  /** ELI-32: "Wieder kontaktierbar" — undo "Nicht mehr kontaktieren". */
  liftDoNotContact: (subject: 'candidate' | 'manager', id: string) =>
    request<DoNotContactDTO>(`/${subject}s/${id}/do-not-contact`, { method: 'DELETE' }),
  /** ELI-32: "Bestätigung senden" — one mail to the marked person, on this click. */
  sendDoNotContactConfirmation: (subject: 'candidate' | 'manager', id: string) =>
    request<{ status: 'sent' }>(`/${subject}s/${id}/do-not-contact/confirmation`, { method: 'POST' }),

  /** Funnel + dwell + KPIs, derived live from the record. */
  reportingOverview: () => request<ReportingOverviewDTO>('/reporting/overview'),

  /**
   * Upload a PDF CV for extraction. `persist=false` previews only (writes
   * nothing); `persist=true` creates a candidate from the accepted fields.
   */
  async extractCv(
    file: File,
    persist = false,
    overrideSuppression = false,
    /** Arbeitserlaubnis chosen in the upload dialog — stored on persist only. */
    workPermit?: string,
  ): Promise<CVExtractionResultDTO> {
    const body = new FormData()
    body.append('file', file)
    const q =
      `persist=${persist}${overrideSuppression ? '&override_suppression=true' : ''}` +
      (persist && workPermit ? `&work_permit=${encodeURIComponent(workPermit)}` : '')
    const res = await fetch(`${BASE}/documents/extract-cv?${q}`, {
      method: 'POST',
      body, // let the browser set the multipart boundary
      headers: await authHeaders(),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      throw new ApiError(res.status, detail || res.statusText)
    }
    return res.json() as Promise<CVExtractionResultDTO>
  },

  /** One mandate, with its briefing score (ELI-47). */
  job: (jobId: string) => request<JobDTO>(`/jobs/${jobId}`),

  /** Edit a mandate's Suchprofil. Each changed field leaves a receipt. */
  updateJob: (jobId: string, patch: JobUpdatePayload) =>
    request<JobDTO>(`/jobs/${jobId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  /** Who the server thinks you are, and what you may do. */
  me: () => request<MeDTO>('/me'),

  /** What has changed on one record, newest first, from the ledger. */
  history: (entityType: string, entityId: string) =>
    request<HistoryEntryDTO[]>(`/verification/history/${entityType}/${entityId}`),

  // ── Importing a file ──
  importEntities: () => request<ImportEntityDTO[]>('/imports/entities'),

  /** Read the file and report what importing it WOULD do. Writes nothing. */
  importPreview: (file: File, entity: string, mapping?: Record<string, string>) =>
    upload<ImportPreviewDTO>('/imports/preview', file, {
      entity,
      ...(mapping ? { mapping: JSON.stringify(mapping) } : {}),
    }),

  /** Import the file with the mapping the recruiter confirmed. */
  importCommit: (file: File, entity: string, mapping: Record<string, string>) =>
    upload<ImportResultDTO>('/imports/commit', file, {
      entity,
      mapping: JSON.stringify(mapping),
    }),

  // ── This workspace's own data sources ──
  // ── What an AI client proposed, waiting for a human ──
  proposals: (pendingOnly = true) =>
    request<ProposalDTO[]>(`/proposals${pendingOnly ? '?pending_only=true' : ''}`),
  /** Applies it as you. 409 when the record changed since it was proposed. */
  confirmProposal: (id: string) =>
    request<ProposalDTO>(`/proposals/${id}/confirm`, { method: 'POST' }),
  declineProposal: (id: string) =>
    request<ProposalDTO>(`/proposals/${id}/decline`, { method: 'POST' }),

  // ── Gated features (AI access, interview assistant) ──
  features: () => request<FeatureStatusDTO[]>('/features'),
  /** Accept the terms the admin was SHOWN: the server refuses (409) if the
   *  version changed in the meantime. */
  acceptFeature: (key: string, termsVersion: string) =>
    request<FeatureStatusDTO>(`/features/${key}/consent`, {
      method: 'POST',
      body: JSON.stringify({ terms_version: termsVersion }),
    }),
  revokeFeature: (key: string) =>
    request<FeatureStatusDTO>(`/features/${key}/consent`, { method: 'DELETE' }),

  tenantSources: () => request<TenantSourceDTO[]>('/tenant-sources'),
  sourceCapabilities: () =>
    request<SourceCapabilitiesDTO>('/tenant-sources/capabilities'),
  /** Connect or re-configure a source. `secret` is write-only and optional on
   *  an update, so a username can be fixed without re-typing the password. */
  saveTenantSource: (
    kind: string,
    body: {
      username: string
      secret?: string
      label?: string
      status?: string
      config?: Record<string, string>
    },
  ) =>
    request<TenantSourceDTO>(`/tenant-sources/${kind}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteTenantSource: (kind: string) =>
    request<void>(`/tenant-sources/${kind}`, { method: 'DELETE' }),
  /** Ask for an import. Queues it — the scheduled runner performs it. */
  /** Queue an import. `scope` picks the pass the next run makes (ELI-14):
   *  "full" walks every manager and candidate for their details and their
   *  notes; "basic" takes the lists and is minutes rather than an hour. */
  requestImport: (kind: string, scope: 'full' | 'basic' = 'full') =>
    request<{ queued: boolean; detail: string }>(`/tenant-sources/${kind}/import`, {
      method: 'POST',
      body: JSON.stringify({ scope }),
    }),

  /** Companies this tenant's candidates named as other active processes. */
  competingEmployers: () =>
    request<CompetingEmployerDTO[]>('/candidates/competing-employers'),

  /** Every Art.-14 notice sent to one candidate, newest first. */
  candidateNotices: (candidateId: string) =>
    request<CandidateNoticeDTO[]>(`/candidates/${candidateId}/notices`),

  /** Send the notice and the opt-in question. One candidate, one click —
   *  there is deliberately no batch endpoint behind this. */
  sendCandidateNotice: (candidateId: string) =>
    request<CandidateNoticeDTO>(`/candidates/${candidateId}/notices`, {
      method: 'POST',
    }),

  /** Can this deployment send at all? Read before offering the button, so a
   *  recruiter is told "not configured" instead of meeting a 503. */
  noticeCapability: () => request<NoticeCapabilityDTO>('/notices/capability'),

  /** Every file on a candidate (metadata only). */
  candidateDocuments: (candidateId: string) =>
    request<CandidateDocumentDTO[]>(`/documents/candidate/${candidateId}`),

  /** Where a stored file is served from — used as an <a href>. */
  documentUrl: (documentId: string) => `${BASE}/documents/${documentId}/content`,

  /** Attach a Zeugnis, Zertifikat or any other file to a candidate. */
  async uploadDocument(
    candidateId: string,
    file: File,
    kind: DocumentKind,
  ): Promise<CandidateDocumentDTO> {
    const body = new FormData()
    body.append('file', file)
    body.append('candidate_id', candidateId)
    body.append('kind', kind)
    const res = await fetch(`${BASE}/documents/upload`, {
      method: 'POST',
      body,
      headers: await authHeaders(),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      throw new ApiError(res.status, detail || res.statusText)
    }
    return res.json() as Promise<CandidateDocumentDTO>
  },

  /**
   * Read a Gesprächstranskript for the qualification fields.
   *
   * Returns PROPOSALS and stores the transcript as evidence — nothing is
   * written to the candidate. Confirming a value is an ordinary PATCH, which
   * is what makes the receipt say a human asserted it.
   */
  async extractTranscript(
    candidateId: string,
    file: File,
  ): Promise<CVExtractionResultDTO> {
    const body = new FormData()
    body.append('file', file)
    body.append('candidate_id', candidateId)
    const res = await fetch(`${BASE}/documents/extract-transcript`, {
      method: 'POST',
      body,
      headers: await authHeaders(),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      throw new ApiError(res.status, detail || res.statusText)
    }
    return res.json() as Promise<CVExtractionResultDTO>
  },

  /**
   * Read an attached Zeugnis or Zertifikat for what it attests.
   *
   * Returns PROPOSALS, each with the sentence it came from — nothing is
   * written. Confirming is an ordinary PATCH, as with the transcript.
   */
  readDocument: (documentId: string) =>
    request<CVExtractionResultDTO>(`/documents/${documentId}/read`, { method: 'POST' }),

  // ── Cover sheet (ELI-20) ──────────────────────────────────────────────

  /** The workspace's CI. Everyone reads it; only admins change it. */
  branding: () => request<BrandingDTO>('/branding'),
  saveBranding: (body: BrandingWrite) =>
    request<BrandingDTO>('/branding', { method: 'PUT', body: JSON.stringify(body) }),
  async uploadLogo(file: File): Promise<BrandingDTO> {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`${BASE}/branding/logo`, { method: 'PUT', body, headers: await authHeaders() })
    if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
    return res.json() as Promise<BrandingDTO>
  },
  async deleteLogo(): Promise<void> {
    const res = await fetch(`${BASE}/branding/logo`, { method: 'DELETE', headers: await authHeaders() })
    if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
  },
  /** The logo as a blob, null when none is set. */
  async brandingLogo(): Promise<Blob | null> {
    const res = await fetch(`${BASE}/branding/logo`, { headers: await authHeaders() })
    if (res.status === 404) return null
    if (!res.ok) throw new ApiError(res.status, res.statusText)
    return res.blob()
  },
  /** ELI-55: the header icon — PNG, JPEG or SVG (rebuilt by the server). */
  async uploadHeaderIcon(file: File): Promise<BrandingDTO> {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`${BASE}/branding/header-icon`, { method: 'PUT', body, headers: await authHeaders() })
    if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
    return res.json() as Promise<BrandingDTO>
  },
  async deleteHeaderIcon(): Promise<void> {
    const res = await fetch(`${BASE}/branding/header-icon`, { method: 'DELETE', headers: await authHeaders() })
    if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
  },
  /** The header icon as a blob, null when none is set. */
  async brandingHeaderIcon(): Promise<Blob | null> {
    const res = await fetch(`${BASE}/branding/header-icon`, { headers: await authHeaders() })
    if (res.status === 404) return null
    if (!res.ok) throw new ApiError(res.status, res.statusText)
    return res.blob()
  },
  /** What the PDF will hold — empty sections, files left out. Reads only. */
  coverSheetPreview: (candidateId: string, params: CoverSheetParams) =>
    request<CoverSheetPreviewDTO>(`/candidates/${candidateId}/cover-sheet/preview?${coverQuery(params)}`),
  /** The PDF. The server records the download as a disclosure (a receipt). */
  async coverSheet(candidateId: string, params: CoverSheetParams): Promise<Blob> {
    const res = await fetch(`${BASE}/candidates/${candidateId}/cover-sheet?${coverQuery(params)}`, {
      headers: await authHeaders(),
    })
    if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
    return res.blob()
  },
}

function coverQuery(params: CoverSheetParams): string {
  const q = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === 'string' && value.trim()) q.set(key, value.trim())
  }
  return q.toString()
}

export { ApiError }