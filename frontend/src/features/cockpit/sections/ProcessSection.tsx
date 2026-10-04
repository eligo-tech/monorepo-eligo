// "02 Laufende Prozesse" — grouped by mandate, as the design groups them and
// as the recruiter's tracker does: a job heading, then the candidates running
// on it on an indented rail.
//
// The heading answers the question a flat list could not: for THIS search,
// how many people are in play and how far has the best of them come. Cards
// come from the tracker (process steps) when the backend is reachable, else
// from the coarse pipeline board.
//
// Tapping a step opens its editor — the header has promised "Schritte
// antippen" since the mockup. Only cards backed by real process rows are
// editable; a demo card has nothing to write to.

import { useState } from 'react'

import { api } from '@/api/client'
import { StepEditor } from '../ui/StepEditor'
import { ProcessCardPanel } from '../ui/ProcessCardPanel'
import { Money, Panel, SectionHeader } from '../ui/primitives'
import type { Mandate, ProcessCard, ProcessStep } from '../data/types'

/** What the mandate is waiting on: the first step that is not done.
 *
 *  Mirrors the design's `stageLabel` — "bester Stand" names the next thing
 *  that has to happen, not the last thing that did, because that is what a
 *  recruiter acts on. */
function bestStand(cards: ProcessCard[]): string {
  const furthest = cards.reduce((best, card) =>
    card.progress.value > best.progress.value ? card : best,
  )
  if (furthest.steps.some((s) => s.state === 'out')) return 'abgesagt'
  const open = furthest.steps.find((s) => s.state !== 'done')
  return open ? open.label : 'Vertrag'
}

function MandateHead({ mandate }: { mandate: Mandate }) {
  const count = mandate.cards.length
  // Fee is demo-only until a Honorarmodell exists; a header reading
  // "Fee € 0" would be worse than one that stays quiet about money.
  const fee = mandate.cards
    .map((c) => c.fee)
    .filter((f) => f.value > 0)
    .sort((a, b) => b.value - a.value)[0]

  return (
    <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-cockpit-line bg-cockpit-inset px-3.5 py-2.5">
      <div className="min-w-0">
        <span className="text-[14px] font-semibold text-cockpit-text">
          <span className="font-mono font-medium">{mandate.ref}</span> · {mandate.title}
        </span>
        <span className="block text-[11.5px] text-cockpit-dim">{mandate.client}</span>
      </div>
      <div className="ml-auto text-right font-mono text-[11px] text-cockpit-faint">
        {count} {count === 1 ? 'Kandidat' : 'Kandidaten'} · bester Stand:{' '}
        <span className="text-cockpit-text">{bestStand(mandate.cards)}</span>
        {fee && (
          <>
            {' '}
            · Fee <Money figure={fee} className="text-mint-400" />
          </>
        )}
      </div>
    </div>
  )
}

export function ProcessSection({
  mandates,
  isLive,
  onStepClick,
  onChanged,
  onOpenMandate,
}: {
  mandates: Mandate[]
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
  const total = mandates.reduce((n, m) => n + m.cards.length, 0)

  return (
    <section className="space-y-5">
      <SectionHeader
        id="section-02"
        index="02"
        title="Laufende Prozesse"
        tone="coral"
        hint="Schritte antippen · Mandat öffnen"
      />

      {total === 0 ? (
        <Panel className="px-6 py-10 text-center text-[15px] text-cockpit-dim">
          Kein Kandidat ist derzeit vorgestellt — sobald ein Profil beim Kunden liegt,
          erscheint der Prozess hier.
        </Panel>
      ) : (
        <div className="space-y-5">
          {mandates.map((mandate) => (
            <div key={mandate.id}>
              <button
                type="button"
                onClick={() => onOpenMandate?.(mandate.id)}
                disabled={!onOpenMandate}
                title={onOpenMandate ? 'Mandat öffnen' : undefined}
                className="block w-full text-left transition-opacity enabled:hover:opacity-90"
              >
                <MandateHead mandate={mandate} />
              </button>

              {/* The rail is the design's: candidates hang off their mandate
                  rather than floating next to it. */}
              <div className="ml-[7px] space-y-3 border-l-2 border-cockpit-line pl-[13px]">
                {mandate.cards.map((card) => (
                  <ProcessCardPanel
                    key={card.id}
                    card={card}
                    onAddStep={
                      card.editable
                        ? async (label, after) => {
                            await api.addProcessStep(card.id, { label, after })
                            onChanged?.()
                          }
                        : undefined
                    }
                    onRemoveStep={
                      card.editable
                        ? async (step) => {
                            await api.removeProcessStep(card.id, step.key)
                            onChanged?.()
                          }
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
            </div>
          ))}
        </div>
      )}

      {!isLive && total > 0 && (
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
