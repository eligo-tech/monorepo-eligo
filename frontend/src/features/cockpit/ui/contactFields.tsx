// A contact's details as the recruiter types them (ELI-45).
//
// "Hier kann man nur die E-Mail hinzufügen": a contact created with a new
// mandate got a role and an e-mail and nothing else, and the Manager page had
// no way to add a phone afterwards. One field set now serves the three places
// that add or edit a contact — new mandate, "Ansprechpartner festlegen" and
// the Manager page — so they cannot drift apart again. The fields are the
// columns `managers` already has; nothing here invents a new one.

import { t } from '@/i18n'

import type { ManagerDTO } from '@/api/types'
import { TextInput } from './forms'

export const CONTACT_KEYS = ['role_title', 'department', 'email', 'phone', 'linkedin_url'] as const
export type ContactKey = (typeof CONTACT_KEYS)[number]
export type ContactDraft = Record<ContactKey, string>
export type ContactPayload = Record<ContactKey, string | null>

export const EMPTY_CONTACT: ContactDraft = {
  role_title: '',
  department: '',
  email: '',
  phone: '',
  linkedin_url: '',
}

const clean = (v: string) => v.trim() || null

/** What a new contact is created with: trimmed, blanks as null. */
export function contactPayload(draft: ContactDraft): ContactPayload {
  return Object.fromEntries(CONTACT_KEYS.map((k) => [k, clean(draft[k])])) as ContactPayload
}

export function contactDraftOf(m: ManagerDTO): ContactDraft {
  return Object.fromEntries(CONTACT_KEYS.map((k) => [k, m[k] ?? ''])) as ContactDraft
}

/** Only what changed. An unchanged address is not sent, so it is not checked
 *  against the erasure list again; an emptied field is sent as null. */
export function contactPatch(m: ManagerDTO, draft: ContactDraft): Partial<ContactPayload> {
  const patch: Partial<ContactPayload> = {}
  for (const k of CONTACT_KEYS) {
    const next = clean(draft[k])
    if (next !== (m[k] ?? null)) patch[k] = next
  }
  return patch
}

export function ContactFields({
  value,
  onChange,
  withPhone = true,
}: {
  value: ContactDraft
  onChange: (next: ContactDraft) => void
  /** ELI-46: the Manager page edits every number in its own list instead. */
  withPhone?: boolean
}) {
  const set = (k: ContactKey) => (v: string) => onChange({ ...value, [k]: v })
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <TextInput label={t('Rolle')} value={value.role_title} onChange={set('role_title')} placeholder="Head of IT" />
      <TextInput label={t('Abteilung')} value={value.department} onChange={set('department')} placeholder={t('optional')} />
      <TextInput label={t('E-Mail')} type="email" value={value.email} onChange={set('email')} placeholder={t('optional')} />
      {withPhone && (
        <TextInput label={t('Telefon')} value={value.phone} onChange={set('phone')} placeholder="+49 30 1234567" />
      )}
      <div className="sm:col-span-2">
        <TextInput
          label={t('LinkedIn-Profil')}
          value={value.linkedin_url}
          onChange={set('linkedin_url')}
          placeholder="https://www.linkedin.com/in/…"
        />
      </div>
    </div>
  )
}
