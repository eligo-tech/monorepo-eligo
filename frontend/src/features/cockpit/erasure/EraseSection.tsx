// "Personenbezogene Daten löschen" — the bottom of a candidate's or a
// contact's page. Admins only: it removes CVs, processes and notes for the
// whole workspace and cannot be undone. The button is a courtesy; the server's
// admin check is the control.

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ShieldAlert, Trash2 } from 'lucide-react'

import { api } from '@/api/client'
import type { ErasureRequestDTO } from '@/api/types'
import { t } from '@/i18n'

import { DateField } from '../ui/DateField'
import { isAdmin, useMe } from '../useMe'
import { confirmationNote, describeEraseError, namesMatch, summary, todayIso, unprotected } from './erasureView'

const NOTE_TONE = {
  mint: 'text-mint-400',
  gold: 'rounded-md border border-gold-600 bg-gold-800 px-3 py-2 text-gold-300',
  coral: 'text-coral-300',
} as const

type Subject = 'candidate' | 'manager'

export function EraseSection({
  subject,
  id,
  name,
  email,
  onErased,
  open: openProp,
  onOpenChange,
}: {
  subject: Subject
  id: string
  name: string
  /** ELI-32: where the confirmation can go — read now, before it is erased. */
  email?: string | null
  /** The record is gone: close the page, reload the list. */
  onErased: () => void
  /** ELI-32: controlled by the page when the note composer opens the dialog
   *  ("Löschen (DSGVO)"); otherwise the section's own button does. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const me = useMe()
  const [ownOpen, setOwnOpen] = useState(false)
  const open = openProp ?? ownOpen
  const setOpen = onOpenChange ?? setOwnOpen
  if (!isAdmin(me)) return null
  return (
    <section className="mt-10 border-t border-cockpit-line pt-5">
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
        {t('Datenschutz')}
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-prose text-[13px] text-cockpit-dim">
          {subject === 'candidate'
            ? t('Verlangt diese Person die Löschung ihrer Daten (DSGVO Art. 17) oder widerspricht sie der Verarbeitung (Art. 21), lösche sie hier vollständig aus diesem Workspace.')
            : t('Verlangt dieser Kontakt die Löschung seiner Daten (DSGVO Art. 17) oder widerspricht er der Verarbeitung (Art. 21), lösche ihn hier. Seine Mandate bleiben beim Kunden.')}
        </p>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 rounded-md border border-coral-600 px-3 py-1.5 text-[13px] text-coral-300 hover:bg-coral-800"
        >
          <Trash2 className="h-4 w-4" />
          {t('Person löschen')}
        </button>
      </div>
      {open && (
        <EraseDialog
          subject={subject}
          id={id}
          name={name}
          email={email}
          onClose={() => setOpen(false)}
          onErased={onErased}
        />
      )}
    </section>
  )
}

function EraseDialog({
  subject,
  id,
  name,
  email,
  onClose,
  onErased,
}: {
  subject: Subject
  id: string
  name: string
  email?: string | null
  onClose: () => void
  onErased: () => void
}) {
  // ELI-32: the confirmation is offered only where it can go — an address,
  // and a server that can send. Off until ticked; never automatic.
  const [confirm, setConfirm] = useState(false)
  const [canMail, setCanMail] = useState<boolean | null>(null)
  useEffect(() => {
    if (!email) return
    let alive = true
    api
      .noticeCapability()
      .then((c) => alive && setCanMail(c.configured))
      .catch(() => alive && setCanMail(false))
    return () => {
      alive = false
    }
  }, [email])
  const [typed, setTyped] = useState('')
  const [reason, setReason] = useState<'erasure' | 'objection'>('erasure')
  const [requestedOn, setRequestedOn] = useState(todayIso())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<ErasureRequestDTO | null>(null)

  const finish = () => (done ? onErased() : onClose())

  useEffect(() => {
    // Capture phase, and stopped: Escape must not also close the drawer
    // underneath — mid-request that would unmount this dialog and the list
    // would keep showing a person who is already erased.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      e.stopPropagation()
      if (!busy) finish()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  })

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const body = { confirm_name: typed, reason, requested_on: requestedOn, send_confirmation: confirm && !!email }
      setDone(subject === 'candidate' ? await api.eraseCandidate(id, body) : await api.eraseManager(id, body))
    } catch (e) {
      setError(describeEraseError(e))
    } finally {
      setBusy(false)
    }
  }

  const ready = namesMatch(typed, name) && !!requestedOn && !busy

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 px-4" onClick={() => !busy && finish()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="erase-title"
        className="w-full max-w-lg rounded-lg border border-coral-600 bg-cockpit-bg p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <p id="erase-title" className="flex items-center gap-2 text-[15px] text-coral-300">
          <ShieldAlert className="h-5 w-5" />
          {done ? t('Gelöscht') : t('{name} endgültig löschen', { name })}
        </p>

        {done ? (
          <div className="mt-3 space-y-3 text-[13.5px] text-cockpit-dim">
            <p>{summary(done.counts)}</p>
            {unprotected(done.counts) ? (
              <p role="alert" className="rounded-md border border-gold-600 bg-gold-800 px-3 py-2 text-gold-300">
                {t('Achtung: Es gab weder eine E-Mail-Adresse noch eine Import-ID. Nichts verhindert, dass diese Person erneut importiert oder angelegt wird — prüfe das ATS des Kunden.')}
              </p>
            ) : (
              <p>{t('Der nächste Import legt diese Person nicht wieder an.')}</p>
            )}
            <p className="text-[12.5px] text-cockpit-faint">
              {t('Im ATS des Kunden, in heruntergeladenen Exporten und in Sicherungen ist die Person damit nicht gelöscht.')}
            </p>
            {(() => {
              const note = confirmationNote(done.confirmation)
              return note ? (
                <p role="status" className={NOTE_TONE[note.tone]}>
                  {note.text}
                </p>
              ) : null
            })()}
            <div className="flex justify-end">
              <button
                type="button"
                autoFocus
                onClick={onErased}
                className="rounded-md border border-cockpit-line px-3 py-1.5 text-[13px] text-cockpit-text hover:bg-cockpit-surface"
              >
                {t('Schließen')}
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-3 space-y-4 text-[13.5px] text-cockpit-dim">
            <p>
              {subject === 'candidate'
                ? t('Gelöscht werden der Datensatz, Lebensläufe und Dateien, Prozesse, Bewertungen, Notizen, Interviews und KI-Vorschläge. Einträge im Änderungsverlauf werden geschwärzt. Das lässt sich nicht rückgängig machen.')
                : t('Gelöscht werden der Kontakt, seine Notizen und KI-Vorschläge; seine Mandate bleiben ohne Ansprechpartner. Einträge im Änderungsverlauf werden geschwärzt. Das lässt sich nicht rückgängig machen.')}
            </p>
            <label className="block">
              <span className="text-[12px] text-cockpit-faint">{t('Anlass')}</span>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value as 'erasure' | 'objection')}
                className="mt-1 w-full rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1.5 text-cockpit-text"
              >
                <option value="erasure">{t('Löschung verlangt (Art. 17)')}</option>
                <option value="objection">{t('Widerspruch gegen die Verarbeitung (Art. 21)')}</option>
              </select>
            </label>
            <label className="block">
              <span className="text-[12px] text-cockpit-faint">{t('Verlangt am')}</span>
              <DateField
                value={requestedOn}
                max={todayIso()}
                onChange={setRequestedOn}
                className="mt-1 w-full rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1.5 text-cockpit-text"
              />
            </label>
            <label className="block">
              <span className="text-[12px] text-cockpit-faint">
                {t('Zur Bestätigung den Namen eintippen: {name}', { name })}
              </span>
              <input
                value={typed}
                autoFocus
                onChange={(e) => setTyped(e.target.value)}
                className="mt-1 w-full rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1.5 text-cockpit-text"
              />
            </label>
            {email && canMail === true && (
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={confirm}
                  onChange={(e) => setConfirm(e.target.checked)}
                  className="mt-1"
                />
                <span>{t('Bestätigung an {email} senden', { email })}</span>
              </label>
            )}
            {email && canMail === false && (
              <p className="text-[12.5px] text-cockpit-faint">
                {t('Eine Bestätigung per E-Mail ist nicht möglich: E-Mail-Versand ist auf diesem Server nicht eingerichtet.')}
              </p>
            )}
            {error && (
              <p role="alert" className="text-coral-300">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={busy}
                className="rounded-md border border-cockpit-line px-3 py-1.5 text-[13px] text-cockpit-text hover:bg-cockpit-surface"
              >
                {t('Abbrechen')}
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={!ready}
                className="rounded-md border border-coral-600 bg-coral-800 px-3 py-1.5 text-[13px] text-coral-300 enabled:hover:bg-coral-600/40 disabled:opacity-40"
              >
                {busy ? t('Lösche …') : t('Endgültig löschen')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
