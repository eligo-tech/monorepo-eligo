// The Kandidatenauswertung, written after the Qualifikationsgespräch.
//
// It was readable and not writable: `data/examples/KandidatenInfo.txt` could
// be imported by a script, the cockpit rendered 8/10 with Stärken and
// Risiken, and a recruiter who had just put the phone down had no way to
// record the same thing for the next candidate. The endpoint existed; the
// form did not.
//
// Keyed on the APPLICATION, like the stored row: the same person against
// another Muss-Profil is a different fit, a different risk list and a
// different text for the client.
//
// A full replacement, not a patch — the server says so too. A recruiter
// re-reads the whole evaluation after a round, and a half-updated verdict
// (new risks, old Kurzfazit) is worse than no verdict at all.

import { useState } from 'react'
import { Save, X } from 'lucide-react'

import { api } from '@/api/client'
import { Button } from './forms'
import type { CandidateAssessment, ProcessCard } from '../data/types'

/** One line per entry: the way these lists are actually written down. */
const toLines = (values: string[] | undefined) => (values ?? []).join('\n')
const fromLines = (text: string) =>
  text
    .split('\n')
    .map((line) => line.replace(/^[-•*]\s*/, '').trim())
    .filter(Boolean)

const toCommas = (values: string[] | undefined) => (values ?? []).join(', ')
const fromCommas = (text: string) =>
  text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block space-y-1">
      <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-cockpit-faint">
        {label}
        {hint && <span className="ml-2 normal-case tracking-normal">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

const BOX =
  'w-full rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 text-[13.5px] leading-relaxed text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none'

export function AssessmentEditor({
  card,
  onClose,
  onSaved,
}: {
  card: ProcessCard
  onClose: () => void
  onSaved?: () => void
}) {
  const a: CandidateAssessment | undefined = card.assessment
  const [score, setScore] = useState(a?.fitScore != null ? String(a.fitScore) : '')
  const [verdict, setVerdict] = useState(a?.verdict ?? '')
  const [strengths, setStrengths] = useState(toLines(a?.strengths))
  const [risks, setRisks] = useState(toLines(a?.risks))
  const [clientSummary, setClientSummary] = useState(a?.clientSummary ?? '')
  const [technologies, setTechnologies] = useState(toCommas(a?.technologies))
  const [basis, setBasis] = useState(a?.basis ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    const value = score.trim() === '' ? null : Number(score)
    if (value !== null && (Number.isNaN(value) || value < 0 || value > 10)) {
      return setError('Die Passung ist eine Zahl von 0 bis 10.')
    }
    setBusy(true)
    setError(null)
    try {
      await api.setAssessment(card.id, {
        fit_score: value,
        verdict: verdict.trim() || null,
        strengths: fromLines(strengths),
        risks: fromLines(risks),
        client_summary: clientSummary.trim() || null,
        technologies: fromCommas(technologies),
        basis: basis.trim() || null,
      })
      onSaved?.()
      onClose()
    } catch {
      setError('Nicht gespeichert — bitte erneut versuchen.')
      setBusy(false)
    }
  }

  return (
    <div className="mt-6 space-y-4 border-t border-cockpit-line pt-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          Auswertung · {card.candidateName}
        </span>
        <span className="font-mono text-[11.5px] text-cockpit-faint">
          {card.mandateRef} · gilt nur für dieses Mandat
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="grid grid-cols-[6rem_1fr] gap-3">
            <Field label="Passung" hint="0–10">
              <input
                value={score}
                onChange={(e) => setScore(e.target.value)}
                inputMode="numeric"
                placeholder="8"
                className={`${BOX} font-mono`}
              />
            </Field>
            <Field label="Grundlage" hint="worauf beruht das Urteil">
              <input
                value={basis}
                onChange={(e) => setBasis(e.target.value)}
                placeholder="CV (Kurzversion) + Gesprächstranskript 18.09.2026"
                className={BOX}
              />
            </Field>
          </div>

          <Field label="Kurzfazit">
            <textarea
              value={verdict}
              onChange={(e) => setVerdict(e.target.value)}
              rows={4}
              placeholder="Sehr passgenauer Senior-Kandidat — deckt das Muss-Profil vollständig ab …"
              className={BOX}
            />
          </Field>

          <Field label="Relevante Technologien" hint="mit Komma getrennt">
            <input
              value={technologies}
              onChange={(e) => setTechnologies(e.target.value)}
              placeholder="Java, Jakarta EE, WildFly, JPA/Hibernate"
              className={BOX}
            />
          </Field>
        </div>

        <div className="space-y-4">
          <Field label="Stärken" hint="eine pro Zeile">
            <textarea
              value={strengths}
              onChange={(e) => setStrengths(e.target.value)}
              rows={5}
              placeholder={'Deckt das Muss vollständig ab\nArchitektur-Verantwortung real gelebt'}
              className={BOX}
            />
          </Field>
          <Field label="Lücken / Risiken" hint="eine pro Zeile">
            <textarea
              value={risks}
              onChange={(e) => setRisks(e.target.value)}
              rows={5}
              placeholder={'Gehalt am oberen Rand\nKündigungsfrist 3 Monate'}
              className={BOX}
            />
          </Field>
        </div>
      </div>

      <Field label="Text für den Kunden" hint="geht so in die Vorstellung">
        <textarea
          value={clientSummary}
          onChange={(e) => setClientSummary(e.target.value)}
          rows={4}
          placeholder="Der Kandidat ist ein Senior Software Entwickler und Architekt mit …"
          className={BOX}
        />
      </Field>

      {error && <p className="text-[12.5px] text-coral-400">{error}</p>}

      <div className="flex items-center gap-2">
        <Button tone="primary" onClick={() => void save()} disabled={busy}>
          <Save className="h-4 w-4" /> {busy ? 'Speichert…' : 'Auswertung speichern'}
        </Button>
        <Button onClick={onClose}>
          <X className="h-4 w-4" /> Abbrechen
        </Button>
      </div>
    </div>
  )
}
