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
//
// ELI-40: choosing an appointment kind ("Meeting Notes") makes the note a
// Termin — the date gets a time next to it, and the saved row shows up in the
// manager's Termine tab. Same row, same endpoint: the calendar is a view of
// the notes, not a second copy of them. Every other kind saves as before.
//
// ELI-32: a page may pass `privacy`, which adds a "Datenschutz" choice —
// "Nicht mehr kontaktieren" saves the note with the mark (one request, one
// transaction, one receipt), "Löschen (DSGVO)" saves nothing and opens the
// page's erase dialog instead: a note about to be erased is pointless.
//
// ELI-61: "Anonyme Profile gesendet" brings its Wiedervorlage with it — a
// to-do ("Feedback zu anonymen Profilen") due in three working days, both
// editable here before saving. The page files it through the ordinary
// follow-up endpoint once the note is written.

import { useState } from 'react'
import { BellPlus, CalendarPlus, ShieldAlert } from 'lucide-react'

import { cn } from '@/lib/cn'

import { t } from '@/i18n'
import { Button } from './forms'
import { DateField } from './DateField'
import { berlinIsoDate } from './datePicker'
import { addWorkingDays } from './followUps'
import { interactionLabel } from './interactionKinds'
import { isAppointmentKind, nextFullHour, occurredAt } from './appointments'

/** Today in Germany, as the date input wants it — not `toISOString()`,
 *  which is UTC and filed a note written at 00:30 under yesterday (ELI-53). */
export const composerToday = (now: Date = new Date()) => berlinIsoDate(now)

/** ELI-32: the Datenschutz outcome of a note — none, the mark, or erasure. */
export type PrivacyAction = '' | 'do_not_contact' | 'erase'

/** Stored when "Nicht mehr kontaktieren" is saved without words. Data, not
 *  copy: it is the note's text and stays German in both languages. */
export const DO_NOT_CONTACT_SUMMARY = 'Möchte nicht mehr kontaktiert werden.'

export interface ComposedEntry {
  interaction_type: string
  summary: string
  occurred_at: string
  do_not_contact?: boolean
}

/** What the composer hands to `onSave`. The time counts only for a Termin;
 *  any other kind keeps the date-only, midday-pinned behaviour. */
export function composeEntry(
  kind: string,
  text: string,
  date: string,
  time: string,
  privacy: PrivacyAction = '',
): ComposedEntry {
  const entry: ComposedEntry = {
    interaction_type: kind,
    summary: text.trim(),
    occurred_at: occurredAt(date, isAppointmentKind(kind) ? time : null),
  }
  if (privacy === 'do_not_contact') {
    entry.do_not_contact = true
    if (!entry.summary) entry.summary = DO_NOT_CONTACT_SUMMARY
  }
  return entry
}

/** ELI-61: the kind that files a Wiedervorlage for the client's feedback. */
export const PROFILES_SENT = 'profiles_sent'

/** The Wiedervorlage a profiles-sent note brings along. */
export interface NoteFollowUp {
  due_date: string
  text: string
}

/** ELI-61: its defaults — three working days from today in Germany. */
export function profilesFollowUp(now: Date = new Date()): NoteFollowUp {
  return { due_date: addWorkingDays(berlinIsoDate(now), 3), text: t('Feedback zu anonymen Profilen') }
}

/** An ordinary note needs words; the two privacy outcomes do not, and
 *  neither does "Anonyme Profile gesendet" — but its Wiedervorlage needs a
 *  day and a to-do. */
export function canSaveNote(
  text: string,
  privacy: PrivacyAction,
  kind?: string,
  followUp?: NoteFollowUp | null,
): boolean {
  if (privacy !== '') return true
  if (kind === PROFILES_SENT) return Boolean(followUp?.due_date && followUp.text.trim())
  return text.trim() !== ''
}

export function InteractionComposer({
  kinds,
  onSave,
  onCancel,
  defaultKind,
  privacy,
}: {
  /** The vocabulary for the thing being annotated — `MANAGER_INTERACTION_KINDS`
   *  or `CANDIDATE_INTERACTION_KINDS`. Neither is a subset of the other:
   *  `business_call` is meaningless on a candidate and `candidate_call` on a
   *  manager, so one shared list would offer each half the wrong options. */
  kinds: readonly string[]
  /** Resolves when the row is written; rejects to show the error. The
   *  second argument is the Wiedervorlage to file with it (ELI-61), if any. */
  onSave: (entry: ComposedEntry, followUp?: NoteFollowUp | null) => Promise<unknown>
  onCancel: () => void
  defaultKind?: string
  /** ELI-32: offer the Datenschutz outcomes. `onErase` opens the page's
   *  erase dialog; `canErase` is false for non-admins, who are told so. */
  privacy?: { onErase: () => void; canErase: boolean }
}) {
  const [kind, setKind] = useState<string>(defaultKind ?? kinds[0])
  const [text, setText] = useState('')
  const [when, setWhen] = useState(composerToday())
  const [at, setAt] = useState(nextFullHour())
  const appointment = isAppointmentKind(kind)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [action, setAction] = useState<PrivacyAction>('')
  const erase = action === 'erase'
  const [followUp, setFollowUp] = useState<NoteFollowUp>(() => profilesFollowUp())
  const sendsProfiles = kind === PROFILES_SENT
  // Nobody is to be asked for feedback who asked not to be contacted.
  const filedFollowUp = sendsProfiles && action === '' ? { ...followUp, text: followUp.text.trim() } : null
  const ready = canSaveNote(text, action, kind, sendsProfiles && action === '' ? followUp : null)

  async function save() {
    if (!ready || busy) return
    if (erase) {
      if (privacy?.canErase) privacy.onErase()
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onSave(composeEntry(kind, text, when, at, action), filedFollowUp)
      setText('')
      setFollowUp(profilesFollowUp())
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
            onChange={(e) => {
              setKind(e.target.value)
              // A fresh default each time, not one computed when the composer
              // opened (it may have stayed open past midnight).
              if (e.target.value === PROFILES_SENT) setFollowUp(profilesFollowUp())
            }}
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
          <DateField
            value={when}
            onChange={setWhen}
            className="rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
          />
        </label>
        {appointment && (
          <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
            {t('um')}
            <input
              type="time"
              value={at}
              onChange={(e) => setAt(e.target.value)}
              className="rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
            />
          </label>
        )}
        {appointment && (
          <span className="font-mono text-[11px] text-mint-400">
            {t('→ wird unter Termine eingetragen')}
          </span>
        )}
        {privacy && (
          <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
            {t('Datenschutz')}
            <select
              value={action}
              onChange={(e) => setAction(e.target.value as PrivacyAction)}
              className={cn(
                'rounded-md border bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal focus:outline-none',
                action ? 'border-coral-600 text-coral-300' : 'border-cockpit-line text-cockpit-text focus:border-cockpit-edge',
              )}
            >
              <option value="">—</option>
              <option value="do_not_contact">{t('Nicht mehr kontaktieren')}</option>
              <option value="erase">{t('Löschen (DSGVO)')}</option>
            </select>
          </label>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button tone="ghost" onClick={onCancel} disabled={busy}>
            {t('Abbrechen')}
          </Button>
          {erase ? (
            <Button tone="primary" onClick={() => void save()} disabled={!privacy?.canErase}>
              <ShieldAlert className="h-4 w-4" />
              {t('Löschdialog öffnen')}
            </Button>
          ) : (
            <Button tone="primary" onClick={() => void save()} disabled={busy || !ready}>
              <CalendarPlus className="h-4 w-4" />
              {busy ? t('Speichert…') : t('Ereignis speichern')}
            </Button>
          )}
        </div>
      </div>
      {sendsProfiles && action === '' && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gold-600/60 bg-gold-800/20 px-3 py-2">
          <label className="flex min-w-0 flex-1 items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-gold-400">
            <BellPlus className="h-3.5 w-3.5 shrink-0" />
            {t('Wiedervorlage')}
            <input
              value={followUp.text}
              onChange={(e) => setFollowUp((f) => ({ ...f, text: e.target.value }))}
              maxLength={500}
              className="min-w-0 flex-1 rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
            />
          </label>
          <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
            {t('fällig am')}
            <DateField
              value={followUp.due_date}
              onChange={(due_date) => setFollowUp((f) => ({ ...f, due_date }))}
              className="rounded-md border border-cockpit-line bg-cockpit-surface px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
            />
          </label>
        </div>
      )}
      {action === 'do_not_contact' && (
        <p className="text-[12px] text-coral-300">
          {t('Die Person bleibt gespeichert, erscheint aber nicht mehr in Anruf- und Wiedervorlagelisten.')}
        </p>
      )}
      {erase && (
        <p className="text-[12px] text-coral-300">
          {privacy?.canErase
            ? t('Es wird keine Notiz gespeichert — der Löschdialog öffnet sich mit „Löschung verlangt (Art. 17)“ und dem heutigen Datum.')
            : t('Nur Administratoren dürfen Personen löschen. Bitte einen Admin informieren — bis dahin „Nicht mehr kontaktieren“ wählen.')}
        </p>
      )}
      {error && <p className="text-[12px] text-coral-400">{error}</p>}
    </div>
  )
}
