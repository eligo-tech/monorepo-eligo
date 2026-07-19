// Thin typed fetch client for the eligo-tech backend.
// Base path is /api/v1; the Vite dev server proxies /api → http://localhost:8000.
import type {
  CandidateDTO,
  CVExtractionResultDTO,
  JobDTO,
  MatchResultDTO,
  PipelineBoardDTO,
  ReportingOverviewDTO,
} from './types'

// Dev: '/api/v1' (Vite proxies to :8000). Prod: set VITE_API_BASE_URL to the
// deployed backend, e.g. https://eligo-api.up.railway.app/api/v1
const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

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
    headers: { 'Content-Type': 'application/json' },
    ...init,
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

  /** Fetch the original uploaded CV (PDF) for a candidate. null if none on file. */
  async candidateCv(id: string): Promise<Blob | null> {
    const res = await fetch(`${BASE}/candidates/${id}/cv`)
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
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      throw new ApiError(res.status, detail || res.statusText)
    }
    return res.json() as Promise<CVExtractionResultDTO>
  },
}

export { ApiError }