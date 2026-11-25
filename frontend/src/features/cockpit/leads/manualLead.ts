// ELI-65 "+ Lead": a lead entered by hand — from a job ad elsewhere or a
// LinkedIn profile — for a job Markt does not hold. Pure helpers for the form.

import type { LeadCreateBody } from '@/api/types'

import { refusal } from '../erasure/erasureView'
import { ApiError } from '@/api/client'
import { t } from '@/i18n'

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

/** The company a lead is entered for from its own page (ELI-78). */
export interface LeadCompany {
  id: string
  name: string
}

/** The request, or null while Job, Name or Firma is missing. From a
 *  company page the company is fixed: its id goes along, so the lead lands
 *  at that company and not at the first one of its name. */
export function leadPayload(form: LeadForm, fixed?: LeadCompany | null): LeadCreateBody | null {
  const job = form.jobTitle.trim()
  const name = form.fullName.trim()
  const company = fixed ? fixed.name : form.companyName.trim()
  if (!job || !name || !company) return null
  return {
    job_title: job,
    full_name: name,
    company_name: company,
    ...(fixed ? { company_id: fixed.id } : {}),
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

/** ELI-78: why "Zu Leads" was refused (409 `{code}`), in words; null if it
 *  was not such a refusal. */
export function toLeadRefusal(e: unknown): string | null {
  switch (refusal(e)?.code) {
    case 'has_contact':
      return t('Mit dieser Person gab es schon Kontakt — sie bleibt Manager.')
    case 'has_mandate':
      return t('Diese Person hat ein Mandat — sie bleibt Manager.')
    case 'imported':
      return t('Aus dem eigenen System importiert — bleibt Manager.')
    case 'do_not_contact':
      return t('Diese Person möchte nicht kontaktiert werden — sie bleibt Manager.')
    default:
      return null
  }
}

/** The person already held at that company (409 `lead_exists`), else null. */
export function existingLead(e: unknown): ExistingLead | null {
  if (refusal(e)?.code !== 'lead_exists' || !(e instanceof ApiError)) return null
  const detail = (JSON.parse(e.message) as { detail: { manager_id: string; stage: string; full_name: string } }).detail
  return { managerId: detail.manager_id, stage: detail.stage, fullName: detail.full_name }
}
