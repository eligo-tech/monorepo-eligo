// ELI-37: the concrete jobs a lead is connected to — the ads that name the
// person, and this workspace's own job taken from one or owned by them.

import type { LeadJobDTO } from '@/api/types'

/** "Pflegefachkraft (m/w/d) · Ulm" — the place only when the record has one. */
export const leadJobLine = (job: LeadJobDTO) => [job.title, job.location].filter(Boolean).join(' · ')

/** The workspace's own job page, or null when it holds none for this ad. */
export const mandateHref = (job: LeadJobDTO) => (job.job_id ? `#cockpit/${job.job_id}` : null)
