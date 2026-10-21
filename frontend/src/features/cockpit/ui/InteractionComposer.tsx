// Writing an event down, where the events are read.
//
// The manager's activity bar named what exists on the record and offered no
// way to add to it: a call a recruiter made this morning could only reach the
// profile by being imported from the system the record came from. So the one
// note worth the most — the one written while the conversation is still in
// your head — had nowhere to go.
//
// The kinds are passed in rather than fixed here. They were a constant, with
// a note saying the recruiter's own list would replace it — ELI-9 is that
// list, and it turned out to be TWO lists: five kinds on a manager, three on
// a candidate. A composer that knew its own vocabulary could only ever serve
// one of them. Both live in `interactionKinds.ts`.

import { useState } from 'react'
import { CalendarPlus } from 'lucide-react'

import { t } from '@/i18n'
import { Button } from './forms'
import { interactionLabel } from './interactionKinds'

/** Today, as the date input wants it. */
const today = () => new Date().toISOString().slice(0, 10)

export function InteractionComposer({
  kinds,
  onSave,
  onCancel,
  defaultKind,
}: {
  /** The vocabulary for the thing being annotated — `MANAGER_INTERACTION_KINDS`
   *  or `CANDIDATE_INTERACTION_KINDS`. Neither is a subset of the other:
   *  `business_call` is meaningless on a candidate and `candidate_call` on a
   *  manager, so one shared list would offer each half the wrong options. */
  kinds: readonly string[]
  /** Resolves when the row is written; rejects to show the error. */
  onSave: (entry: {
    interaction_type: string
    summary: string
    occurred_at: string
  }) => Promise<unknown>
  onCancel: () => void
  defaultKind?: string
}) {
  const [kind, setKind] = useState<string>(defaultKind ?? kinds[0])
  const [text, setText] = useState('')
  const [when, setWhen] = useState(today())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
            onChange={(e) => setKind(e.target.value)}
            className="rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
          >
            {kinds.map((value) => (
              <option key={value} value={value}>
                {interactionLabel(value)}
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
