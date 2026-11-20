// ELI-65 "+ Lead": a lead entered by hand — from a job ad elsewhere or a
// LinkedIn profile — for a job Markt does not hold. Pure helpers for the form.

import type { LeadCreateBody } from '@/api/types'

import { refusal } from '../erasure/erasureView'
import { ApiError } from '@/api/client'

export interface LeadForm {
  jobTitle: string
  sourceUrl: string
  fullName: string
  roleTitle: string
  companyName: string
  email: string
  phone: string
}

export const EMPTY_LEAD_FORM: LeadForm = {
  jobTitle: '',
  sourceUrl: '',
  fullName: '',
  roleTitle: '',
  companyName: '',
  email: '',
  phone: '',
}

const opt = (v: string) => v.trim() || null

/** The request, or null while Job, Name or Firma is missing. */
export function leadPayload(form: LeadForm): LeadCreateBody | null {
  const job = form.jobTitle.trim()
  const name = form.fullName.trim()
  const company = form.companyName.trim()
  if (!job || !name || !company) return null
  return {
    job_title: job,
    full_name: name,
    company_name: company,
    role_title: opt(form.roleTitle),
    email: opt(form.email),
    phone: opt(form.phone),
    source_url: opt(form.sourceUrl),
  }
}

export interface ExistingLead {
  managerId: string
  /** "bus_dev" (a lead) or "manager". */
  stage: string
  fullName: string
}

/** The person already held at that company (409 `lead_exists`), else null. */
export function existingLead(e: unknown): ExistingLead | null {
  if (refusal(e)?.code !== 'lead_exists' || !(e instanceof ApiError)) return null
  const detail = (JSON.parse(e.message) as { detail: { manager_id: string; stage: string; full_name: string } }).detail
  return { managerId: detail.manager_id, stage: detail.stage, fullName: detail.full_name }
}
