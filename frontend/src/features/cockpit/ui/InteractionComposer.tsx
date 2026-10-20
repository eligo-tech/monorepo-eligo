// Writing an event down, where the events are read.
//
// The manager's activity bar named what exists on the record and offered no
// way to add to it: a call a recruiter made this morning could only reach the
// profile by being imported from the system the record came from. So the one
// note worth the most — the one written while the conversation is still in
// your head — had nowhere to go.
//
// The kinds live in one exported constant on purpose. The vocabulary is
// provisional: it is today's coarse enum (call · email · meeting · message ·
// note), and the recruiter's own list replaces it next. One constant means
// that is one edit, not a hunt through two screens.

import { useState } from 'react'
import { CalendarPlus } from 'lucide-react'

import { t } from '@/i18n'
import { Button } from './forms'

/** The kinds that can be filed by hand.
 *
 *  `briefing` and `feedback` are deliberately absent. Both belong to a
 *  mandate — one says what the client asked for, the other what they thought
 *  of a candidate — and both are written in the mandate's own panels, where
 *  the job is in scope. Offering them here would produce a briefing attached
 *  to nothing. */
export const INTERACTION_KINDS = ['call', 'meeting', 'email', 'message', 'note'] as const

export type InteractionKind = (typeof INTERACTION_KINDS)[number]

/** Today, as the date input wants it. */
const today = () => new Date().toISOString().slice(0, 10)

export function InteractionComposer({
  onSave,
  onCancel,
  defaultKind = 'call',
}: {
  /** Resolves when the row is written; rejects to show the error. */
  onSave: (entry: {
    interaction_type: InteractionKind
    summary: string
    occurred_at: string
  }) => Promise<unknown>
  onCancel: () => void
  defaultKind?: InteractionKind
}) {
  const [kind, setKind] = useState<InteractionKind>(defaultKind)
  const [text, setText] = useState('')
  const [when, setWhen] = useState(today())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Inside the component rather than at module scope: a label read once at
  // import time keeps the language the page started in.
  const label: Record<InteractionKind, string> = {
    call: t('Anruf'),
    meeting: t('Meeting'),
    email: t('E-Mail'),
    message: t('Nachricht'),
    note: t('Notiz'),
  }

  async function save() {
    const summary = text.trim()
    if (!summary || busy) return
    setBusy(true)
    setError(null)
    try {
      await onSave({
        interaction_type: kind,
        summary,
        // Midday, so a date typed without a time does not drift across a day
        // boundary when it is read back in another timezone.
        occurred_at: new Date(`${when}T12:00:00`).toISOString(),
      })
      setText('')
    } catch {
      setError(t('Nicht gespeichert — bitte erneut versuchen.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2 border-b border-cockpit-line bg-cockpit-inset px-6 py-4">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        autoFocus
        placeholder={t('Was besprochen wurde …')}
        className="w-full rounded-lg border border-cockpit-line bg-cockpit-surface px-3 py-2 text-[13.5px] leading-relaxed text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          {t('Art')}
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as InteractionKind)}
            className="rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
          >
            {INTERACTION_KINDS.map((value) => (
              <option key={value} value={value}>
                {label[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          {t('am')}
          <input
            type="date"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            className="rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
          />
        </label>
        <div className="ml-auto flex items-center gap-2">
          <Button tone="ghost" onClick={onCancel} disabled={busy}>
            {t('Abbrechen')}
          </Button>
          <Button tone="primary" onClick={() => void save()} disabled={busy || !text.trim()}>
            <CalendarPlus className="h-4 w-4" />
            {busy ? t('Speichert…') : t('Ereignis speichern')}
          </Button>
        </div>
      </div>
      {error && <p className="text-[12px] text-coral-400">{error}</p>}
    </div>
  )
}
