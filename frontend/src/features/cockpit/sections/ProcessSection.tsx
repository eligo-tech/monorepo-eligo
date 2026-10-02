// "03 Laufende Prozesse" — one card per live placement, with the nine-step
// stepper. Cards come from the recruiter's tracker (process steps) when the
// backend is reachable, else from the coarse pipeline board.
//
// Tapping a step opens its editor — the header has promised "Schritte
// antippen" since the mockup. Only cards backed by real process rows are
// editable; a demo card has nothing to write to.

import { useState } from 'react'

import { StepEditor } from '../ui/StepEditor'
import { ProcessCardPanel } from '../ui/ProcessCardPanel'
import { Panel, SectionHeader } from '../ui/primitives'
import type { ProcessCard, ProcessStep } from '../data/types'

export function ProcessSection({
  cards,
  isLive,
  onStepClick,
  onChanged,
  onOpenMandate,
}: {
  cards: ProcessCard[]
  isLive: boolean
  onStepClick?: (card: ProcessCard, step: ProcessStep) => void
  /** Called after a step was written, so the cockpit can re-read it. */
  onChanged?: () => void
  /** Opens the per-job view for one mandate. */
  onOpenMandate?: (mandateId: string) => void
}) {
  const [editing, setEditing] = useState<{ card: ProcessCard; step: ProcessStep } | null>(
    null,
  )

  return (
    <section className="space-y-5">
      <SectionHeader
        id="section-03"
        index="03"
        title="Laufende Prozesse"
        tone="coral"
        hint="Schritte antippen · Mandat öffnen"
      />

      {cards.length === 0 ? (
        <Panel className="px-6 py-10 text-center text-[15px] text-cockpit-dim">
          Kein Kandidat ist derzeit vorgestellt — sobald ein Profil beim Kunden liegt,
          erscheint der Prozess hier.
        </Panel>
      ) : (
        <div className="space-y-4">
          {cards.map((card) => (
            <ProcessCardPanel
              key={card.id}
              card={card}
              onMandateClick={
                onOpenMandate
                  ? () => onOpenMandate(card.jobId ?? card.mandateRef)
                  : undefined
              }
              onStepClick={
                card.editable
                  ? (step) => {
                      setEditing({ card, step })
                      onStepClick?.(card, step)
                    }
                  : onStepClick
                    ? (step) => onStepClick(card, step)
                    : undefined
              }
            />
          ))}
        </div>
      )}

      {!isLive && cards.length > 0 && (
        <p className="font-mono text-[12px] text-cockpit-faint">
          ° Demo-Prozesse — sobald Bewerbungen den Status „vorgestellt" erreichen, kommen
          die Karten aus der Pipeline.
        </p>
      )}

      {editing && (
        <StepEditor
          card={editing.card}
          step={editing.step}
          onClose={() => setEditing(null)}
          onSaved={() => onChanged?.()}
        />
      )}
    </section>
  )
}
