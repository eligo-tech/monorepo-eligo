// The offer shown after a call is logged or a note is saved (ELI-44, ELI-48).
//
// When the note names a date ("Anfang Februar wieder melden"):
// "Wiedervorlage am 01.02.2027 anlegen?" for one click, or "Anderes Datum…".
// When it names none ("hey, grad gesprochen"): "Wiedervorlage erstellen?" —
// the form opens with a week out and the note as the to-do, both editable.
//
// The dates come from the backend's deterministic reader
// (`followups/dates.py`). This only OFFERS: nothing is created until the
// recruiter clicks — an agent proposes, a person decides.

import { t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'

import { useState } from 'react'
import { BellPlus, X } from 'lucide-react'

import type { FollowUpSuggestionDTO } from '@/api/types'
import { Button } from './forms'
import { FollowUpForm, type FollowUpFields } from './FollowUpForm'
import { parseLocalDate } from './followUps'

export function FollowUpOffer({
  suggestions,
  fallbackDate,
  noteText,
  onConfirm,
  onSave,
  onDismiss,
  busy,
  error,
}: {
  suggestions: readonly FollowUpSuggestionDTO[]
  /** `YYYY-MM-DD` the form opens with when the note names no date. */
  fallbackDate: string
  /** The to-do the form opens with: the note, shortened. */
  noteText: string
  onConfirm: (s: FollowUpSuggestionDTO) => void
  /** Saves what the person wrote in the form; rejects to show the error. */
  onSave: (fields: FollowUpFields) => Promise<unknown>
  onDismiss: () => void
  busy?: boolean
  error?: string | null
}) {
  const [editing, setEditing] = useState<string | null>(null)
  const day = (iso: string) => fmtDate(parseLocalDate(iso))

  if (editing !== null) {
    return (
      <FollowUpForm
        initial={{ due_date: editing, due_time: null, text: noteText }}
        defaultDate={editing}
        onSave={onSave}
        onCancel={() => setEditing(null)}
      />
    )
  }

  const [best, ...others] = suggestions
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gold-600/60 bg-gold-800/20 px-4 py-3">
      <BellPlus className="h-4 w-4 shrink-0 text-gold-400" />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] text-cockpit-text">
          {best ? t('Wiedervorlage am {date} anlegen?', { date: day(best.due_date) }) : t('Wiedervorlage erstellen?')}
        </p>
        <p className="font-mono text-[11px] text-cockpit-faint">
          {best
            ? t('aus der Notiz: „{phrase}“', { phrase: best.phrase })
            : t('Kein Datum in der Notiz — Vorschlag: {date}', { date: day(fallbackDate) })}
        </p>
      </div>
      {best ? (
        <Button tone="primary" onClick={() => onConfirm(best)} disabled={busy}>
          <BellPlus className="h-4 w-4" />
          {t('Anlegen')}
        </Button>
      ) : (
        <Button tone="primary" onClick={() => setEditing(fallbackDate)} disabled={busy}>
          <BellPlus className="h-4 w-4" />
          {t('Wiedervorlage erstellen')}
        </Button>
      )}
      {others.map((s) => (
        <button
          key={s.due_date}
          type="button"
          onClick={() => onConfirm(s)}
          disabled={busy}
          title={t('aus der Notiz: „{phrase}“', { phrase: s.phrase })}
          className="rounded-md border border-cockpit-line px-2 py-1 font-mono text-[12px] text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text disabled:opacity-40"
        >
          {day(s.due_date)} · {s.phrase}
        </button>
      ))}
      {best && (
        <button
          type="button"
          onClick={() => setEditing(best.due_date)}
          disabled={busy}
          className="font-mono text-[12px] text-cockpit-dim hover:text-cockpit-text disabled:opacity-40"
        >
          {t('Anderes Datum…')}
        </button>
      )}
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
