// Writing a Wiedervorlage by hand (ELI-44): a day, optionally a time, and
// what to do. Also the edit form — "verschieben" is the same three fields.

import { t } from '@/i18n'

import { useState } from 'react'
import { BellPlus } from 'lucide-react'

import { Button } from './forms'
import { shortTime } from './followUps'

const INPUT =
  'rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none'

export interface FollowUpFields {
  due_date: string
  due_time: string | null
  text: string
}

export function FollowUpForm({
  initial,
  defaultDate,
  onSave,
  onCancel,
}: {
  initial?: { due_date: string; due_time: string | null; text: string }
  /** `YYYY-MM-DD` for a new one — the caller knows the recruiter's today. */
  defaultDate: string
  /** Resolves when saved; rejects to show the error. */
  onSave: (fields: FollowUpFields) => Promise<unknown>
  onCancel: () => void
}) {
  const [day, setDay] = useState(initial?.due_date ?? defaultDate)
  const [at, setAt] = useState(shortTime(initial?.due_time ?? null) ?? '')
  const [text, setText] = useState(initial?.text ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ready = Boolean(day && text.trim()) && !busy

  async function save() {
    if (!ready) return
    setBusy(true)
    setError(null)
    try {
      await onSave({ due_date: day, due_time: at || null, text: text.trim() })
    } catch {
      setError(t('Nicht gespeichert — bitte erneut versuchen.'))
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-cockpit-line bg-cockpit-inset px-4 py-3">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={500}
        autoFocus
        placeholder={t('Was ist zu tun? z. B. „Bedarf für 2027 erfragen“')}
        className="w-full rounded-lg border border-cockpit-line bg-cockpit-surface px-3 py-2 text-[13.5px] text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none"
        onKeyDown={(e) => e.key === 'Enter' && void save()}
      />
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          {t('fällig am')}
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} className={INPUT} />
        </label>
        <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          {t('um (optional)')}
          <input type="time" value={at} onChange={(e) => setAt(e.target.value)} className={INPUT} />
        </label>
        <div className="ml-auto flex items-center gap-2">
          <Button tone="ghost" onClick={onCancel} disabled={busy}>
            {t('Abbrechen')}
          </Button>
          <Button tone="primary" onClick={() => void save()} disabled={!ready}>
            <BellPlus className="h-4 w-4" />
            {busy ? t('Speichert…') : t('Wiedervorlage speichern')}
          </Button>
        </div>
      </div>
      {error && <p className="text-[12px] text-coral-400">{error}</p>}
    </div>
  )
}
