// "Wiedervorlage am 01.02.2027 anlegen?" (ELI-44) — the offer shown after a
// note is saved, when its text names a date ("Anfang Februar wieder melden").
//
// The dates come from the backend's deterministic reader
// (`followups/dates.py`). This only OFFERS: nothing is created until the
// recruiter clicks — an agent proposes, a person decides.

import { t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'

import { BellPlus, X } from 'lucide-react'

import type { FollowUpSuggestionDTO } from '@/api/types'
import { Button } from './forms'
import { parseLocalDate } from './followUps'

export function FollowUpOffer({
  suggestions,
  onConfirm,
  onDismiss,
  busy,
  error,
}: {
  suggestions: readonly FollowUpSuggestionDTO[]
  onConfirm: (s: FollowUpSuggestionDTO) => void
  onDismiss: () => void
  busy?: boolean
  error?: string | null
}) {
  if (suggestions.length === 0) return null
  const [best, ...others] = suggestions
  const day = (s: FollowUpSuggestionDTO) => fmtDate(parseLocalDate(s.due_date))
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gold-600/60 bg-gold-800/20 px-4 py-3">
      <BellPlus className="h-4 w-4 shrink-0 text-gold-400" />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] text-cockpit-text">
          {t('Wiedervorlage am {date} anlegen?', { date: day(best) })}
        </p>
        <p className="font-mono text-[11px] text-cockpit-faint">
          {t('aus der Notiz: „{phrase}“', { phrase: best.phrase })}
        </p>
      </div>
      <Button tone="primary" onClick={() => onConfirm(best)} disabled={busy}>
        <BellPlus className="h-4 w-4" />
        {t('Anlegen')}
      </Button>
      {others.map((s) => (
        <button
          key={s.due_date}
          type="button"
          onClick={() => onConfirm(s)}
          disabled={busy}
          title={t('aus der Notiz: „{phrase}“', { phrase: s.phrase })}
          className="rounded-md border border-cockpit-line px-2 py-1 font-mono text-[12px] text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text disabled:opacity-40"
        >
          {day(s)} · {s.phrase}
        </button>
      ))}
      <button
        type="button"
        onClick={onDismiss}
        disabled={busy}
        className="flex items-center gap-1 font-mono text-[12px] text-cockpit-faint hover:text-cockpit-text"
      >
        <X className="h-3.5 w-3.5" />
        {t('Verwerfen')}
      </button>
      {error && <p className="w-full text-[12px] text-coral-400">{error}</p>}
    </div>
  )
}
