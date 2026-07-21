// Thin typed fetch client for the eligo-tech backend.
// Base path is /api/v1; the Vite dev server proxies /api → http://localhost:8000.
import type {
  CandidateDTO,
  CandidateUpdatePayload,
  CVExtractionResultDTO,
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