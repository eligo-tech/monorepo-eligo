// The nine-step placement stepper from "03 Laufende Prozesse".
//
// Node states carry meaning: filled mint = done, mint ring = the step we're
// waiting on, coral ring = blocked (a party still owes us something), dim = not
// reached. Sub-chips show which of the two parties has delivered.

import { Check } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { ProcessStep } from '../data/types'

const NODE: Record<ProcessStep['state'], string> = {
  done: 'border-mint-500 bg-mint-500 text-[#0f1a12]',
  current: 'border-mint-600 bg-transparent text-transparent',
  blocked: 'border-coral-400 bg-transparent text-transparent shadow-glow-coral',
  pending: 'border-[#25271f] bg-transparent text-transparent',
}

const LABEL: Record<ProcessStep['state'], string> = {
  done: 'text-cockpit-text',
  current: 'text-cockpit-text',
  blocked: 'text-cockpit-text',
  pending: 'text-cockpit-faint',
}

export function ProcessStepper({
  steps,
  onStepClick,
}: {
  steps: ProcessStep[]
  /** The mockup's hint is "Schritte antippen" — steps are the interaction. */
  onStepClick?: (step: ProcessStep) => void
}) {
  return (
    <ol
      className="grid gap-x-1"
      style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}
    >
      {steps.map((step, i) => {
        const prev = steps[i - 1]
        // A connector is lit only when the step behind it is complete.
        const leftLit = prev?.state === 'done'
        const rightLit = step.state === 'done'

        return (
          <li key={step.key} className="flex flex-col items-center">
            {/* Node row with its two connector halves */}
            <div className="relative flex h-11 w-full items-center justify-center">
              {i > 0 && (
                <span
                  className={cn(
                    'absolute left-0 top-1/2 h-px w-1/2 -translate-y-1/2',
                    leftLit ? 'bg-mint-600' : 'bg-[#22241d]',
                  )}
                />
              )}
              {i < steps.length - 1 && (
                <span
                  className={cn(
                    'absolute right-0 top-1/2 h-px w-1/2 -translate-y-1/2',
                    rightLit ? 'bg-mint-600' : 'bg-[#22241d]',
                  )}
                />
              )}
              <button
                type="button"
                onClick={() => onStepClick?.(step)}
                aria-label={`${step.label} — ${step.state}`}
                className={cn(
                  'relative z-10 flex h-[26px] w-[26px] items-center justify-center rounded-full border-2 transition-transform',
                  NODE[step.state],
                  onStepClick && 'hover:scale-110',
                )}
              >
                {step.state === 'done' && <Check className="h-3.5 w-3.5" strokeWidth={3} />}
              </button>
            </div>

            <span className={cn('text-center text-[13px] leading-tight', LABEL[step.state])}>
              {step.label}
            </span>

            {step.meta && (
              <span className="mt-1 whitespace-nowrap font-mono text-[11px] text-cockpit-faint">
                {step.meta}
              </span>
            )}

            {step.chips && (
              <div className="mt-1.5 flex flex-wrap justify-center gap-1">
                {step.chips.map((chip) => (
                  <span
                    key={chip.label}
                    className={cn(
                      'rounded border px-1.5 py-0.5 font-mono text-[11px] leading-4',
                      chip.done
                        ? 'border-mint-700 bg-mint-800/40 text-mint-400'
                        : 'border-[#25271f] bg-white/[0.02] text-cockpit-faint',
                    )}
                  >
                    {chip.label}
                  </span>
                ))}
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
