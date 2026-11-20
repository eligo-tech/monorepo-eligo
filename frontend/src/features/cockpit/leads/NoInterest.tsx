// ELI-60: "Kein Interesse" — a lead called with that outcome leaves the Leads
// list, and the record stays: the chip with its date on the manager page,
// the company page and in Markt, and "Wieder als Lead aufnehmen" to undo it.
// A sales status — not the ELI-32 "Nicht mehr kontaktieren" mark.
//
// ELI-66: "Entfernen" hides a lead by hand on the same status, with a
// reason (Personalberatung · Nicht interessant · Sonstiges). Never a delete.

import { useState } from 'react'
import { EyeOff, RotateCcw, ThumbsDown } from 'lucide-react'

import { api } from '@/api/client'
import type { ManagerDTO, RemoveReason } from '@/api/types'
import { t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'

import { Button, FIELD } from '../ui/forms'

const REASONS: RemoveReason[] = ['agency', 'not_relevant', 'other']

export function removeReasonLabel(reason: RemoveReason): string {
  return reason === 'agency' ? t('Personalberatung') : reason === 'not_relevant' ? t('Nicht interessant') : t('Sonstiges')
}

/** The chip, for a card or a list row. With a reason: removed by hand. */
export function NoInterestChip({
  since,
  reason,
  note,
}: {
  since: string
  reason?: RemoveReason | null
  note?: string | null
}) {
  const when = fmtDate(since)
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-cockpit-edge px-2 py-0.5 font-mono text-[12px] leading-5 text-cockpit-dim"
      title={
        reason
          ? [t('Aus den Leads entfernt — nicht gelöscht. Anrufe und Notizen bleiben gespeichert.'), note].filter(Boolean).join(' · ')
          : t('Beim Anruf kein Interesse — nicht mehr in den Leads. Anruf und Notizen bleiben gespeichert.')
      }
    >
      {reason ? <EyeOff className="h-3 w-3" /> : <ThumbsDown className="h-3 w-3" />}
      {reason
        ? t('Entfernt: {reason} (seit {date})', { reason: removeReasonLabel(reason), date: when })
        : t('Kein Interesse (seit {date})', { date: when })}
    </span>
  )
}

/** "Wieder als Lead aufnehmen" — back on the Leads list. */
export function ReviveLeadButton({
  managerId,
  onRevived,
}: {
  managerId: string
  onRevived: (manager: ManagerDTO) => void
}) {
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const revive = async () => {
    setBusy(true)
    setFailed(false)
    try {
      onRevived(await api.reviveLead(managerId))
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <span className="inline-flex items-center gap-2">
      <Button onClick={revive} disabled={busy}>
        <RotateCcw className="h-4 w-4" />
        {t('Wieder als Lead aufnehmen')}
      </Button>
      {failed && <span className="text-[12px] text-coral-400">{t('Fehlgeschlagen — nichts geändert.')}</span>}
    </span>
  )
}

/** ELI-66 "Entfernen": asks why, then hides the lead. The record stays. */
export function RemoveLeadButton({
  managerId,
  onRemoved,
}: {
  managerId: string
  onRemoved: (manager: ManagerDTO) => void
}) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState<RemoveReason | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)} title={t('Aus den Leads entfernen — ausgeblendet, nicht gelöscht.')}>
        <EyeOff className="h-4 w-4" />
        {t('Entfernen')}
      </Button>
    )
  }

  const remove = async () => {
    if (!reason) return
    setBusy(true)
    setFailed(false)
    try {
      onRemoved(await api.removeLead(managerId, reason, reason === 'other' ? note.trim() : undefined))
      setOpen(false)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="flex basis-full flex-wrap items-center gap-2 rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 font-sans text-[13px] text-cockpit-dim">
      <span>{t('Warum entfernen?')}</span>
      {REASONS.map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={reason === r}
          onClick={() => setReason(r)}
          className={
            reason === r
              ? 'rounded-md border border-mint-500 px-2 py-0.5 font-mono text-[12px] text-mint-400'
              : 'rounded-md border border-cockpit-line px-2 py-0.5 font-mono text-[12px] text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text'
          }
        >
          {removeReasonLabel(r)}
        </button>
      ))}
      {reason === 'other' && (
        <input
          value={note}
          maxLength={500}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t('Grund (optional)')}
          aria-label={t('Grund (optional)')}
          className={`${FIELD} w-56`}
        />
      )}
      <Button tone="danger" onClick={remove} disabled={busy || !reason}>
        <EyeOff className="h-4 w-4" />
        {t('Entfernen')}
      </Button>
      <Button onClick={() => setOpen(false)} disabled={busy}>
        {t('Abbrechen')}
      </Button>
      {reason === 'agency' && (
        <span className="basis-full text-[12px] text-cockpit-faint">
          {t('Weitere Personalberatungen blendet Markt mit „Personalberatungen ausblenden“ aus.')}
        </span>
      )}
      {failed && <span className="text-[12px] text-coral-400">{t('Fehlgeschlagen — nichts geändert.')}</span>}
    </span>
  )
}
