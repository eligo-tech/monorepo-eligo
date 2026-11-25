// ELI-76: "+ Nummer" on the Leads row. A recruiter calling leads finds a
// number and saves it right there — no detour through the lead's page.
//
// It goes through the same `PATCH /managers/{id}` as "Kontaktdaten
// bearbeiten" (ELI-46/66): field by field through verification, with a
// receipt, the erasure list checked for the new number. That endpoint
// REPLACES the list, so the lead is read fresh first and every number it
// holds is sent back with the new one — a stale row never drops a number.

import { useState } from 'react'
import { Check, Plus, X } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { ManagerDTO, PhoneKind } from '@/api/types'
import { t } from '@/i18n'

import { ReaddDeclined, withReaddConfirm } from '../erasure/readd'
import { Button } from '../ui/forms'
import { PhoneNumberFields, appendPhone, phonesOf } from '../ui/phoneList'

type Added = { number: string; kind: PhoneKind | string }

interface Deps {
  read: (id: string) => Promise<ManagerDTO>
  update: typeof api.updateManager
}

/** Saves one more number on the lead. 'duplicate' when it already has it
 *  (nothing sent), 'empty' for a blank number. */
export async function saveAddedPhone(
  managerId: string,
  added: Added,
  deps: Deps = { read: api.manager, update: api.updateManager },
): Promise<'saved' | 'duplicate' | 'empty'> {
  if (!added.number.trim()) return 'empty'
  const lead = await deps.read(managerId)
  const phones = appendPhone(phonesOf(lead), added)
  if (!phones) return 'duplicate'
  await withReaddConfirm((override) =>
    deps.update(managerId, { phones, override_suppression: override || undefined }),
  )
  return 'saved'
}

/** The small inline form: type, number, Speichern / Abbrechen. */
export function AddPhoneForm({
  managerId,
  onSaved,
  onCancel,
}: {
  managerId: string
  onSaved: () => void
  onCancel: () => void
}) {
  const [kind, setKind] = useState<string>('mobile')
  const [number, setNumber] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await saveAddedPhone(managerId, { number, kind })
      if (result === 'saved') {
        onSaved()
        return
      }
      setError(result === 'duplicate' ? t('Diese Nummer ist beim Lead schon gespeichert.') : t('Bitte eine Nummer eingeben.'))
    } catch (e) {
      setError(
        e instanceof ReaddDeclined
          ? e.message
          : e instanceof ApiError && e.status === 422
            ? t('Bitte Eingaben prüfen.')
            : t('Nicht gespeichert — bitte erneut versuchen.'),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="mt-2 space-y-1.5"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <PhoneNumberFields kind={kind} number={number} onKind={setKind} onNumber={setNumber} autoFocus />
        <Button tone="primary" type="submit" disabled={busy || !number.trim()}>
          <Check className="h-4 w-4" /> {busy ? t('Speichert…') : t('Speichern')}
        </Button>
        <Button onClick={onCancel} disabled={busy}>
          <X className="h-4 w-4" /> {t('Abbrechen')}
        </Button>
      </div>
      {error && <p className="text-[12.5px] text-coral-400">{error}</p>}
    </form>
  )
}

/** The "+ Nummer" link next to the lead's number. */
export function AddPhoneButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      data-action="add-phone"
      onClick={onClick}
      title={t('Nummer direkt beim Lead speichern')}
      className="flex items-center gap-1 text-mint-400 transition-colors hover:text-mint-300"
    >
      <Plus className="h-3.5 w-3.5" />
      {t('Nummer')}
    </button>
  )
}
