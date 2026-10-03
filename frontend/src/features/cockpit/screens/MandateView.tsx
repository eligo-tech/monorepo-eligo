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
import { Panel, SectionHeader } from '../ui/primitives'
import type { CompanyDTO, ManagerDTO } from '@/api/types'
import { ActivityPanel } from './mandate/ActivityPanel'
import { FeedbackPanel } from './mandate/FeedbackPanel'
import { QualificationPanel } from './mandate/QualificationPanel'
import { SourcingPanel } from './mandate/SourcingPanel'
import { StammdatenPanel } from './mandate/StammdatenPanel'
import { SuchprofilPanel } from './mandate/SuchprofilPanel'
import type { Mandate, ProcessCard, ProcessStep } from '../data/types'

/** The money, measured against the band — arithmetic, not an opinion.
 *
 *  "Verhandelbar" is its own state and is deliberately not red: a wish above
 *  the band with a floor inside it is the conversation the recruiter is paid
 *  to have, and colouring it like a rejection would lose the candidate the
 *  example document scores 8/10. */
function SalaryVerdict({ fit }: { fit: NonNullable<ProcessCard['salaryFit']> }) {
  const TONE = {
    fits: 'border-mint-600 bg-mint-800/30 text-mint-300',
    negotiable: 'border-gold-600 bg-gold-800/30 text-gold-300',
    above_band: 'border-coral-600 bg-coral-800/30 text-coral-300',
  } as const
  const LABEL = {
    fits: 'Gehalt im Band',
    negotiable: 'Gehalt verhandelbar',
    above_band: 'Gehalt über Band',
  } as const

  return (
    <div className="mt-5 flex flex-wrap items-center gap-2.5">
      <span
        className={`rounded-md border px-2 py-0.5 font-mono text-[12px] leading-5 ${TONE[fit.status]}`}
      >
        {LABEL[fit.status]}
      </span>
      {fit.detail && (
        <span className="font-mono text-[12px] text-cockpit-faint">{fit.detail}</span>
      )}
    </div>
  )
}

export function MandateView({
  mandate,
  company,
  manager,
  onBack,
  onChanged,
}: {
  mandate: Mandate
  /** The client company record, for the Stammdaten block. */
  company?: CompanyDTO
  /** Its hiring manager, when one has been enriched. */
  manager?: ManagerDTO
  onBack: () => void
  /** Re-read the cockpit after a step was written. */
  onChanged?: () => void
}) {
  const [editing, setEditing] = useState<{ card: ProcessCard; step: ProcessStep } | null>(
    null,
  )
  const assessed = mandate.cards.filter((c) => c.assessment).length

  return (
    <div className="space-y-6">
      <header id="section-mandat" className="scroll-mt-24">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint transition-colors hover:text-cockpit-text"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Gesamtansicht
        </button>
        <span className="mt-3 block font-mono text-[11px] uppercase tracking-[0.22em] text-lav-400">
          Job-Workspace
        </span>
        <h1 className="mt-1.5 text-[40px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Mandat &amp; Kandidatensuche
        </h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-cockpit-dim">
          Die Stammdaten des Mandats plus die komplette Kandidatensuche in einem
          Bereich — vom Job über Ansprache und Ergebnisse bis zur Qualifizierung.
        </p>
        <p className="mt-3 font-mono text-[13px] text-cockpit-faint">
          {mandate.ref} · {mandate.client} · {mandate.cards.length}{' '}
          {mandate.cards.length === 1 ? 'Kandidat' : 'Kandidaten'} im Prozess
          {assessed > 0 && ` · ${assessed} bewertet`}
        </p>
      </header>

      <StammdatenPanel mandate={mandate} company={company} manager={manager} />

      <FeedbackPanel mandate={mandate} onChanged={onChanged} />

      <section className="space-y-4">
        <SectionHeader
          id="section-prozesse"
          title={`Laufende Prozesse · ${mandate.ref} · ${mandate.title}`}
          tone="coral"
          hint="Schritte antippen · Bewertung je Mandat"
        />
        <div className="space-y-4">
          {mandate.cards.length === 0 ? (
            <Panel className="px-6 py-8 text-center text-[14px] text-cockpit-dim">
              Für dieses Mandat läuft noch kein Prozess.
            </Panel>
          ) : (
            mandate.cards.map((card) => (
              <ProcessCardPanel
                key={card.id}
                card={card}
                onStepClick={
                  card.editable ? (step) => setEditing({ card, step }) : undefined
                }
              >
                {card.salaryFit && <SalaryVerdict fit={card.salaryFit} />}
                {card.assessment ? (
                  <AssessmentPanel assessment={card.assessment} />
                ) : (
                  <p className="mt-6 border-t border-cockpit-line pt-5 font-mono text-[12px] text-cockpit-faint">
                    Noch keine Auswertung für dieses Mandat.
                  </p>
                )}
              </ProcessCardPanel>
            ))
          )}
        </div>
      </section>

      <ActivityPanel mandate={mandate} />
      <SuchprofilPanel mandate={mandate} />
      <SourcingPanel mandate={mandate} />
      <QualificationPanel mandate={mandate} />

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
