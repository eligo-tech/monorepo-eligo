// ELI-65 "+ Lead": a lead for a job Markt does not hold, entered by hand from
// a job ad or a LinkedIn profile. Same record as a Markt lead (stage bus_dev),
// marked "manuell"; the company is named — an existing one of that name is
// used, else it is created. The same person at that company already held is
// offered, not created a second time.

import { useState } from 'react'

import { api } from '@/api/client'
import { t } from '@/i18n'

import { ReaddDeclined, withReaddConfirm } from '../erasure/readd'
import { Button, FieldLabel, TextInput } from '../ui/forms'
import { Panel } from '../ui/primitives'
import {
  EMPTY_LEAD_FORM,
  type ExistingLead,
  type LeadCompany,
  type LeadForm,
  existingLead,
  leadPayload,
  toLeadRefusal,
} from './manualLead'

/** The "manuell" mark on a lead entered by hand. */
export function ManualLeadChip({ source }: { source?: string | null }) {
  return (
    <span
      className="inline-flex items-center rounded-md border border-cockpit-edge px-2 py-0.5 font-mono text-[12px] leading-5 text-cockpit-dim"
      title={source?.startsWith('http') ? t('Von Hand angelegt — Quelle: {url}', { url: source }) : t('Von Hand angelegt, nicht aus dem Markt.')}
    >
      {t('manuell')}
    </span>
  )
}

export function NewLead({
  onCancel,
  onSaved,
  company,
}: {
  onCancel: () => void
  onSaved: () => void
  /** ELI-78: entered on this company's page — the company is fixed. */
  company?: LeadCompany
}) {
  const [form, setForm] = useState<LeadForm>(EMPTY_LEAD_FORM)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [existing, setExisting] = useState<ExistingLead | null>(null)
  const payload = leadPayload(form, company)
  const set = (patch: Partial<LeadForm>) => {
    setForm((f) => ({ ...f, ...patch }))
    setExisting(null)
  }

  async function save() {
    if (!payload) return
    setBusy(true)
    setError(null)
    setExisting(null)
    try {
      await withReaddConfirm((override) => api.createLead({ ...payload, override_suppression: override || undefined }))
      setForm(EMPTY_LEAD_FORM)
      onSaved()
    } catch (e) {
      const held = existingLead(e)
      if (held) setExisting(held)
      else if (e instanceof ReaddDeclined) setError(e.message)
      else if (e instanceof Error && e.message.includes('source_url')) setError(t('Der Link muss eine Webadresse sein (https://…).'))
      else setError(t('Nicht gespeichert — bitte erneut versuchen.'))
    }
    setBusy(false)
  }

  // ELI-78: the person is held as a manager nobody has spoken to yet — move
  // them to Leads instead of entering them a second time.
  async function toLeads(managerId: string) {
    setBusy(true)
    setError(null)
    try {
      await api.managerToLead(managerId)
      setExisting(null)
      setForm(EMPTY_LEAD_FORM)
      onSaved()
    } catch (e) {
      setError(toLeadRefusal(e) ?? t('Nicht gespeichert — bitte erneut versuchen.'))
    }
    setBusy(false)
  }

  return (
    <Panel className="p-4">
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault()
          void save()
        }}
      >
        <TextInput label={t('Job *')} value={form.jobTitle} onChange={(jobTitle) => set({ jobTitle })} placeholder={t('z. B. Senior Java Entwickler (m/w/d)')} />
        <TextInput
          label={t('Link zur Stellenanzeige / LinkedIn-Profil')}
          value={form.sourceUrl}
          onChange={(sourceUrl) => set({ sourceUrl })}
          placeholder="https://"
        />
        <TextInput label={t('Name Ansprechpartner *')} value={form.fullName} onChange={(fullName) => set({ fullName })} />
        <TextInput label={t('Jobtitel Ansprechpartner')} value={form.roleTitle} onChange={(roleTitle) => set({ roleTitle })} />
        {company ? (
          <div className="min-w-0">
            <FieldLabel>{t('Firma')}</FieldLabel>
            <span className="block py-2 text-[14px] text-cockpit-text">{company.name}</span>
          </div>
        ) : (
          <TextInput label={t('Firma *')} value={form.companyName} onChange={(companyName) => set({ companyName })} />
        )}
        <TextInput label={t('E-Mail')} type="email" value={form.email} onChange={(email) => set({ email })} />
        <TextInput label={t('Nummer')} value={form.phone} onChange={(phone) => set({ phone })} />
        <p className="self-end text-[12px] text-cockpit-faint">
          {company
            ? t('Der Lead erscheint unter Leads; nach dem Erstkontakt „Zu Managern“.')
            : t('Gibt es die Firma hier schon (gleicher Name), wird der Lead dort angelegt, sonst wird sie neu angelegt.')}
        </p>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
          <Button type="submit" tone="primary" disabled={busy || !payload}>
            {t('Lead anlegen')}
          </Button>
          <Button onClick={onCancel} disabled={busy}>
            {t('Abbrechen')}
          </Button>
          {existing && (
            <span className="flex flex-wrap items-center gap-2 text-[13px] text-gold-400">
              {existing.stage === 'bus_dev'
                ? t('{name} ist bei dieser Firma schon ein Lead.', { name: existing.fullName })
                : t('{name} ist bei dieser Firma schon als Manager gespeichert.', { name: existing.fullName })}
              <a
                href={`#managers/${existing.managerId}`}
                className="rounded-lg border border-cockpit-line px-3 py-1.5 font-mono text-[12px] text-cockpit-text hover:border-cockpit-edge"
              >
                {t('Vorhandenen Eintrag öffnen')}
              </a>
              {existing.stage !== 'bus_dev' && (
                <Button onClick={() => void toLeads(existing.managerId)} disabled={busy}>
                  {t('Zu Leads')}
                </Button>
              )}
            </span>
          )}
          {error && <span className="text-[13px] text-coral-400">{error}</span>}
        </div>
      </form>
    </Panel>
  )
}
