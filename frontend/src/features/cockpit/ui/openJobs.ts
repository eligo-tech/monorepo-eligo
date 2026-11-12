// ELI-33: what a company is hiring for now — its open jobs in Markt (every
// site of the employer it is linked to) — on the company page and beside a
// manager or lead, so a call starts from what is actually open.

import type { CompanyMarketDTO } from '@/api/types'

/** The first `limit` jobs, and how many more the company has. */
export function jobsShown(market: CompanyMarketDTO, limit: number) {
  const shown = market.jobs.slice(0, limit)
  return { shown, more: Math.max(0, market.total - shown.length) }
}
