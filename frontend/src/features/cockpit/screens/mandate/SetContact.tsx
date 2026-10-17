// "Ansprechpartner festlegen" — on the mandate, where the question is asked.
//
// The row used to read "Kein Ansprechpartner hinterlegt — über „Projekte"
// anreichern", which sent the reader to a different screen that links a
// contact to a COMPANY and never to a mandate. `jobs.manager_id` had existed
// since the first migration and was in no schema, so there was no way to
// answer the question from anywhere.
//
// Either pick somebody already recorded at this client, or add one here. A
// new contact is a person, so it is written with `source` and `source_detail`
// — that provenance is what the Art. 14 flow reads later, and a contact whose
// origin was never recorded cannot be assessed for it at all.

import { t } from '@/i18n'

import { useState } from 'react'
import { Check, Plus, UserRound, X } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { ManagerDTO } from '@/api/types'
import { Button, TextInput } from '../../ui/forms'

export function SetContact({
  jobId,
  jobTitle,
  companyId,
  companyName,
  candidates,
  onDone,
}: {
  jobId: string
  jobTitle: string
  /** Null when the mandate has no client yet — then there is nowhere to
   *  attach a contact, and the backend would refuse it. */
  companyId?: string
  companyName: string
  /** Contacts already recorded at this client. */
  candidates: ManagerDTO[]
  onDone: () => void
}) {
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [role, setRole] = useState('')
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function attach(managerId: string) {
    setBusy(true)
    setError(null)
    try {
      await api.updateJob(jobId, { manager_id: managerId })
      onDone()
      setOpen(false)
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 422
          ? t('Dieser Kontakt gehört zu einer anderen Firma.')
          : t('Nicht gespeichert — bitte erneut versuchen.'),
      )
    }
    setBusy(false)
  }

  async function create() {
    if (!name.trim() || !companyId) return
    setBusy(true)
    setError(null)
    try {
      const manager = await api.createManager({
        company_id: companyId,
        full_name: name.trim(),
        role_title: role.trim() || null,
        email: email.trim() || null,
        source: 'self_reported',
        source_detail: t('Ansprechpartner für das Mandat „{title}” erfasst', { title: jobTitle }),
      })
      await api.updateJob(jobId, { manager_id: manager.id })
      onDone()
      setOpen(false)
      setAdding(false)
      setName('')
      setRole('')
      setEmail('')
    } catch {
      setError(t('Nicht gespeichert — bitte erneut versuchen.'))
    }
    setBusy(false)
  }

  if (!companyId) {
    return (
      <span className="font-mono text-[11.5px] text-cockpit-faint">
        {t('Erst einen Kunden am Mandat hinterlegen.')}
      </span>
    )
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="font-mono text-[12px] text-mint-300 underline-offset-2 transition-colors hover:underline"
      >
        {t('Ansprechpartner festlegen')}
      </button>
    )
  }

  return (
    <div className="mt-2 space-y-3 rounded-xl border border-cockpit-line bg-cockpit-inset/60 p-3">
      {!adding && (
        <>
          {candidates.length > 0 ? (
            <div className="space-y-1.5">
              <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-cockpit-faint">
                Kontakte bei {companyName}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {candidates.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    disabled={busy}
                    onClick={() => void attach(m.id)}
                    className="flex items-center gap-1.5 rounded-lg border border-cockpit-line px-2.5 py-1.5 text-[12.5px] text-cockpit-dim transition-colors hover:border-mint-600 hover:text-mint-300"
                  >
                    <UserRound className="h-3.5 w-3.5" />
                    {m.full_name}
                    {m.role_title && (
                      <span className="text-cockpit-faint">· {m.role_title}</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-[12.5px] text-cockpit-dim">
              Für {companyName} ist noch kein Kontakt erfasst.
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" /> Neuer Kontakt
            </Button>
            <Button onClick={() => setOpen(false)}>
              <X className="h-4 w-4" /> Abbrechen
            </Button>
          </div>
        </>
      )}

      {adding && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <TextInput label={t('Name')} value={name} onChange={setName} placeholder={t('Vor- und Nachname')} />
            <TextInput label={t('Rolle')} value={role} onChange={setRole} placeholder="Head of IT" />
            <TextInput label={t('E-Mail')} value={email} onChange={setEmail} placeholder={t('optional')} />
          </div>
          <div className="flex items-center gap-2">
            <Button tone="primary" onClick={() => void create()} disabled={busy || !name.trim()}>
              <Check className="h-4 w-4" /> {busy ? t('Speichert…') : t('Anlegen & zuordnen')}
            </Button>
            <Button onClick={() => setAdding(false)}>
              <X className="h-4 w-4" /> Zurück
            </Button>
          </div>
          <p className="font-mono text-[11px] text-cockpit-faint">
            {t('Wird mit Herkunft erfasst — Grundlage für die Art.-14-Information.')}
          </p>
        </>
      )}

      {error && <p className="text-[12.5px] text-coral-400">{error}</p>}
    </div>
  )
}
