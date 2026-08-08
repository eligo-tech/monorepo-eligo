// "03 Laufende Prozesse" — one card per live placement, with the nine-step
// stepper. Cards come from the pipeline board when the backend is reachable.

import { ProgressRing } from '../ui/Gauge'
import { ProcessStepper } from '../ui/ProcessStepper'
import { Chip, Money, Panel, SectionHeader } from '../ui/primitives'
import type { ProcessCard, ProcessStep } from '../data/types'

export function ProcessSection({
  cards,
  isLive,
  onStepClick,
}: {
  cards: ProcessCard[]
  isLive: boolean
  onStepClick?: (card: ProcessCard, step: ProcessStep) => void
}) {
  return (
    <section className="space-y-5">
      <SectionHeader
        id="section-03"
        index="03"
        title="Laufende Prozesse"
        tone="coral"
        hint="Schritte antippen · Deal bestätigen"
      />

      {cards.length === 0 ? (
        <Panel className="px-6 py-10 text-center text-[15px] text-cockpit-dim">
          Kein Kandidat ist derzeit vorgestellt — sobald ein Profil beim Kunden liegt,
          erscheint der Prozess hier.
        </Panel>
      ) : (
        <div className="space-y-4">
          {cards.map((card) => (
            <Panel key={card.id} tone="raised" className="px-7 py-6">
              <div className="flex flex-wrap items-start gap-x-5 gap-y-3">
                <ProgressRing figure={card.progress} />

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <h3 className="text-[19px] font-semibold text-cockpit-text">
                      <span className="font-mono font-medium">{card.candidateRef}</span>
                      <span className="text-cockpit-faint"> · </span>
                      {card.candidateName}
                      <span className="text-cockpit-faint"> · </span>
                      {card.role}
                    </h3>
                    {card.statusNote && <Chip tone="mint">{card.statusNote}</Chip>}
                  </div>
                  <p className="mt-1 font-mono text-[13px] text-cockpit-faint">
                    {card.mandateRef} · {card.client} · {card.paceLabel}
                    {card.pacePro === 'demo' && (
                      <sup
                        title="Demo-Wert — keine Verweilzeiten im Reporting"
                        className="cursor-help"
                      >
                        °
                      </sup>
                    )}
                  </p>
                </div>

                <div className="shrink-0 text-right">
                  <Money figure={card.fee} className="block text-[22px] text-mint-400" />
                  <span className="font-mono text-[12px] text-cockpit-faint">Fee-Potenzial</span>
                </div>
              </div>

              <div className="mt-6">
                <ProcessStepper
                  steps={card.steps}
                  onStepClick={onStepClick ? (step) => onStepClick(card, step) : undefined}
                />
              </div>
            </Panel>
          ))}
        </div>
      )}

      {!isLive && cards.length > 0 && (
        <p className="font-mono text-[12px] text-cockpit-faint">
          ° Demo-Prozesse — sobald Bewerbungen den Status „vorgestellt" erreichen, kommen
          die Karten aus der Pipeline.
        </p>
      )}
    </section>
  )
}
