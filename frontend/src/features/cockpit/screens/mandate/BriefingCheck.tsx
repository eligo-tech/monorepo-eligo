// Briefing-Bewertung (ELI-47): how much of the briefing is geklärt, and what
// to ask the client next.
//
// The score and the list come from the backend with the job
// (`JobDTO.briefing`) — this only renders them. Each missing point is a
// button that opens the form at its field, so "Gehaltsrahmen fehlt" is one
// click from the box it needs; the contact is picked in the Stammdaten.
// Saving goes through the same PATCH as "Mandat bearbeiten": one receipt per
// changed field.

import { t } from '@/i18n'

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, CircleDashed, Pencil } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { JobDTO } from '@/api/types'
import { Button, FieldLabel, TagInput, TextArea, TextInput } from '../../ui/forms'
import {
  type BriefingDraft,
  briefingDraft,
  briefingPatch,
  missingLabel,
  pointTarget,
  scoreLine,
} from './briefingPoints'

/** Focus the box a point is written in. Text inputs and textareas both. */
function focusField(root: HTMLElement | null, field: string) {
  const at = '[data-field="' + field + '"]'
  const box = root?.querySelector<HTMLElement>([at + ' input', at + ' textarea'].join(', '))
  box?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  box?.focus({ preventScroll: true })
}

function Area({
  field,
  label,
  value,
  onChange,
  placeholder,
}: {
  field: string
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <label className="block min-w-0" data-field={field}>
      <FieldLabel>{label}</FieldLabel>
      <TextArea value={value} onChange={onChange} rows={2} placeholder={placeholder} />
    </label>
  )
}

function Tags({
  field,
  label,
  tags,
  onChange,
  placeholder,
}: {
  field: string
  label: string
  tags: string[]
  onChange: (v: string[]) => void
  placeholder?: string
}) {
  return (
    <div className="min-w-0" data-field={field}>
      <FieldLabel>{label}</FieldLabel>
      <TagInput tags={tags} onChange={onChange} placeholder={placeholder} />
    </div>
  )
}

export function BriefingCheck({
  job,
  onSaved,
}: {
  job: JobDTO
  /** The saved job — the caller re-reads whatever else shows these fields. */
  onSaved: (updated: JobDTO) => void
}) {
  const [editing, setEditing] = useState(false)
  const [d, setD] = useState<BriefingDraft>(() => briefingDraft(job))
  // The draft as the form opened — what a save is diffed against.
  const [base, setBase] = useState<BriefingDraft>(() => briefingDraft(job))
  const [focus, setFocus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const root = useRef<HTMLDivElement>(null)

  // After the form has rendered, land in the field that was asked for.
  useEffect(() => {
    if (editing && focus) {
      focusField(root.current, focus)
      setFocus(null)
    }
  }, [editing, focus])

  const score = job.briefing
  if (!score) return null

  const set = <K extends keyof BriefingDraft>(key: K, value: BriefingDraft[K]) =>
    setD((prev) => ({ ...prev, [key]: value }))

  function open(field?: string) {
    if (!editing) {
      const fresh = briefingDraft(job)
      setD(fresh)
      setBase(fresh)
    }
    setEditing(true)
    setError(null)
    if (field) setFocus(field)
  }

  function goTo(key: string) {
    const target = pointTarget(key)
    if ('section' in target) {
      document
        .getElementById(target.section)
        ?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    } else {
      open(target.field)
    }
  }

  async function save() {
    const result = briefingPatch(base, d)
    if (!result.ok) return setError(result.error)
    if (Object.keys(result.patch).length === 0) return setEditing(false)
    setBusy(true)
    setError(null)
    try {
      const updated = await api.updateJob(job.id, result.patch)
      onSaved(updated)
      setEditing(false)
    } catch (e) {
      setError(
        e instanceof ApiError
          ? t('Konnte nicht gespeichert werden (HTTP {status}).', { status: e.status })
          : t('Konnte nicht gespeichert werden — keine Antwort vom Server.'),
      )
    } finally {
      setBusy(false)
    }
  }

  const complete = score.missing.length === 0

  return (
    <div ref={root} className="mb-5 rounded-xl border border-cockpit-line bg-cockpit-inset/40 px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-cockpit-faint">
          {t('Briefing-Bewertung')}
        </span>
        <b
          className={`font-mono text-[13px] ${
            complete ? 'text-mint-300' : score.done >= 7 ? 'text-gold-300' : 'text-coral-300'
          }`}
        >
          {scoreLine(score)}
        </b>
        {!editing && (
          <button
            type="button"
            onClick={() => open()}
            className="ml-auto flex items-center gap-1 font-mono text-[12px] text-cockpit-faint transition-colors hover:text-mint-300"
          >
            <Pencil className="h-3.5 w-3.5" /> {t('Briefing-Punkte bearbeiten')}
          </button>
        )}
      </div>

      {complete ? (
        <p className="mt-2 flex items-center gap-1.5 text-[13px] text-mint-300">
          <CheckCircle2 className="h-4 w-4" /> {t('Alle Punkte geklärt.')}
        </p>
      ) : (
        <>
          <p className="mt-2 text-[12px] text-cockpit-faint">
            {t('Beim Kunden noch nachfragen:')}
          </p>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {score.missing.map((key) => (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => goTo(key)}
                  className="flex items-center gap-1 rounded-md border border-dashed border-gold-600/50 px-2 py-0.5 text-[12.5px] text-gold-300 transition-colors hover:border-gold-500 hover:bg-gold-500/10"
                >
                  <CircleDashed className="h-3 w-3" />
                  {missingLabel(key)}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {editing && (
        <div className="mt-4 space-y-3 border-t border-cockpit-line pt-4">
          <Area
            field="tasks"
            label={t('Aufgaben')}
            value={d.tasks}
            onChange={(v) => set('tasks', v)}
            placeholder={t('Was die Person tatsächlich tun wird …')}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Tags
              field="must_have_skills"
              label={t('Muss-Kriterien')}
              tags={d.must_have_skills}
              onChange={(v) => set('must_have_skills', v)}
              placeholder={t('Skill hinzufügen…')}
            />
            <Tags
              field="nice_to_have_skills"
              label={t('Kann-Kriterien')}
              tags={d.nice_to_have_skills}
              onChange={(v) => set('nice_to_have_skills', v)}
              placeholder={t('Skill hinzufügen…')}
            />
            <TextInput
              name="salary_min"
              label={t('Gehalt von')}
              value={d.salary_min}
              onChange={(v) => set('salary_min', v)}
              type="number"
            />
            <TextInput
              name="salary_max"
              label={t('Gehalt bis (Obergrenze)')}
              value={d.salary_max}
              onChange={(v) => set('salary_max', v)}
              type="number"
            />
            <TextInput
              name="location"
              label={t('Standort/Remote')}
              value={d.location}
              onChange={(v) => set('location', v)}
              placeholder={t('z. B. München · 2 Tage remote')}
            />
            <TextInput
              name="start_date"
              label={t('Startdatum')}
              value={d.start_date}
              onChange={(v) => set('start_date', v)}
              placeholder={t('z. B. sofort, Q2, zum 1. März')}
            />
            <TextInput
              name="team_size"
              label={t('Teamgröße')}
              value={d.team_size}
              onChange={(v) => set('team_size', v)}
              placeholder={t('z. B. 6 Entwickler + PO')}
            />
          </div>
          <Area
            field="interview_process"
            label={t('Prozess beim Kunden')}
            value={d.interview_process}
            onChange={(v) => set('interview_process', v)}
            placeholder={t('Interviewrunden, wer entscheidet …')}
          />
          <Area
            field="vacancy_reason"
            label={t('Grund der Vakanz')}
            value={d.vacancy_reason}
            onChange={(v) => set('vacancy_reason', v)}
            placeholder={t('Nachfolge, Wachstum, neue Abteilung …')}
          />
          <p className="text-[12px] leading-relaxed text-cockpit-faint">
            {t('Muss-Kriterien, Obergrenze und Ort sind harte Filter im Matching. Jede Änderung wird mit Beleg protokolliert.')}
          </p>
          {error && (
            <p className="flex items-center gap-1.5 text-[13px] text-coral-400">
              <AlertCircle className="h-4 w-4 shrink-0" /> {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button onClick={() => setEditing(false)}>{t('Abbrechen')}</Button>
            <Button tone="primary" onClick={() => void save()} disabled={busy}>
              {busy ? t('Speichert…') : t('Speichern')}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
