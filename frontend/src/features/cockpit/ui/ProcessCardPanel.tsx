// One running process, as a card: the ring, who on which mandate, the fee,
// and the nine-step stepper.
//
// Extracted from "03 Laufende Prozesse" so the per-job view can show the very
// same card. Two renderings of one process would drift, and a recruiter
// comparing the overall list with a mandate would have to work out which one
// to believe.
//
// It collapses. A mandate with five candidates is five summaries, five
// steppers and five assessments, and the question "who is on this mandate?"
// then needs a page of scrolling to answer. Collapsed, the card keeps the
// line that identifies it — ref, name, role, mandate, fee — and adds the
// step it is on, so a folded card still says something.
//
// The choice is remembered per card, because a collapse that forgets itself
// on reload is a collapse nobody uses twice.

import type { ReactNode } from 'react'

import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'

import { useRemembered } from '@/hooks/useRemembered'
import { ProgressRing } from './Gauge'
import { ProcessStepper } from './ProcessStepper'
import { Chip, Money, Panel } from './primitives'
import type { ProcessCard, ProcessStep } from '../data/types'

export function ProcessCardPanel({
  card,
  onStepClick,
  onAddStep,
  onRemoveStep,
  onMandateClick,
  summary,
  children,
}: {
  card: ProcessCard
  onStepClick?: (step: ProcessStep) => void
  /** Only live cards can be edited: a demo card has no row to write to. */
  onAddStep?: (label: string, after: string | null) => Promise<void>
  onRemoveStep?: (step: ProcessStep) => Promise<void>
  /** Set in the overall view: the mandate ref opens that mandate's view. */
  onMandateClick?: () => void
  /** Rendered between the title and the stepper — the summary, per mandate.
   *  Above the stepper on purpose: a recruiter opening a mandate asks who
   *  this is before they ask which step is next. The overall list leaves it
   *  out, where the question is the opposite one. */
  summary?: ReactNode
  /** Rendered inside the card, under the stepper — the assessment, per job. */
  children?: ReactNode
}) {
  const [collapsed, setCollapsed] = useRemembered(
    `eligo.processCard.${card.id}.collapsed`,
    false,
  )
  // What a folded card still says: where the process stands.
  const current = card.steps.find((s) => s.state === 'current')

  return (
    <Panel tone="raised" className="px-7 py-6">
      <div className="flex flex-wrap items-start gap-x-5 gap-y-3">
        <ProgressRing figure={card.progress} />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            {/* The process says where the person stands; their record says
                who they are. The NAME is the way across — a bordered
                "Kandidatenakte" chip sat at the end of a long title and read
                as a tag, so the obvious thing to click was the only thing
                that did nothing. */}
            <h3 className="text-[19px] font-semibold text-cockpit-text">
              <span className="font-mono font-medium">{card.candidateRef}</span>
              <span className="text-cockpit-faint"> · </span>
              {card.candidateId ? (
                <a
                  href={`#kandidaten/${card.candidateId}`}
                  title={`${card.candidateName} — Kandidatenakte öffnen`}
                  className="underline decoration-cockpit-line decoration-1 underline-offset-[5px] transition-colors hover:text-mint-300 hover:decoration-mint-400"
                >
                  {card.candidateName}
                  <ExternalLink className="ml-1 inline h-3.5 w-3.5 align-[-1px] text-cockpit-faint" />
                </a>
              ) : (
                card.candidateName
              )}
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
            {collapsed && current && (
              <span className="text-cockpit-dim"> · bei „{current.label}“</span>
            )}
          </p>
        </div>

        <div className="shrink-0 text-right">
          {/* No Honorarmodell yet, so the fee is a demo zero. The design shows
              a real figure here; "€ 0" would read as a fee of nothing, which
              is a claim. An em dash says "not known" instead. */}
          {card.fee.value > 0 ? (
            <Money figure={card.fee} className="block text-[22px] text-mint-400" />
          ) : (
            <span
              className="block text-[22px] text-cockpit-faint"
              title="Kein Honorarmodell hinterlegt"
            >
              —
            </span>
          )}
          <span className="font-mono text-[12px] text-cockpit-faint">Fee-Potenzial</span>
        </div>

        <button
          type="button"
          onClick={() => setCollapsed((shut) => !shut)}
          aria-expanded={!collapsed}
          title={collapsed ? 'Prozess ausklappen' : 'Prozess einklappen'}
          className="-mr-1 shrink-0 self-start rounded-lg border border-cockpit-line p-1.5 text-cockpit-faint transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
          <span className="sr-only">
            {collapsed ? 'Prozess ausklappen' : 'Prozess einklappen'}
          </span>
        </button>
      </div>

      {!collapsed && (
        <>
          {summary}

          <div className="mt-6">
            <ProcessStepper
              steps={card.steps}
              onStepClick={onStepClick}
              onAddStep={onAddStep}
              onRemoveStep={onRemoveStep}
            />
          </div>

          {children}
        </>
      )}
    </Panel>
  )
}
