// The Summary at the top of a candidate's card: everything the recruiter
// wrote down after the Qualifikationsgespräch, in one block, before the
// stepper.
//
// It used to be scattered and below the fold. The Kandidatenauswertung has
// four sections and the product stored them in two places for good reasons
// — A/C/D belong to one mandate, B belongs to the person — but a recruiter
// opening a cockpit does not want to know which table a sentence lives in.
// They want the answer to "who is this, and does he fit", and they were
// getting the nine-step stepper first and the verdict somewhere underneath.
//
// So the two halves are shown together and LABELLED as what they are:
//
//   Passung zum Mandat   — A. Scored against THIS Muss-Profil. Changes when
//                          the person runs on another mandate.
//   Zum Profil           — B. The Gesprächszusammenfassung. The same on
//                          every mandate they run on, because it is about
//                          them and not about the job.
//
// The person half is collapsed by default once it is more than a paragraph:
// it is reference, read when a question comes up, and nine labelled lines
// above the stepper would push the process off the screen it belongs on.

import { useState } from 'react'
import { ChevronDown, ChevronRight, Pencil } from 'lucide-react'

import { cn } from '@/lib/cn'
import { scoreTone } from './ScoreBar'
import { Chip, Label } from './primitives'
import type { CandidateProfile, ProcessCard } from '../data/types'

const TONE_TEXT = {
  mint: 'text-mint-300',
  gold: 'text-gold-300',
  coral: 'text-coral-300',
} as const

/** "92.000 €" — a figure a recruiter reads out, not a formatted cell. */
const eur = (value: number, currency: string | null) =>
  new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: currency || 'EUR',
    maximumFractionDigits: 0,
  }).format(value)

/** The salary line, from whichever of the three numbers are on record.
 *
 *  Minimum and Wunsch are separate questions and a profile that holds only
 *  one must say which one it holds — "ab 92.000 €" and "Wunsch 100.000 €"
 *  are different sentences to a client. */
function salaryLine(profile: CandidateProfile): string | null {
  const { salaryMinimum: min, salaryExpectation: wish, currentSalary: now } = profile
  const c = profile.salaryCurrency
  const parts: string[] = []
  if (min !== null) parts.push(`Minimum ${eur(min, c)}`)
  if (wish !== null) parts.push(`Wunsch ${eur(wish, c)}`)
  if (now !== null) parts.push(`aktuell ${eur(now, c)}`)
  return parts.length > 0 ? parts.join(' · ') : null
}

function Fact({ label, value }: { label: string; value: string | null }) {
  if (!value?.trim()) return null
  return (
    <div className="min-w-0 space-y-1">
      <Label>{label}</Label>
      <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-cockpit-dim">
        {value}
      </p>
    </div>
  )
}

/** The nine labelled lines of section B, in the document's own order. */
function profileFacts(profile: CandidateProfile): { label: string; value: string | null }[] {
  return [
    { label: 'Technisches Know-how', value: profile.technicalProfile },
    { label: 'Kündigungsfrist / Verfügbarkeit', value: profile.noticePeriod ?? profile.availability },
    { label: 'Gehaltsvorstellung', value: salaryLine(profile) },
    { label: 'Wechselmotivation', value: profile.motivation },
    { label: 'Höchster Abschluss', value: profile.education.join('\n') || null },
    { label: 'Verfügbarkeit für Interviews', value: profile.interviewAvailability },
    {
      label: 'Weitere relevante Punkte',
      value: profile.otherNotes,
    },
    {
      label: 'Andere Prozesse',
      value:
        profile.otherProcesses ??
        (profile.otherProcessCompanies.length > 0
          ? profile.otherProcessCompanies.join(', ')
          : null),
    },
  ]
}

export function CandidateSummary({
  card,
  onEdit,
}: {
  card: ProcessCard
  /** Absent on a demo card: there is no row to write to. */
  onEdit?: () => void
}) {
  const [open, setOpen] = useState(false)
  const assessment = card.assessment
  const profile = card.profile
  const facts = profile ? profileFacts(profile).filter((f) => f.value?.trim()) : []
  // The Kurzfazit is the first paragraph; the rest is the argument behind it
  // and stays in the Auswertung further down the card.
  const headline = (assessment?.verdict ?? '').split('\n\n')[0]
  const score = assessment?.fitScore ?? null
  const tone = score === null ? 'gold' : scoreTone(score * 10)

  const hasAnything =
    !!headline || !!profile?.summary || facts.length > 0 || (profile?.focusAreas.length ?? 0) > 0

  if (!hasAnything) {
    return (
      <div className="mt-5 flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-cockpit-line px-4 py-3">
        <p className="font-mono text-[12px] text-cockpit-faint">
          Noch keine Zusammenfassung — nach dem Qualifikationsgespräch hier erfassen.
        </p>
        {onEdit && (
          <button
            type="button"
            onClick={onEdit}
            className="font-mono text-[12px] text-mint-300 underline-offset-2 transition-colors hover:underline"
          >
            Gespräch erfassen
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="mt-5 rounded-xl border border-cockpit-line bg-cockpit-inset/60 px-5 py-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <Label>Zusammenfassung</Label>
        {score !== null && (
          <span className={cn('font-mono text-[18px] font-semibold', TONE_TEXT[tone])}>
            {score}
            <span className="text-[13px] text-cockpit-faint"> / 10</span>
            <span className="ml-2 font-sans text-[12px] font-normal text-cockpit-faint">
              Passung zum Mandat
            </span>
          </span>
        )}
        {onEdit && (
          <button
            type="button"
            onClick={onEdit}
            className="ml-auto flex items-center gap-1.5 font-mono text-[12px] text-cockpit-faint transition-colors hover:text-mint-300"
          >
            <Pencil className="h-3.5 w-3.5" />
            Bearbeiten
          </button>
        )}
      </div>

      {headline && (
        <p className="mt-3 max-w-4xl text-[15px] leading-relaxed text-cockpit-text">
          {headline}
        </p>
      )}

      {profile?.summary && (
        <div className="mt-4 space-y-1.5">
          {/* Said out loud, because it is the one thing on this card that is
              NOT about this mandate: edit it here and it changes on every
              process the person runs. */}
          <Label>Zum Profil · gilt für alle Mandate</Label>
          <p className="max-w-4xl whitespace-pre-wrap text-[14px] leading-relaxed text-cockpit-dim">
            {profile.summary}
          </p>
        </div>
      )}

      {(profile?.focusAreas.length ?? 0) > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-1.5">
          <Label className="mr-1">Schwerpunkte</Label>
          {profile?.focusAreas.map((area) => <Chip key={area}>{area}</Chip>)}
        </div>
      )}

      {facts.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setOpen((shown) => !shown)}
            className="mt-4 flex items-center gap-1.5 font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint transition-colors hover:text-cockpit-text"
          >
            {open ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            Gesprächszusammenfassung
            <span className="normal-case tracking-normal">
              · {facts.length} {facts.length === 1 ? 'Angabe' : 'Angaben'}
            </span>
          </button>
          {open && (
            <div className="mt-4 grid gap-x-10 gap-y-4 border-t border-cockpit-line pt-4 lg:grid-cols-2">
              {facts.map((fact) => (
                <Fact key={fact.label} label={fact.label} value={fact.value} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
