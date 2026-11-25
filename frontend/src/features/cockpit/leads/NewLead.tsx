// ELI-65 "+ Lead": a lead for a job Markt does not hold, entered by hand from
// a job ad or a LinkedIn profile. Same record as a Markt lead (stage bus_dev),
// marked "manuell"; the company is named — an existing one of that name is
// used, else it is created. The same person at that company already held is
// offered, not created a second time.

import { useState } from 'react'

import { api } from '@/api/client'
import { t } from '@/i18n'

import { ReaddDeclined, withReaddConfirm } from '../erasure/readd'
import type { LeadPrefillDTO } from '@/api/types'

import { Button, FIELD, FieldLabel, TextInput } from '../ui/forms'
import { Panel } from '../ui/primitives'
import {
  EMPTY_LEAD_FORM,
  type ExistingLead,
  type LeadCompany,
  type LeadForm,
  existingLead,
  leadPayload,
  toLeadRefusal,
  withProfile,
} from './manualLead'
import { parseProfileLink } from './profileLink'
import { PREFILL_FIELDS, applyPrefill, defaultPerson, filledBy } from './adPrefill'

/** ELI-73: `source_detail` of a lead read from pasted ad text — stored by
 *  the server, compared here, so it is not copy. */
const FROM_PASTED_TEXT = 'aus eingefügtem Anzeigentext'

/** The "manuell" mark on a lead entered by hand. */
export function ManualLeadChip({ source }: { source?: string | null }) {
  return (
    <span
      className="inline-flex items-center rounded-md border border-cockpit-edge px-2 py-0.5 font-mono text-[12px] leading-5 text-cockpit-dim"
      title={
        source?.startsWith('http')
          ? t('Von Hand angelegt — Quelle: {url}', { url: source })
          : source === FROM_PASTED_TEXT
            ? t('Von Hand angelegt — aus eingefügtem Anzeigentext.')
            : t('Von Hand angelegt, nicht aus dem Markt.')
      }
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
  // ELI-77: the name this form filled in from the profile link, so a changed
  // link may replace it — but never a name the recruiter typed.
  const [prefilled, setPrefilled] = useState('')
  const payload = leadPayload(form, company)
  const profile = form.profileUrl.trim() ? parseProfileLink(form.profileUrl) : null
  const pasteProfile = (raw: string) => {
    const next = withProfile(form, raw, prefilled)
    setForm(next.form)
    setPrefilled(next.prefilled)
    setExisting(null)
  }
  const set = (patch: Partial<LeadForm>) => {
    setForm((f) => ({ ...f, ...patch }))
    setExisting(null)
  }

  // ELI-73: fill from a job ad. The link is LOOKED UP in Markt, never opened;
  // an ad Markt does not hold asks for its text, read by the same rules.
  const [ad, setAd] = useState<LeadPrefillDTO | null>(null)
  const [person, setPerson] = useState<number | null>(null)
  const [pasting, setPasting] = useState(false)
  const [adText, setAdText] = useState('')
  const [reading, setReading] = useState(false)
  const [adError, setAdError] = useState<string | null>(null)
  // What the fills wrote: a later fill or person pick may replace exactly
  // these fields — never one the recruiter typed.
  const [filled, setFilled] = useState<Partial<LeadForm>>({})
  const fill = (found: LeadPrefillDTO, pick: number | null, previous: Partial<LeadForm>) =>
    setForm((f) => {
      const applied = applyPrefill(f, found, pick, previous)
      // A company fixed by its page stays that company.
      const next = company ? { ...applied, companyName: f.companyName } : applied
      const still = Object.fromEntries(
        PREFILL_FIELDS.filter((k) => previous[k] !== undefined && next[k] === previous[k]).map((k) => [k, next[k]]),
      )
      setFilled({ ...still, ...filledBy(f, next) })
      return next
    })
  async function readAd(body: { url?: string; text?: string }) {
    setReading(true)
    setAdError(null)
    try {
      const found = await api.prefillLead(body)
      setAd(found)
      if (found.found === 'not_in_corpus') {
        setPasting(true)
      } else {
        const pick = defaultPerson(found)
        setPerson(pick)
        // The link looked up is replaced by the ad's own page (one spelling).
        fill(found, pick, body.url ? { ...filled, sourceUrl: form.sourceUrl } : filled)
        setExisting(null)
      }
    } catch {
      setAdError(t('Anzeige konnte nicht gelesen werden — bitte erneut versuchen.'))
    }
    setReading(false)
  }
  const pickPerson = (i: number) => {
    if (!ad) return
    setPerson(i)
    // That person's details replace the last pick's — not what was typed.
    fill(ad, i, filled)
  }

  async function save() {
    if (!payload) return
    setBusy(true)
    setError(null)
    setExisting(null)
    try {
      await withReaddConfirm((override) => api.createLead({ ...payload, override_suppression: override || undefined }))
      setForm(EMPTY_LEAD_FORM)
      setPrefilled('')
      setAd(null)
      setAdText('')
      setFilled({})
      onSaved()
    } catch (e) {
      const held = existingLead(e)
      if (held) setExisting(held)
      else if (e instanceof ReaddDeclined) setError(e.message)
      else if (e instanceof Error && e.message.includes('source_url')) setError(t('Der Link muss eine Webadresse sein (https://…).'))
      else if (e instanceof Error && e.message.includes('profile_url'))
        setError(t('Kein LinkedIn- oder XING-Profil (…/in/… oder …/profile/…).'))
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
        {/* ELI-77: the name is read from the link itself — Eligo never opens
            LinkedIn or XING. */}
        <div className="sm:col-span-2">
          <TextInput
            label={t('LinkedIn-/XING-Profil')}
            value={form.profileUrl}
            onChange={pasteProfile}
            placeholder="https://www.linkedin.com/in/…"
          />
          {form.profileUrl.trim() && (
            <p className={`mt-1 text-[12px] ${profile ? 'text-cockpit-faint' : 'text-coral-400'}`}>
              {!profile
                ? t('Kein LinkedIn- oder XING-Profil (…/in/… oder …/profile/…).')
                : profile.name && form.fullName === profile.name
                  ? t('Name aus dem Link übernommen — bitte prüfen.')
                  : profile.name
                    ? t('Profil erkannt.')
                    : t('Aus dem Link lässt sich kein Name sicher lesen — bitte eintragen.')}
            </p>
          )}
        </div>
        <TextInput label={t('Job *')} value={form.jobTitle} onChange={(jobTitle) => set({ jobTitle })} placeholder={t('z. B. Senior Java Entwickler (m/w/d)')} />
        <TextInput
          label={t('Link zur Stellenanzeige')}
          value={form.sourceUrl}
          onChange={(sourceUrl) => {
            set({ sourceUrl })
            setAd(null)
          }}
          placeholder="https://"
        />
        <div className="space-y-2 sm:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void readAd({ url: form.sourceUrl })} disabled={reading || !form.sourceUrl.trim()}>
              {t('Aus Anzeige übernehmen')}
            </Button>
            <Button onClick={() => setPasting((v) => !v)} disabled={reading}>
              {t('Anzeigentext einfügen')}
            </Button>
            {ad?.found === 'corpus' && (
              <span className="text-[12px] text-mint-400">{t('Aus dem Markt übernommen — bitte prüfen.')}</span>
            )}
            {ad?.found === 'text' && (
              <span className="text-[12px] text-mint-400">{t('Aus dem Anzeigentext gelesen — bitte prüfen.')}</span>
            )}
            {ad?.is_agency && (
              <span className="text-[12px] text-gold-400">{t('Achtung: Die Anzeige stammt von einer Personalberatung.')}</span>
            )}
            {adError && <span className="text-[12px] text-coral-400">{adError}</span>}
          </div>
          {ad?.found === 'not_in_corpus' && (
            <p className="text-[13px] text-gold-400">{t('Diese Anzeige ist nicht im Markt – Text der Anzeige hier einfügen.')}</p>
          )}
          {pasting && (
            <div className="space-y-2">
              <textarea
                className={`${FIELD} min-h-[120px]`}
                value={adText}
                maxLength={8000}
                onChange={(e) => setAdText(e.target.value)}
                placeholder={t('Text der Stellenanzeige')}
                aria-label={t('Text der Stellenanzeige')}
              />
              <Button onClick={() => void readAd({ text: adText })} disabled={reading || !adText.trim()}>
                {t('Text auslesen')}
              </Button>
            </div>
          )}
          {ad?.contacts_withheld && (
            <p className="text-[12px] text-gold-400">
              {t('Personen aus der Anzeige können gerade nicht gegen Löschanträge geprüft werden — bitte selbst eintragen.')}
            </p>
          )}
          {ad && ad.found !== 'not_in_corpus' && ad.contacts.length === 0 && !ad.contacts_withheld && (
            <p className="text-[12px] text-cockpit-faint">{t('Die Anzeige nennt keine Person — bitte selbst eintragen.')}</p>
          )}
          {ad && ad.contacts.length > 1 && (
            <div className="flex flex-wrap items-center gap-2 text-[12px] text-cockpit-dim">
              {t('Die Anzeige nennt mehrere Personen:')}
              {ad.contacts.map((c, i) => (
                <Button key={`${c.full_name}-${i}`} tone={person === i ? 'primary' : 'ghost'} onClick={() => pickPerson(i)} title={c.quote ?? undefined}>
                  {c.full_name}
                </Button>
              ))}
            </div>
          )}
        </div>
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
              {existing.byProfile
                ? t('{name} ist mit diesem Profil schon gespeichert.', { name: existing.fullName })
                : existing.stage === 'bus_dev'
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
