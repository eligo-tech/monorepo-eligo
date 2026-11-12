// ELI-30: "Zentrale laut Impressum" — phone, VAT id, register, and the page
// they come from. Used on the Markt company card and the Unternehmen view.

import { t } from '@/i18n'
import { ExternalLink, Phone } from 'lucide-react'
import type { SwitchboardDTO } from '@/api/types'
import { registerLine, telHref } from './switchboard'

export function ImpressumBadge() {
  return (
    <span
      className="rounded border border-gold-600/50 px-1.5 text-[11px] text-gold-400"
      title={t('Die Nummer aus dem Impressum des Unternehmens: Sie erreichen die Zentrale, nicht eine Person direkt.')}
    >
      {t('Zentrale (Impressum)')}
    </span>
  )
}

export function SwitchboardLine({ board, compact = false }: { board: SwitchboardDTO; compact?: boolean }) {
  const register = registerLine(board)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[12px] text-cockpit-dim">
      {board.phone && (
        <a href={telHref(board.phone)} className="flex items-center gap-1 text-cockpit-text hover:text-mint-400">
          <Phone className="h-3.5 w-3.5 text-cockpit-faint" />
          {board.phone}
        </a>
      )}
      <ImpressumBadge />
      {!compact && board.vat_id && (
        <span>
          {t('USt-IdNr.')} {board.vat_id}
        </span>
      )}
      {!compact && register && <span>{register}</span>}
      {board.impressum_url && (
        <a
          href={board.impressum_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-cockpit-faint hover:text-mint-400"
        >
          <ExternalLink className="h-3 w-3" />
          {board.domain}
        </a>
      )}
    </div>
  )
}
