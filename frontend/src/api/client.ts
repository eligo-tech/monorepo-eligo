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
  HubEmployerHitDTO,
  HubJobPostingDTO,
  SavedSearchDTO,
  JobDTO,
  MatchResultDTO,
  PipelineBoardDTO,
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

export const api = {
  health: () => request<{ status: string }>('/health'),
  candidates: () => request<CandidateDTO[]>('/candidates'),

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
  /** Client + prospect companies — used to name the client on a mandate. */
  companies: () => request<CompanyDTO[]>('/companies'),
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

  /**
   * Search the corpus. Returns EMPLOYERS rolled up across their sites, each
   * carrying the roles that made it match.
   */
  hubSearch: (params: { q?: string; city?: string; minRoles?: number; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params.q) qs.set('q', params.q)
    if (params.city) qs.set('city', params.city)
    if (params.minRoles) qs.set('min_roles', String(params.minRoles))
    qs.set('limit', String(params.limit ?? 40))
    return request<HubEmployerHitDTO[]>(`/hub/search?${qs}`)
  },

  /** This workspace's standing market questions. */
  savedSearches: () => request<SavedSearchDTO[]>('/searches'),

  /** Save a standing question. Crawls nothing — the nightly job acts on it. */
  createSavedSearch: (body: {
    label: string
    q?: string | null
    city?: string | null
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
}

export { ApiError }