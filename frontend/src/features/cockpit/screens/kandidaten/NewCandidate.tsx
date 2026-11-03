// "Kandidat anlegen" — a person written down, without a CV and without an
// import (ELI-17).
//
// Until now someone reached the record two ways: an ATS import, or dropping
// their CV in as a PDF. Neither covers the commonest way a recruiter meets
// somebody — a referral on the phone, a conversation at an event, a reply on
// LinkedIn with nothing attached, a CV promised for next week. `POST
// /candidates` has answered 201 the whole time and nothing in the frontend
// ever called it, which is the same hole "Neues Mandat" closed for jobs.
//
// Two decisions carried over from that form, and one that is this form's own:
//
//  1. **The name is the only required field.** A person is worth writing
//     down before you know their salary expectation, and a form that insists
//     on everything is a form filled in somewhere else — a notebook, usually,
//     and then never transcribed.
//
//  2. **A CV can arrive later.** This creates the record; uploading the
//     document afterwards enriches the same one rather than making a second.
//
//  3. **Herkunft is free text, not a dropdown.** `candidates.source` is
//     quoted VERBATIM into the Art. 14 notice the person receives —
//     `notices/service.py` builds "Wir haben Ihre Daten aus folgender Quelle
//     erhalten: {source}." So a machine code like `self_reported` would be
//     mailed to a human being, and a closed list cannot describe how people
//     actually meet. The quick picks below are suggestions; anything typed
//     is kept as written.

import { t } from '@/i18n'

import { useState } from 'react'
import { UserRoundPlus } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import { ReaddDeclined, withReaddConfirm } from '../../erasure/readd'
import { toAmount } from '@/lib/amount'
import {
  Button,
  CloseButton,
  FieldLabel,
  Modal,
  TagInput,
  TextInput,
} from '../../ui/forms'
import { Label } from '../../ui/primitives'



export function NewCandidate({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [currentTitle, setCurrentTitle] = useState('')
  const [currentCompany, setCurrentCompany] = useState('')
  const [location, setLocation] = useState('')
  const [skills, setSkills] = useState<string[]>([])
  const [salary, setSalary] = useState('')
  const [source, setSource] = useState('')
  /** Common origins, offered as one tap each.
   *
   *  The VALUE stays German in both languages and the LABEL is translated —
   *  the rule this codebase already applies to `WHO[].value` in
   *  `FeedbackPanel`. What gets stored is quoted into the Art. 14 notice, and
   *  that notice is written in German (`notices/templates.py`), so an English
   *  speaker who picks "Referral" must still put the word "Empfehlung" in
   *  front of the candidate. Translating the stored value would mail somebody
   *  a German letter with one English word wedged into it. */
  const ORIGINS: { value: string; label: string }[] = [
    { value: 'Empfehlung', label: t('Empfehlung') },
    { value: 'Veranstaltung', label: t('Veranstaltung') },
    { value: 'LinkedIn', label: 'LinkedIn' },
    { value: 'Xing', label: 'Xing' },
    { value: 'Eigenbewerbung', label: t('Eigenbewerbung') },
  ]

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    const name = fullName.trim()
    if (!name) {
      setError(t('Ohne Namen lässt sich niemand anlegen.'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      const created = await withReaddConfirm((override) => api.createCandidate({
        override_suppression: override || undefined,
        full_name: name,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        current_title: currentTitle.trim() || undefined,
        current_company: currentCompany.trim() || undefined,
        location: location.trim() || undefined,
        skills,
        salary_expectation: toAmount(salary),
        source: source.trim() || undefined,
      }))
      onCreated(created.id)
      onClose()
    } catch (e) {
      setError(
        e instanceof ReaddDeclined
          ? e.message
          : e instanceof ApiError && (e.status === 401 || e.status === 403)
          ? t('Sitzung abgelaufen — bitte neu anmelden.')
          : e instanceof ApiError
            ? t('Konnte nicht gespeichert werden (HTTP {status}).', { status: e.status })
            : t('Konnte nicht gespeichert werden — keine Antwort vom Server.'),
      )
      setBusy(false)
    }
  }

  return (
    <Modal onClose={onClose} className="max-w-2xl">
      <div className="flex items-center gap-3 border-b border-cockpit-line px-7 py-4">
        <Label>{t('Kandidat anlegen')}</Label>
        <span className="ml-auto">
          <CloseButton onClose={onClose} />
        </span>
      </div>

      <div className="space-y-5 overflow-y-auto px-7 py-6">
        <p className="text-[13px] leading-relaxed text-cockpit-dim">
          {t('Für jemanden, von dem es noch keinen Lebenslauf gibt. Nur der Name ist nötig — alles andere lässt sich später ergänzen, und ein hochgeladener CV reichert denselben Datensatz an.')}
        </p>

        <TextInput
          label={t('Name')}
          value={fullName}
          onChange={setFullName}
          placeholder="Marie Hoffmann"
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextInput label={t('E-Mail')} value={email} onChange={setEmail} type="email" />
          <TextInput label={t('Telefon')} value={phone} onChange={setPhone} />
          <TextInput
            label={t('Aktuelle Position')}
            value={currentTitle}
            onChange={setCurrentTitle}
            placeholder="Senior Backend Engineer"
          />
          <TextInput
            label={t('Aktueller Arbeitgeber')}
            value={currentCompany}
            onChange={setCurrentCompany}
          />
          <TextInput label={t('Ort')} value={location} onChange={setLocation} />
          <TextInput
            label={t('Gehaltsvorstellung')}
            value={salary}
            onChange={setSalary}
            placeholder="85.000"
          />
        </div>

        <div>
          <FieldLabel>{t('Skills')}</FieldLabel>
          <TagInput
            tags={skills}
            onChange={setSkills}
            placeholder={t('Skill eingeben und Enter drücken')}
          />
        </div>

        {/* The field that is not cosmetic. See the note at the top of this
            file: whatever is written here is mailed to the person. */}
        <div className="rounded-xl border border-cockpit-line bg-cockpit-inset p-4">
          <TextInput
            label={t('Woher stammen die Daten?')}
            value={source}
            onChange={setSource}
            placeholder={t('z. B. Empfehlung von Thomas Bausch')}
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {ORIGINS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                onClick={() => setSource(value)}
                className="rounded-full border border-dashed border-cockpit-edge px-2.5 py-1 text-[12px] text-cockpit-dim transition-colors hover:border-mint-600 hover:text-mint-300"
              >
                {label}
              </button>
            ))}
          </div>
          <p className="mt-2.5 text-[12px] leading-relaxed text-cockpit-faint">
            {t('Dieser Text steht später wörtlich in der Benachrichtigung an die Person („Wir haben Ihre Daten aus folgender Quelle erhalten: …“). Wer sich nicht selbst gemeldet hat, muss nach Art. 14 DSGVO informiert werden — ohne festgehaltene Herkunft lässt sich das hinterher nicht mehr beurteilen.')}
          </p>
        </div>

        {error && <p className="text-[13px] text-coral-400">{error}</p>}
      </div>

      <div className="flex items-center gap-2 border-t border-cockpit-line px-7 py-4">
        <Button tone="primary" onClick={() => void save()} disabled={busy || !fullName.trim()}>
          <UserRoundPlus className="h-4 w-4" />
          {busy ? t('Legt an…') : t('Kandidat anlegen')}
        </Button>
        <Button onClick={onClose}>{t('Abbrechen')}</Button>
        {!fullName.trim() && (
          <span className="ml-auto font-mono text-[12px] text-cockpit-faint">
            {t('Es fehlt noch der Name')}
          </span>
        )}
      </div>
    </Modal>
  )
}
