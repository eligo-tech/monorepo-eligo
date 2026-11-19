// ELI-60: "Kein Interesse" — a lead called with that outcome leaves the Leads
// list, and the record stays: the chip with its date on the manager page,
// the company page and in Markt, and "Wieder als Lead aufnehmen" to undo it.
// A sales status — not the ELI-32 "Nicht mehr kontaktieren" mark.

import { useState } from 'react'
import { RotateCcw, ThumbsDown } from 'lucide-react'

import { api } from '@/api/client'
import type { ManagerDTO } from '@/api/types'
import { t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'

import { Button } from '../ui/forms'

/** The chip, for a card or a list row. */
export function NoInterestChip({ since }: { since: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-cockpit-edge px-2 py-0.5 font-mono text-[12px] leading-5 text-cockpit-dim"
      title={t('Beim Anruf kein Interesse — nicht mehr in den Leads. Anruf und Notizen bleiben gespeichert.')}
    >
      <ThumbsDown className="h-3 w-3" />
      {t('Kein Interesse (seit {date})', { date: fmtDate(since) })}
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
