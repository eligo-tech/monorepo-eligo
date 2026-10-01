// Editing one process step — the tracker's cell, as a form.
//
// What a recruiter does to a spreadsheet cell: put a date in it, colour it
// green when the client said yes, red when they said no, or write a word next
// to it ("vor Ort"). Those are the four fields, and nothing else.
//
// Times are Berlin's, always. The appointment was agreed in German local time,
// so the input shows and returns that wall clock whatever zone the viewer's
// laptop is in — a Munich interview must not read 09:30 in London.

import { useRef, useState } from 'react'
import { Trash2, X } from 'lucide-react'
import { ApiError, api } from '@/api/client'
import { cn } from '@/lib/cn'
import { Panel } from './primitives'
import { Button, FIELD } from './forms'
import type { ProcessCard, ProcessStep } from '../data/types'

const TZ = 'Europe/Berlin'
/** How far the Berlin wall clock is from UTC at that instant (DST included). */
function berlinOffsetMs(at: Date): number {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: TZ,
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
      .formatToParts(at)
      .map((p) => [p.type, p.value]),
  ) as Record<string, string>
  const asUtc = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour) % 24,
    Number(parts.minute),
    Number(parts.second),
  )
  return asUtc - at.getTime()
}

/** ISO instant → '2026-09-22T16:30' as shown on a Berlin wall clock. */
function toBerlinInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const at = new Date(iso)
  return new Date(at.getTime() + berlinOffsetMs(at)).toISOString().slice(0, 16)
}

/**
 * '2026-09-22T16:30' read as Berlin local → the ISO instant to store.
 *
 * Strict on purpose. `Date.parse` is not: it reads '02.10.2026, 14:00' — what
 * a browser without `datetime-local` support puts in a plain text field — as
 * the 10th of February, and a wrong date saved silently is the worst outcome
 * available here. Anything that is not exactly a local date-and-time returns
 * `null`, and the caller refuses to save rather than send nothing.
 */
const LOCAL_DATETIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2})?$/

function fromBerlinInput(value: string): string | null {
  const m = LOCAL_DATETIME.exec(value.trim())
  if (!m) return null
  const [, year, month, day, hour, minute] = m
  const asIfUtc = Date.UTC(+year, +month - 1, +day, +hour, +minute)
  // The offset depends on the date itself (summer vs winter time), so it is
  // read at roughly the right instant and then applied.
  const iso = new Date(asIfUtc - berlinOffsetMs(new Date(asIfUtc))).toISOString()
  // Round-trip check: a month of 13 satisfies the pattern and Date.UTC rolls
  // it into next year without complaint. If the instant does not render back
  // as the very string that was typed, it is not that moment.
  return toBerlinInput(iso) === value.trim().slice(0, 16) ? iso : null
}

const OUTCOMES: {
  value: 'open' | 'pass' | 'out'
  label: string
  tone: string
}[] = [
  {
    value: 'open',
    label: 'offen',
    tone: 'border-cockpit-line text-cockpit-dim',
  },
  {
    value: 'pass',
    label: 'positiv',
    tone: 'border-mint-600 bg-mint-800/40 text-mint-300',
  },
  {
    value: 'out',
    label: 'abgesagt',
    tone: 'border-coral-600 bg-coral-800/30 text-coral-300',
  },
]

export function StepEditor({
  card,
  step,
  onClose,
  onSaved,
}: {
  card: ProcessCard
  step: ProcessStep
  onClose: () => void
  onSaved: () => void
}) {
  const [scheduled, setScheduled] = useState(toBerlinInput(step.scheduledAt))
  const [doneOn, setDoneOn] = useState(toBerlinInput(step.doneAt).slice(0, 10))
  const [outcome, setOutcome] = useState(step.outcome ?? 'open')
  const [note, setNote] = useState(step.note ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const terminRef = useRef<HTMLInputElement>(null)

  const save = async () => {
    // A half-filled date input (a day but no time, say) reports an EMPTY value
    // in Chrome. Sending that would leave the field unchanged and close the
    // dialog, which reads exactly like "it did not save" — so ask first.
    if (terminRef.current?.validity.badInput) {
      setError('Termin unvollständig — bitte Datum und Uhrzeit angeben.')
      return
    }
    const scheduledIso = scheduled ? fromBerlinInput(scheduled) : null
    if (scheduled && !scheduledIso) {
      setError('Termin nicht lesbar — bitte Datum und Uhrzeit angeben.')
      return
    }
    const doneIso = doneOn ? fromBerlinInput(`${doneOn}T00:00`) : null
    if (doneOn && !doneIso) {
      setError('Datum „erledigt am" nicht lesbar.')
      return
    }

    setBusy(true)
    setError(null)
    // Anything the recruiter emptied is cleared explicitly — leaving a field
    // out means 'unchanged', so a cancelled appointment would otherwise stay.
    const clear: ('scheduled_at' | 'done_at' | 'note')[] = []
    if (!scheduled && step.scheduledAt) clear.push('scheduled_at')
    if (!doneOn && step.doneAt) clear.push('done_at')
    if (!note.trim() && step.note) clear.push('note')
    try {
      const saved = await api.setProcessStep(card.id, step.key, {
        scheduled_at: scheduledIso ?? undefined,
        done_at: doneIso ?? undefined,
        outcome,
        note: note.trim() || undefined,
        clear,
      })
      // Check the answer instead of assuming it. The endpoint returns the
      // stored row, so a write that quietly changed nothing is visible here
      // rather than to the recruiter a day later.
      // Compare the INSTANT, not the text: the server answers
      // '2026-10-05T07:15:00Z' where the client sent '…:00.000Z'.
      const sameMoment = (a: string | null, b: string | null) =>
        a === b || (!!a && !!b && new Date(a).getTime() === new Date(b).getTime())
      if (!sameMoment(saved.scheduled_at ?? null, scheduledIso ?? null)) {
        setError('Der Termin wurde nicht übernommen — bitte erneut versuchen.')
        setBusy(false)
        return
      }
      onSaved()
      onClose()
    } catch (e) {
      setError(
        e instanceof ApiError && (e.status === 401 || e.status === 403)
          ? 'Sitzung abgelaufen — bitte neu anmelden.'
          : e instanceof ApiError
            ? `Konnte nicht gespeichert werden (HTTP ${e.status}).`
            : 'Konnte nicht gespeichert werden — keine Antwort vom Server.',
      )
      setBusy(false)
    }
  }
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      {/* The backdrop closes the dialog; clicks inside must not reach it. */}
      <div className="w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <Panel className="space-y-4 p-5">
          <div className="flex items-start gap-3">
            <div>
              <h3 className="text-[16px] font-semibold text-cockpit-text">
                {step.label}
              </h3>
              <p className="mt-0.5 font-mono text-[12px] text-cockpit-faint">
                {card.candidateName} · {card.role}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Schließen"
              className="ml-auto text-cockpit-faint transition-colors hover:text-cockpit-text"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <label className="block space-y-1">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              Termin (Ortszeit Deutschland)
            </span>
            <div className="flex items-center gap-2">
              <input
                ref={terminRef}
                type="datetime-local"
                value={scheduled}
                onChange={(e) => setScheduled(e.target.value)}
                className={cn(FIELD, 'flex-1')}
              />
              {scheduled && (
                <button
                  type="button"
                  onClick={() => setScheduled('')}
                  aria-label="Termin entfernen"
                  title="Termin entfernen"
                  className="text-cockpit-faint transition-colors hover:text-coral-400"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          </label>

          <label className="block space-y-1">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              Erledigt am
            </span>
            <input
              type="date"
              value={doneOn}
              onChange={(e) => setDoneOn(e.target.value)}
              className={cn(FIELD, 'w-full')}
            />
          </label>

          <div className="space-y-1">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              Ergebnis
            </span>
            <div className="flex gap-2">
              {OUTCOMES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setOutcome(option.value)}
                  className={cn(
                    'rounded-lg border px-3 py-1.5 text-[13px] transition-colors',
                    outcome === option.value
                      ? option.tone
                      : 'border-cockpit-line text-cockpit-faint hover:text-cockpit-text',
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
            {outcome === 'out' && (
              <p className="text-[12px] leading-relaxed text-coral-400">
                Abgesagt beendet den Prozess — der Kandidat verschwindet aus den
                offenen Schritten.
              </p>
            )}
          </div>

          <label className="block space-y-1">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              Notiz
            </span>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="z. B. vor Ort"
              className={cn(FIELD, 'w-full')}
            />
          </label>

          {error && <p className="text-[13px] text-coral-400">{error}</p>}

          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Abbrechen</Button>
            <Button tone='primary' onClick={save} disabled={busy}>
              {busy ? 'Speichert…' : 'Speichern'}
            </Button>
          </div>
        </Panel>
      </div>
    </div>
  )
}
