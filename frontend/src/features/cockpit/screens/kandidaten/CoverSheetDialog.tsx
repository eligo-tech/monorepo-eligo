// "Kandidatenprofil als PDF" (ELI-20) — the cover sheet a client receives.
//
// The server decides what is on the page; this dialog only chooses the
// variant, the process (for the position) and the contact line, and shows
// what the preview says BEFORE anyone downloads: which sections are empty
// (left off the page, never invented), which files cannot be attached, and
// which parts of the workspace's CI are not set. Downloading is still allowed
// — a recruiter in a hurry decides, the dialog only makes sure they know.

import { useEffect, useState } from 'react'
import { AlertTriangle, Download, FileText, Loader2 } from 'lucide-react'

import { t } from '@/i18n'
import { ApiError, api } from '@/api/client'
import type { CoverSheetParams, CoverSheetPreviewDTO, CoverSheetVariant } from '@/api/types'
import { useSignedInContact } from '@/auth/signedInContact'
import { cn } from '@/lib/cn'
import { Button, CloseButton, Modal, SelectInput, TextInput } from '../../ui/forms'

export interface CoverSheetRun {
  applicationId: string
  title: string
}

const VARIANTS: { value: CoverSheetVariant; label: () => string; hint: () => string }[] = [
  { value: 'cover', label: () => t('Nur Deckblatt'), hint: () => t('Das Kandidatenprofil allein.') },
  { value: 'cover_cv', label: () => t('Deckblatt + CV'), hint: () => t('Dahinter der neueste CV.') },
  {
    value: 'cover_cv_references',
    label: () => t('Deckblatt + CV + Zeugnisse'),
    hint: () => t('Dahinter CV, alle Zeugnisse und Zertifikate.'),
  },
  {
    value: 'anonymous',
    label: () => t('Deckblatt anonym'),
    hint: () => t('Initialen statt Name, keine Anhänge.'),
  },
]

/** The page's German section labels → what this session reads. */
const SECTION: Record<string, () => string> = {
  'Angestrebte Position': () => t('Angestrebte Position'),
  Zusammenfassung: () => t('Zusammenfassung'),
  'Technologie Stack': () => t('Technologie Stack'),
  Gehaltsvorstellung: () => t('Gehaltsvorstellung'),
  Kündigungsfrist: () => t('Kündigungsfrist'),
  Qualifikationen: () => t('Qualifikationen'),
  Sprachkenntnisse: () => t('Sprachkenntnisse'),
  Wechselmotivation: () => t('Wechselmotivation'),
}

const BRANDING_PART: Record<string, () => string> = {
  logo: () => t('Logo'),
  company_line: () => t('Fußzeile mit Firmenadresse'),
  legal_text: () => t('AGB-Text'),
}

const REASON: Record<string, () => string> = {
  not_pdf: () => t('kein PDF'),
  unreadable: () => t('nicht lesbar'),
  encrypted: () => t('passwortgeschützt'),
}

export function CoverSheetDialog({
  candidateId,
  runs,
  defaultPosition,
  onClose,
}: {
  candidateId: string
  /** The processes this candidate runs in — the position comes from one. */
  runs: CoverSheetRun[]
  defaultPosition: string
  onClose: () => void
}) {
  const me = useSignedInContact()
  const [variant, setVariant] = useState<CoverSheetVariant>('cover')
  const [applicationId, setApplicationId] = useState(runs.length === 1 ? runs[0].applicationId : '')
  const [position, setPosition] = useState(defaultPosition)
  const [name, setName] = useState(me.name)
  const [email, setEmail] = useState(me.email)
  const [phone, setPhone] = useState('')
  const [preview, setPreview] = useState<CoverSheetPreviewDTO | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Escape closes this dialog only, not the drawer underneath: handled on
  // the window before the drawer's document listener sees it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  // The workspace's default number, until somebody types their own.
  useEffect(() => {
    api
      .branding()
      .then((b) => setPhone((p) => p || b.contact_phone || ''))
      .catch(() => undefined)
  }, [])

  const params: CoverSheetParams = {
    variant,
    application_id: applicationId || undefined,
    position: applicationId ? undefined : position,
    contact_name: name,
    contact_email: email,
    contact_phone: phone,
  }

  useEffect(() => {
    let alive = true
    const timer = setTimeout(() => {
      api
        .coverSheetPreview(candidateId, {
          variant,
          application_id: applicationId || undefined,
          position: applicationId ? undefined : position,
        })
        .then((p) => alive && setPreview(p))
        .catch(() => alive && setPreview(null))
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [candidateId, variant, applicationId, position])

  async function download() {
    setBusy(true)
    setError(null)
    try {
      const blob = await api.coverSheet(candidateId, params)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${preview?.title ?? 'Kandidatenprofil'}.pdf`
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch (e) {
      setError(
        e instanceof ApiError
          ? t('Fehlgeschlagen (HTTP {status}).', { status: String(e.status) })
          : t('Fehlgeschlagen — keine Antwort vom Server.'),
      )
    }
    setBusy(false)
  }

  const leftOut = preview?.attachments.filter((a) => !a.included) ?? []
  const attached = preview?.attachments.filter((a) => a.included) ?? []

  return (
    <Modal onClose={onClose} className="max-w-2xl">
      <div className="flex items-start justify-between gap-4 border-b border-cockpit-line px-6 py-4">
        <div>
          <h2 className="text-[19px] font-semibold tracking-tight text-cockpit-text">
            {t('Kandidatenprofil als PDF')}
          </h2>
          <p className="mt-0.5 text-[13px] text-cockpit-dim">
            {t('Im CI dieses Workspace, für den Kunden. Die Felder werden 1:1 übernommen.')}
          </p>
        </div>
        <CloseButton onClose={onClose} />
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
        <div className="grid gap-2 sm:grid-cols-2">
          {VARIANTS.map((v) => (
            <button
              key={v.value}
              type="button"
              onClick={() => setVariant(v.value)}
              className={cn(
                'rounded-xl border px-4 py-3 text-left transition-colors',
                variant === v.value
                  ? 'border-mint-600 bg-mint-800/30'
                  : 'border-cockpit-line hover:border-cockpit-edge',
              )}
            >
              <div className="text-[14px] font-medium text-cockpit-text">{v.label()}</div>
              <div className="mt-0.5 text-[12px] text-cockpit-dim">{v.hint()}</div>
            </button>
          ))}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          {runs.length > 0 && (
            <SelectInput
              label={t('Prozess')}
              value={applicationId}
              onChange={setApplicationId}
              options={[
                { value: '', label: t('Kein Prozess — Position frei eingeben') },
                ...runs.map((r) => ({ value: r.applicationId, label: r.title })),
              ]}
            />
          )}
          {!applicationId && (
            <TextInput label={t('Angestrebte Position')} value={position} onChange={setPosition} />
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <TextInput label={t('Kontakt: Name')} value={name} onChange={setName} />
          <TextInput label={t('Kontakt: E-Mail')} value={email} onChange={setEmail} type="email" />
          <TextInput label={t('Kontakt: Telefon')} value={phone} onChange={setPhone} />
        </div>

        {variant === 'anonymous' && (
          <p className="rounded-xl border border-gold-600/40 bg-gold-800/10 px-4 py-3 text-[13px] text-gold-300">
            {t('Name und aktueller Arbeitgeber werden im Text ersetzt. Frühere Arbeitgeber, Orte oder Projekte, die einen Rückschluss erlauben, bitte vor dem Versand prüfen — Freitexte werden sonst 1:1 übernommen.')}
          </p>
        )}

        {preview && (
          <div className="space-y-3 text-[13px]">
            {preview.missing.length > 0 && (
              <Notice>
                {t('Leer und daher nicht auf dem Blatt:')}{' '}
                {preview.missing.map((m) => SECTION[m]?.() ?? m).join(' · ')}
              </Notice>
            )}
            {leftOut.length > 0 && (
              <Notice>
                {t('Nicht angehängt:')}{' '}
                {leftOut
                  .map((a) => `${a.filename} (${a.reason ? (REASON[a.reason]?.() ?? a.reason) : ''})`)
                  .join(' · ')}
              </Notice>
            )}
            {preview.branding_missing.length > 0 && (
              <Notice>
                {t('Im CI dieses Workspace fehlt noch:')}{' '}
                {preview.branding_missing.map((b) => BRANDING_PART[b]?.() ?? b).join(' · ')}{' '}
                {t('— ein Administrator hinterlegt es unter Einstellungen.')}
              </Notice>
            )}
            {attached.length > 0 && (
              <ul className="space-y-1 font-mono text-[12px] text-cockpit-dim">
                {attached.map((a) => (
                  <li key={a.document_id} className="flex items-center gap-2">
                    <FileText className="h-3.5 w-3.5 text-mint-400" /> {a.filename}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <p className="text-[12px] leading-relaxed text-cockpit-faint">
          {t('Jeder Download wird im Prüfprotokoll (Receipts) vermerkt — welche Fassung, welcher Prozess, welche Dateien.')}
        </p>
        {error && <p className="text-[13px] text-coral-400">{error}</p>}
      </div>

      <div className="flex justify-end gap-2 border-t border-cockpit-line px-6 py-4">
        <Button onClick={onClose}>{t('Abbrechen')}</Button>
        <Button tone="primary" onClick={() => void download()} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          {t('PDF herunterladen')}
        </Button>
      </div>
    </Modal>
  )
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-xl border border-gold-600/40 bg-gold-800/10 px-4 py-2.5 text-gold-300">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{children}</span>
    </p>
  )
}
