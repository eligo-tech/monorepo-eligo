// The nine-step placement stepper from "03 Laufende Prozesse".
//
// Node states carry meaning: filled mint = done, mint ring = the step we're
// waiting on, coral ring = blocked (a party still owes us something), dim = not
// reached. Sub-chips show which of the two parties has delivered.

import { useState } from 'react'
import { Check, Plus, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { ProcessStep } from '../data/types'

const NODE: Record<ProcessStep['state'], string> = {
  done: 'border-mint-500 bg-mint-500 text-[#0f1a12]',
  current: 'border-mint-600 bg-transparent text-transparent',
  blocked: 'border-coral-400 bg-transparent text-transparent shadow-glow-coral',
  // The tracker's red cell: filled coral, because the process ended here —
  // visibly different from "blocked", where it is merely stuck.
  out: 'border-coral-500 bg-coral-500 text-[#1a0f0f]',
  pending: 'border-[#25271f] bg-transparent text-transparent',
}

const LABEL: Record<ProcessStep['state'], string> = {
  done: 'text-cockpit-text',
  current: 'text-cockpit-text',
  blocked: 'text-cockpit-text',
  out: 'text-coral-400',
  pending: 'text-cockpit-faint',
}

export function ProcessStepper({
  steps,
  onStepClick,
  onAddStep,
  onRemoveStep,
}: {
  steps: ProcessStep[]
  /** The mockup's hint is "Schritte antippen" — steps are the interaction. */
  onStepClick?: (step: ProcessStep) => void
  /** Add a step after `after` (null = first). Absent on read-only cards. */
  onAddStep?: (label: string, after: string | null) => Promise<void>
  /** Take a step out of THIS process. */
  onRemoveStep?: (step: ProcessStep) => Promise<void>
}) {
  const editable = Boolean(onAddStep || onRemoveStep)
  return (
    <div className={cn('flex items-start gap-3', editable && 'group/stepper')}>
      {onAddStep && <AddStep steps={steps} onAdd={onAddStep} />}
      <ol
        className="grid flex-1 gap-x-1"
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

              {/* Removing is a rare, deliberate edit, so it stays out of the
                  way until the pipeline is hovered — and the server refuses
                  it for a step that already happened. */}
              {onRemoveStep && step.state !== 'done' && step.state !== 'out' && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    void onRemoveStep(step)
                  }}
                  title={`${step.label} aus diesem Prozess entfernen`}
                  aria-label={`${step.label} entfernen`}
                  className="absolute -top-0.5 right-1/2 z-20 translate-x-[18px] rounded-full border border-cockpit-line bg-cockpit-bg p-0.5 text-cockpit-faint opacity-0 transition-opacity hover:border-coral-400 hover:text-coral-400 group-hover/stepper:opacity-100"
                >
                  <X className="h-2.5 w-2.5" strokeWidth={3} />
                </button>
              )}
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
    </div>
  )
}

/**
 * "+ Schritt" — left of the pipeline, where the process begins.
 *
 * Chronology is a POSITION, not a date: a Probearbeitstag usually has no date
 * when it is agreed, and where it sits is what makes the next action
 * readable. So the form asks what, then after which step.
 */
function AddStep({
  steps,
  onAdd,
}: {
  steps: ProcessStep[]
  onAdd: (label: string, after: string | null) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [after, setAfter] = useState<string>(steps[0]?.key ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    const name = label.trim()
    if (!name || busy) return
    setBusy(true)
    setError(null)
    try {
      await onAdd(name, after || null)
      setLabel('')
      setOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 120) : 'nicht gespeichert')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Eigenen Schritt in diesen Prozess einfügen"
        className="mt-[7px] flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border-2 border-dashed border-[#2b2e25] text-cockpit-faint transition-colors hover:border-mint-600 hover:text-mint-400"
      >
        <Plus className="h-3.5 w-3.5" strokeWidth={3} />
      </button>
    )
  }

  return (
    <div className="w-60 shrink-0 space-y-2 rounded-lg border border-cockpit-line bg-cockpit-inset p-2.5">
      <input
        autoFocus
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void submit()
          if (e.key === 'Escape') setOpen(false)
        }}
        maxLength={60}
        placeholder="Schritt, z. B. Probearbeitstag"
        className="w-full rounded-md border border-cockpit-line bg-cockpit-bg px-2 py-1.5 text-[13px] text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none"
      />
      <label className="block font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
        danach
        <select
          value={after}
          onChange={(e) => setAfter(e.target.value)}
          className="mt-1 w-full rounded-md border border-cockpit-line bg-cockpit-bg px-2 py-1.5 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
        >
          <option value="">ganz am Anfang</option>
          {/* Numbered: the nine contain two steps called "Feedback", and a
              dropdown with the same word twice is a coin toss. */}
          {steps.map((s, i) => (
            <option key={s.key} value={s.key}>
              {i + 1}. {s.label}
            </option>
          ))}
        </select>
      </label>
      {error && <p className="text-[12px] text-coral-400">{error}</p>}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || !label.trim()}
          className="rounded-md border border-mint-600 bg-mint-800/40 px-2.5 py-1 text-[12px] text-mint-300 transition-colors hover:bg-mint-800/70 disabled:opacity-40"
        >
          {busy ? 'Fügt ein…' : 'Einfügen'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="font-mono text-[12px] text-cockpit-faint transition-colors hover:text-cockpit-text"
        >
          Abbrechen
        </button>
      </div>
    </div>
  )
}
