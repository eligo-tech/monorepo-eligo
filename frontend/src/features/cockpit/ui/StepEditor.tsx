// Editing one process step — the tracker's cell, as a form.
//
// What a recruiter does to a spreadsheet cell: put a date in it, colour it
// green when the client said yes, red when they said no, or write a word next
// to it ("vor Ort"). Those are the four fields, and nothing else.
//
// Times are Berlin's, always. The appointment was agreed in German local time,
// so the input shows and returns that wall clock whatever zone the viewer's
// laptop is in — a Munich interview must not read 09:30 in London.

import { locale } from '@/i18n/format'

import { t } from '@/i18n'

import { useRef, useState } from 'react'
import { Copy, Trash2, X } from 'lucide-react'
import { ApiError, api } from '@/api/client'
import { cn } from '@/lib/cn'
import { Panel } from './primitives'
import { Button, FIELD } from './forms'
import type { JobDTO } from '@/api/types'
import type { ProcessCard, ProcessStep } from '../data/types'

const TZ = 'Europe/Berlin'
/** How far the Berlin wall clock is from UTC at that instant (DST included). */
function berlinOffsetMs(at: Date): number {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat(locale(), {
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

// ── Placement: the question at the moment a role is filled (ELI-8) ──────────
//
// "wenn ein job mit einem Kandidaten besetzt wird, soll die Frage kommen ob
// dieser job nochmal erstellt werden soll."
//
// The mechanism has existed since ELI-7 — `POST /jobs/{id}/copy`, and a copy
// button on the Jobs list. What was missing is the moment. A recruiter who
// has just filled a role is not on the Jobs list, they are in this dialog,
// and a copy somebody has to remember to make later is a copy that does not
// get made. What it costs to forget is not tidiness: the next search then
// runs on the mandate that is already filled, and that mandate's Laufzeit,
// its ratios and its dates end up describing two searches at once.

/** The step that means "filled". Mirrors `derive_stage` in
 *  backend/app/domain/pipeline/service.py, which reads `vertrag` as PLACED. */
const PLACEMENT_STEP = 'vertrag'

/** Only the fields the placement question reads, so a `ProcessStep` off the
 *  card and a `ProcessStepDTO` off the wire can both be passed in — and so a
 *  test can state a case in one line. */
export interface StepFacts {
  key: string
  scheduledAt?: string | null
  doneAt?: string | null
  outcome?: string | null
}

/** Reached, counted the way the backend counts it: a booked date is a
 *  commitment, and so is a green cell. */
const isReached = (s: StepFacts): boolean =>
  !!(s.doneAt || s.scheduledAt || s.outcome === 'pass')

/** Do these steps say the mandate is filled?
 *
 *  A red cell anywhere ends the process — `derive_stage` returns REJECTED
 *  before it ever looks at `vertrag` — so a contract that fell through is not
 *  a placement. Asking "noch einmal anlegen?" there would be asking about a
 *  search that did not finish.
 */
export function isPlaced(steps: StepFacts[]): boolean {
  if (steps.some((s) => s.outcome === 'out')) return false
  return steps.some((s) => s.key === PLACEMENT_STEP && isReached(s))
}

/** Did THIS save fill the mandate?
 *
 *  The transition, not the state. Someone who reopens the Vertrag step to fix
 *  its date, or to add "Startdatum 01.03.", is not placing anybody a second
 *  time — and a dialog that asks again on every edit is one people learn to
 *  dismiss without reading, which is how the question stops working at all.
 */
export function placementJustHappened(before: StepFacts[], saved: StepFacts): boolean {
  if (isPlaced(before)) return false
  // A step nobody has touched yet has no row, so it may be missing from the
  // card entirely rather than present and empty.
  const after = before.some((s) => s.key === saved.key)
    ? before.map((s) => (s.key === saved.key ? saved : s))
    : [...before, saved]
  return isPlaced(after)
}

const OUTCOMES: {
  value: 'open' | 'pass' | 'out'
  label: string
  tone: string
}[] = [
  {
    value: 'open',
    label: t('offen'),
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
  // 'form' is the step editor; the other two are the ELI-8 question and its
  // answer, shown in the same dialog because that is where the recruiter
  // already is.
  const [phase, setPhase] = useState<'form' | 'ask' | 'copied'>('form')
  const [fresh, setFresh] = useState<JobDTO | null>(null)
  // What the card said BEFORE this dialog wrote anything. Snapshotted at
  // mount on purpose: `onSaved` refreshes the board behind the dialog, and a
  // `card` prop that already carried the save would make the transition
  // invisible and the question never fire.
  const [stepsBefore] = useState<StepFacts[]>(() => card.steps)

  const save = async () => {
    // A half-filled date input (a day but no time, say) reports an EMPTY value
    // in Chrome. Sending that would leave the field unchanged and close the
    // dialog, which reads exactly like "it did not save" — so ask first.
    if (terminRef.current?.validity.badInput) {
      setError(t('Termin unvollständig — bitte Datum und Uhrzeit angeben.'))
      return
    }
    const scheduledIso = scheduled ? fromBerlinInput(scheduled) : null
    if (scheduled && !scheduledIso) {
      setError(t('Termin nicht lesbar — bitte Datum und Uhrzeit angeben.'))
      return
    }
    const doneIso = doneOn ? fromBerlinInput(`${doneOn}T00:00`) : null
    if (doneOn && !doneIso) {
      setError(t('Datum „erledigt am“ nicht lesbar.'))
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
        setError(t('Der Termin wurde nicht übernommen — bitte erneut versuchen.'))
        setBusy(false)
        return
      }
      onSaved()
      // The one moment the product knows a role has just been filled.
      // Without a mandate behind the card there is nothing to copy — demo
      // cards and the coarse board join have no job row.
      if (
        card.jobId &&
        placementJustHappened(stepsBefore, {
          key: step.key,
          scheduledAt: saved.scheduled_at,
          doneAt: saved.done_at,
          outcome: saved.outcome,
        })
      ) {
        setBusy(false)
        setPhase('ask')
        return
      }
      onClose()
    } catch (e) {
      setError(
        e instanceof ApiError && (e.status === 401 || e.status === 403)
          ? t('Sitzung abgelaufen — bitte neu anmelden.')
          : e instanceof ApiError
            ? t('Konnte nicht gespeichert werden (HTTP {status}).', { status: e.status })
            : t('Konnte nicht gespeichert werden — keine Antwort vom Server.'),
      )
      setBusy(false)
    }
  }

  /** "Ja" — the same `POST /jobs/{id}/copy` the Jobs list calls, from the
   *  moment it is actually wanted. */
  const copyMandate = async () => {
    if (!card.jobId) return
    setBusy(true)
    setError(null)
    try {
      setFresh(await api.copyJob(card.jobId))
      setPhase('copied')
    } catch (e) {
      setError(
        e instanceof ApiError
          ? t('Das Mandat konnte nicht kopiert werden (HTTP {status}).', { status: e.status })
          : t('Das Mandat konnte nicht kopiert werden — keine Antwort vom Server.'),
      )
    } finally {
      setBusy(false)
    }
  }

  if (phase !== 'form') {
    return (
      <PlacementQuestion
        card={card}
        phase={phase}
        fresh={fresh}
        busy={busy}
        error={error}
        onCopy={() => void copyMandate()}
        onClose={onClose}
      />
    )
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
              aria-label={t('Schließen')}
              className="ml-auto text-cockpit-faint transition-colors hover:text-cockpit-text"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <label className="block space-y-1">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              {t('Termin (Ortszeit Deutschland)')}
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
                  aria-label={t('Termin entfernen')}
                  title={t('Termin entfernen')}
                  className="text-cockpit-faint transition-colors hover:text-coral-400"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          </label>

          <label className="block space-y-1">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              {t('Erledigt am')}
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
              {t('Ergebnis')}
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
                {t('Abgesagt beendet den Prozess — der Kandidat verschwindet aus den offenen Schritten.')}
              </p>
            )}
          </div>

          <label className="block space-y-1">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              {t('Notiz')}
            </span>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t('z. B. vor Ort')}
              className={cn(FIELD, 'w-full')}
            />
          </label>

          {error && <p className="text-[13px] text-coral-400">{error}</p>}

          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>{t('Abbrechen')}</Button>
            <Button tone='primary' onClick={save} disabled={busy}>
              {busy ? t('Speichert…') : t('Speichern')}
            </Button>
          </div>
        </Panel>
      </div>
    </div>
  )
}

/** The ELI-8 question, and what follows from answering it.
 *
 *  Its own dialog rather than a phase inside the editor's: once the role is
 *  filled, the step form has nothing left to say, and the recruiter is being
 *  asked about the mandate, not about the cell they just ticked.
 *
 *  Deliberately not `window.confirm`: the reason to say yes — the finished
 *  process stays where it is, the new search starts on its own numbers — is
 *  the whole argument, and it does not fit in a browser dialog.
 */
function PlacementQuestion({
  card,
  phase,
  fresh,
  busy,
  error,
  onCopy,
  onClose,
}: {
  card: ProcessCard
  phase: 'ask' | 'copied'
  fresh: JobDTO | null
  busy: boolean
  error: string | null
  onCopy: () => void
  onClose: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div className="w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <Panel className="space-y-4 p-5">
          <div className="flex items-start gap-3">
            <div>
              <h3 className="text-[16px] font-semibold text-cockpit-text">
                {t('Position besetzt')}
              </h3>
              <p className="mt-0.5 font-mono text-[12px] text-cockpit-faint">
                {card.candidateName} · {card.role}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('Schließen')}
              className="ml-auto text-cockpit-faint transition-colors hover:text-cockpit-text"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {phase === 'copied' && fresh ? (
            <>
              <p className="text-[14px] leading-relaxed text-cockpit-text">
                {t('Neues Mandat angelegt — gleiches Suchprofil, eigener Prozess.')}
              </p>
              <div className="flex justify-end gap-2">
                <Button onClick={onClose}>{t('Schließen')}</Button>
                <Button
                  tone="primary"
                  onClick={() => {
                    // The same spelling CockpitShell navigates with, so the
                    // copy opens in the per-mandate view instead of reloading.
                    window.location.hash = `cockpit/${fresh.id}`
                    onClose()
                  }}
                >
                  {t('Mandat öffnen')}
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="text-[14px] leading-relaxed text-cockpit-text">
                {t('Soll dieses Mandat noch einmal angelegt werden?')}
              </p>
              <p className="text-[13px] leading-relaxed text-cockpit-dim">
                {t('Die Kopie übernimmt Suchprofil, Kunde und Ansprechpartner und startet mit leerem Prozess. Der abgeschlossene Prozess bleibt an diesem Mandat — so beschreiben Laufzeit und Quoten weiterhin genau eine Suche.')}
              </p>

              {error && <p className="text-[13px] text-coral-400">{error}</p>}

              <div className="flex justify-end gap-2">
                <Button onClick={onClose}>{t('Nein')}</Button>
                <Button tone="primary" onClick={onCopy} disabled={busy}>
                  <Copy className="h-4 w-4" />
                  {busy ? t('Legt an…') : t('Ja, Mandat kopieren')}
                </Button>
              </div>
            </>
          )}
        </Panel>
      </div>
    </div>
  )
}
