// The cockpit, scoped to one mandate.
//
// The overall view answers "where does the book of business stand". This one
// answers the question a client actually asks on the phone: *where does MY
// search stand* — who is in it, how far each has come, and how they measure
// against the Suchprofil. The flat list of process cards could only be read
// sideways to answer that.
//
// Both halves of a mandate are on the page: what is being searched for (the
// Suchprofil, from the job record) and who is running on it (the same process
// cards as the overall view, plus each candidate's Kandidatenauswertung).

import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'

import { AssessmentPanel } from '../ui/AssessmentPanel'
import { ProcessCardPanel } from '../ui/ProcessCardPanel'
import { StepEditor } from '../ui/StepEditor'
import { Chip, Label, Panel, SectionHeader } from '../ui/primitives'
import type { Mandate, ProcessCard, ProcessStep } from '../data/types'

/** "80.000 – 95.000 €", or null when the mandate carries no band. */
function salaryBand(mandate: Mandate): string | null {
  const { salaryMin: min, salaryMax: max } = mandate
  if (min === null && max === null) return null
  const currency = mandate.salaryCurrency === 'EUR' ? '€' : (mandate.salaryCurrency ?? '')
  const money = (v: number) => v.toLocaleString('de-DE')
  const range =
    min !== null && max !== null
      ? `${money(min)} – ${money(max)}`
      : min !== null
        ? `ab ${money(min)}`
        : `bis ${money(max as number)}`
  return `${range} ${currency}`.trim()
}

/** A fact of the Suchprofil, or an honest gap. Inventing a radius or a band
 *  would put a hard filter in front of candidates that nobody agreed. */
function Fact({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <p
        className={
          value ? 'text-[15px] text-cockpit-text' : 'text-[15px] text-cockpit-faint'
        }
      >
        {value ?? 'nicht hinterlegt'}
      </p>
    </div>
  )
}

export function MandateView({
  mandate,
  onBack,
  onChanged,
}: {
  mandate: Mandate
  onBack: () => void
  /** Re-read the cockpit after a step was written. */
  onChanged?: () => void
}) {
  const [editing, setEditing] = useState<{ card: ProcessCard; step: ProcessStep } | null>(
    null,
  )
  const assessed = mandate.cards.filter((c) => c.assessment).length

  return (
    <div className="space-y-10">
      <header id="section-mandat" className="scroll-mt-24">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint transition-colors hover:text-cockpit-text"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Gesamtansicht
        </button>
        <h1 className="mt-3 text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          {mandate.title}
        </h1>
        <p className="mt-2 font-mono text-[13px] text-cockpit-faint">
          {mandate.ref} · {mandate.client} · {mandate.cards.length}{' '}
          {mandate.cards.length === 1 ? 'Kandidat' : 'Kandidaten'} im Prozess
          {assessed > 0 && ` · ${assessed} bewertet`}
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          id="section-suchprofil"
          index="01"
          title="Suchprofil"
          tone="gold"
          hint="Harte Kriterien · aus dem Mandat"
        />
        <Panel className="px-7 py-6">
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            <Fact label="Ort" value={mandate.location} />
            <Fact label="Gehaltsband" value={salaryBand(mandate)} />
            <Fact label="Status" value={mandate.status} />
            <Fact label="Kunde" value={mandate.client} />
          </div>
          <div className="mt-6 space-y-2">
            <Label>Muss-Kriterien</Label>
            {mandate.mustHave.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {mandate.mustHave.map((skill) => (
                  <Chip key={skill} tone="gold">
                    {skill}
                  </Chip>
                ))}
              </div>
            ) : (
              <p className="text-[15px] text-cockpit-faint">
                Keine Muss-Kriterien hinterlegt — ohne sie filtert das Matching nicht.
              </p>
            )}
          </div>
        </Panel>
      </section>

      <section className="space-y-5">
        <SectionHeader
          id="section-kandidaten"
          index="02"
          title="Kandidaten im Prozess"
          tone="coral"
          hint="Schritte antippen · Bewertung je Mandat"
        />
        <div className="space-y-4">
          {mandate.cards.map((card) => (
            <ProcessCardPanel
              key={card.id}
              card={card}
              onStepClick={
                card.editable ? (step) => setEditing({ card, step }) : undefined
              }
            >
              {card.assessment ? (
                <AssessmentPanel assessment={card.assessment} />
              ) : (
                <p className="mt-6 border-t border-cockpit-line pt-5 font-mono text-[12px] text-cockpit-faint">
                  Noch keine Auswertung für dieses Mandat.
                </p>
              )}
            </ProcessCardPanel>
          ))}
        </div>
      </section>

      {editing && (
        <StepEditor
          card={editing.card}
          step={editing.step}
          onClose={() => setEditing(null)}
          onSaved={() => onChanged?.()}
        />
      )}
    </div>
  )
}
