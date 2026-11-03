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

import { isAdmin, useMe } from '../useMe'
import { describeEraseError, namesMatch, summary, todayIso, unprotected } from './erasureView'

type Subject = 'candidate' | 'manager'

export function EraseSection({
  subject,
  id,
  name,
  onErased,
}: {
  subject: Subject
  id: string
  name: string
  /** The record is gone: close the page, reload the list. */
  onErased: () => void
}) {
  const me = useMe()
  const [open, setOpen] = useState(false)
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
        <EraseDialog subject={subject} id={id} name={name} onClose={() => setOpen(false)} onErased={onErased} />
      )}
    </section>
  )
}

function EraseDialog({
  subject,
  id,
  name,
  onClose,
  onErased,
}: {
  subject: Subject
  id: string
  name: string
  onClose: () => void
  onErased: () => void
}) {
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
      const body = { confirm_name: typed, reason, requested_on: requestedOn }
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
              <input
                type="date"
                value={requestedOn}
                max={todayIso()}
                onChange={(e) => setRequestedOn(e.target.value)}
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
