// Thin typed fetch client for the eligo-tech backend.
// Base path is /api/v1; the Vite dev server proxies /api → http://localhost:8000.
import type {
  CandidateDTO,
  CandidateUpdatePayload,
  CompanyDTO,
  CVExtractionResultDTO,
  HubCompanyDTO,
  HubCompanyLinkDTO,
  HubCorpusStatsDTO,
  AdoptResultDTO,
  HubEmployerHitDTO,
  ManagerDTO,
  ManagerInteractionDTO,
  HubSearchPageDTO,
  HubFacetsDTO,
  HubJobPostingDTO,
  SavedSearchDTO,
  ProjectDTO,
  ProjectDetailDTO,
  ProjectCandidateDTO,
  CompanyContactsDTO,
  CriteriaSuggestionDTO,
  JobDTO,
  MatchResultDTO,
  PipelineBoardDTO,
  CandidateDocumentDTO,
  CompetingEmployerDTO,
  DocumentKind,
  HistoryEntryDTO,
  ImportEntityDTO,
  ImportPreviewDTO,
  ImportResultDTO,
  MeDTO,
  SourceCapabilitiesDTO,
  TenantSourceDTO,
  JobUpdatePayload,
  ProcessJobDTO,
  ProcessStepDTO,
  ReportingOverviewDTO,
} from './types'

// Dev: '/api/v1' (Vite proxies to :8000). Prod: set VITE_API_BASE_URL to the
// deployed backend, e.g. https://eligo-api.up.railway.app/api/v1
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
  health: () => request<{ status: string }>('/health'),
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

  /** Fetch a single candidate's full record (used to seed the edit form). */
  candidate: (id: string) => request<CandidateDTO>(`/candidates/${id}`),

  /** Apply a manual recruiter edit. Each changed field is committed through the
   *  backend verification gate as a human-verified change (with a receipt). */
  updateCandidate: (id: string, patch: CandidateUpdatePayload) =>
    request<CandidateDTO>(`/candidates/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  /** Fetch the original uploaded CV (PDF) for a candidate. null if none on file. */
  async candidateCv(id: string): Promise<Blob | null> {
    const res = await fetch(`${BASE}/candidates/${id}/cv`, { headers: await authHeaders() })
    if (res.status === 404) return null
    if (!res.ok) throw new ApiError(res.status, res.statusText)
    return res.blob()
  },
  jobs: () => request<JobDTO[]>('/jobs'),

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
  /** Market corpus: companies aggregated from public sources, most actively
   *  hiring first. Distinct from /companies, which is the tenant's own CRM. */
  hubCompanies: (params?: { q?: string; hiringOnly?: boolean; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.q) qs.set('q', params.q)
    if (params?.hiringOnly) qs.set('hiring_only', 'true')
    qs.set('limit', String(params?.limit ?? 200))
    return request<HubCompanyDTO[]>(`/hub/companies?${qs}`)
  },
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
    minRoles?: number
    limit?: number
    cursor?: string | null
    minRelevance?: number
    /** false asks for the literal query — "trotzdem nach „muenchen" suchen". */
    correct?: boolean
  }) => {
    const qs = new URLSearchParams()
    if (params.q) qs.set('q', params.q)
    if (params.city) qs.set('city', params.city)
    // Repeated params, not comma-joined: a Berufsfeld contains commas
    // ("Krankenpflege, Rettungsdienst und Geburtshilfe").
    params.regions?.forEach((r) => qs.append('region', r))
    params.berufsfelder?.forEach((b) => qs.append('berufsfeld', b))
    if (params.minRoles) qs.set('min_roles', String(params.minRoles))
    qs.set('limit', String(params.limit ?? 40))
    if (params.cursor) qs.set('cursor', params.cursor)
    if (params.minRelevance && params.minRelevance > 1)
      qs.set('min_relevance', String(params.minRelevance))
    if (params.correct === false) qs.set('correct', 'false')
    return request<HubSearchPageDTO>(`/hub/search?${qs}`)
  },

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
  ): Promise<{ items: ManagerDTO[]; total: number }> => {
    const res = await fetch(`${BASE}/managers?limit=${limit}`, {
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
    email?: string | null
    phone?: string | null
    linkedin_url?: string | null
    source?: string
    source_detail?: string | null
  }) => request<ManagerDTO>('/managers', { method: 'POST', body: JSON.stringify(body) }),

  /** People we hold data on who have not been informed (GDPR Art. 14). */
  managersOwingArt14: () => request<ManagerDTO[]>('/managers/art14-outstanding'),

  manager: (id: string) => request<ManagerDTO>(`/managers/${id}`),

  managerInteractions: (id: string) =>
    request<ManagerInteractionDTO[]>(`/managers/${id}/interactions`),

  /** Records that the subject has been informed. Its own call, not a PATCH
   *  field: it asserts something happened in the world. */
  markManagerArt14Notified: (id: string) =>
    request<ManagerDTO>(`/managers/${id}/art14-notified`, { method: 'POST' }),

  // --- Projects: named groupings of target companies ---------------------

  projects: () => request<ProjectDTO[]>('/projects'),

  /** A project needs a name and nothing else. 409 if the name is taken. */
  createProject: (name: string) =>
    request<ProjectDTO>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),

  project: (id: string) => request<ProjectDetailDTO>(`/projects/${id}`),

  renameProject: (id: string, name: string) =>
    request<ProjectDTO>(`/projects/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    }),

  async deleteProject(id: string): Promise<void> {
    const res = await fetch(`${BASE}/projects/${id}`, {
      method: 'DELETE',
      headers: await authHeaders(),
    })
    if (!res.ok) throw new ApiError(res.status, res.statusText)
  },

  /** Watched employers that are in no project yet. */
  unassignedWatched: () => request<ProjectCandidateDTO[]>('/projects/unassigned'),

  /** Watched employers not yet in this project. */
  projectCandidates: (id: string) =>
    request<ProjectCandidateDTO[]>(`/projects/${id}/candidates`),

  /** Put corpus companies in the project. Idempotent; returns the project. */
  addProjectCompanies: (id: string, hubCompanyIds: string[]) =>
    request<ProjectDetailDTO>(`/projects/${id}/companies`, {
      method: 'POST',
      body: JSON.stringify({ hub_company_ids: hubCompanyIds }),
    }),

  /** Attach a person to a company in a project. A name is enough; `source`
   *  decides the Art. 14 obligation and defaults to "found by us". */
  addProjectContact: (
    projectId: string,
    hubCompanyId: string,
    body: {
      full_name: string
      role_title?: string | null
      email?: string | null
      phone?: string | null
      linkedin_url?: string | null
      source?: string
      source_detail?: string | null
    },
  ) =>
    request<ManagerDTO>(
      `/projects/${projectId}/companies/${hubCompanyId}/contacts`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  async removeProjectCompany(id: string, hubCompanyId: string): Promise<void> {
    const res = await fetch(`${BASE}/projects/${id}/companies/${hubCompanyId}`, {
      method: 'DELETE',
      headers: await authHeaders(),
    })
    if (!res.ok) throw new ApiError(res.status, res.statusText)
  },

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

  /** Run a saved search against the corpus. Read-only. */
  savedSearchResults: (id: string) =>
    request<HubEmployerHitDTO[]>(`/searches/${id}/results?limit=40`),

  /** Open roles for one hub company. */
  hubCompanyPostings: (id: string) =>
    request<HubJobPostingDTO[]>(`/hub/companies/${id}/postings?limit=200`),

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
      clear?: ('scheduled_at' | 'done_at' | 'note')[]
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
  /** Funnel + dwell + KPIs, derived live from the record. */
  reportingOverview: () => request<ReportingOverviewDTO>('/reporting/overview'),

  /**
   * Upload a PDF CV for extraction. `persist=false` previews only (writes
   * nothing); `persist=true` creates a candidate from the accepted fields.
   */
  async extractCv(file: File, persist = false): Promise<CVExtractionResultDTO> {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`${BASE}/documents/extract-cv?persist=${persist}`, {
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
  tenantSources: () => request<TenantSourceDTO[]>('/tenant-sources'),
  sourceCapabilities: () =>
    request<SourceCapabilitiesDTO>('/tenant-sources/capabilities'),
  /** Connect or re-configure a source. `secret` is write-only and optional on
   *  an update, so a username can be fixed without re-typing the password. */
  saveTenantSource: (
    kind: string,
    body: { username: string; secret?: string; label?: string; status?: string },
  ) =>
    request<TenantSourceDTO>(`/tenant-sources/${kind}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteTenantSource: (kind: string) =>
    request<void>(`/tenant-sources/${kind}`, { method: 'DELETE' }),
  /** Ask for an import. Queues it — the scheduled runner performs it. */
  requestImport: (kind: string) =>
    request<{ queued: boolean; detail: string }>(`/tenant-sources/${kind}/import`, {
      method: 'POST',
    }),

  /** Companies this tenant's candidates named as other active processes. */
  competingEmployers: () =>
    request<CompetingEmployerDTO[]>('/candidates/competing-employers'),

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
}

export { ApiError }