// ELI-65 "+ Lead": a lead entered by hand — from a job ad elsewhere or a
// LinkedIn profile — for a job Markt does not hold. Pure helpers for the form.

import type { LeadCreateBody } from '@/api/types'

import { refusal } from '../erasure/erasureView'
import { ApiError } from '@/api/client'
import { t } from '@/i18n'

import { parseProfileLink } from './profileLink'

export interface LeadForm {
  /** ELI-77: the person's LinkedIn/XING profile, pasted. */
  profileUrl: string
  /** ELI-73: the fields were read from ad text the recruiter pasted. */
  fromPastedText: boolean
  jobTitle: string
  sourceUrl: string
  fullName: string
  roleTitle: string
  companyName: string
  email: string
  phone: string
}

export const EMPTY_LEAD_FORM: LeadForm = {
  profileUrl: '',
  fromPastedText: false,
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
  // ELI-77: a link in the profile box must be a person's profile.
  const profile = form.profileUrl.trim() ? parseProfileLink(form.profileUrl) : null
  if (form.profileUrl.trim() && !profile) return null
  return {
    job_title: job,
    full_name: name,
    company_name: company,
    ...(fixed ? { company_id: fixed.id } : {}),
    role_title: opt(form.roleTitle),
    email: opt(form.email),
    phone: opt(form.phone),
    source_url: opt(form.sourceUrl),
    profile_url: profile?.url ?? null,
    ...(form.fromPastedText ? { from_pasted_text: true } : {}),
  }
}

/** ELI-77: the form after a profile link is pasted or edited. The name the
 *  link plainly gives fills the name field — only while that field is empty
 *  or still holds this helper's own earlier prefill, never over what the
 *  recruiter typed. `prefilled` is what to pass back next time. Nothing is
 *  fetched: the name is read from the link alone. */
export function withProfile(
  form: LeadForm,
  raw: string,
  prefilled: string,
): { form: LeadForm; prefilled: string } {
  const name = parseProfileLink(raw)?.name ?? null
  const ours = !form.fullName.trim() || form.fullName === prefilled
  if (name && ours) return { form: { ...form, profileUrl: raw, fullName: name }, prefilled: name }
  return { form: { ...form, profileUrl: raw }, prefilled: ours ? '' : prefilled }
}

export interface ExistingLead {
  managerId: string
  /** "bus_dev" (a lead) or "manager". */
  stage: string
  fullName: string
  /** ELI-77: held with the same LinkedIn/XING profile (any company). */
  byProfile?: boolean
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
  const detail = (
    JSON.parse(e.message) as { detail: { manager_id: string; stage: string; full_name: string; match?: string } }
  ).detail
  return {
    managerId: detail.manager_id,
    stage: detail.stage,
    fullName: detail.full_name,
    ...(detail.match === 'profile' ? { byProfile: true } : {}),
  }
}
