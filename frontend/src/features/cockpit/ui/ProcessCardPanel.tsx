// One running process, as a card: the ring, who on which mandate, the fee,
// and the nine-step stepper.
//
// Extracted from "03 Laufende Prozesse" so the per-job view can show the very
// same card. Two renderings of one process would drift, and a recruiter
// comparing the overall list with a mandate would have to work out which one
// to believe.

import type { ReactNode } from 'react'

import { ProgressRing } from './Gauge'
import { ProcessStepper } from './ProcessStepper'
import { Chip, Money, Panel } from './primitives'
import type { ProcessCard, ProcessStep } from '../data/types'

export function ProcessCardPanel({
  card,
  onStepClick,
  onMandateClick,
  children,
}: {
  card: ProcessCard
  onStepClick?: (step: ProcessStep) => void
  /** Set in the overall view: the mandate ref opens that mandate's view. */
  onMandateClick?: () => void
  /** Rendered inside the card, under the stepper — the assessment, per job. */
  children?: ReactNode
}) {
  return (
    <Panel tone="raised" className="px-7 py-6">
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
            {onMandateClick ? (
              <button
                type="button"
                onClick={onMandateClick}
                title="Mandat öffnen"
                className="text-cockpit-dim underline-offset-2 transition-colors hover:text-cockpit-text hover:underline"
              >
                {card.mandateRef} · {card.client}
              </button>
            ) : (
              <>
                {card.mandateRef} · {card.client}
              </>
            )}{' '}
            · {card.paceLabel}
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
        <ProcessStepper steps={card.steps} onStepClick={onStepClick} />
      </div>

      {children}
    </Panel>
  )
}
