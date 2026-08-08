// "Erkannte Signale" — what the system read in the mailbox, calendar and notes
// since the last data run, each with the one action it proposes.
//
// Nothing here has touched the record: this is the propose half of "agents
// propose, verification commits". Übernehmen / Prüfen is the human gate.

import { Sparkles } from 'lucide-react'
import { Panel, WithRefs } from '../ui/primitives'
import type { SignalItem } from '../data/types'

export function SignalsPanel({
  signals,
  onAct,
}: {
  signals: SignalItem[]
  onAct?: (signal: SignalItem) => void
}) {
  if (signals.length === 0) return null

  return (
    <Panel className="p-6">
      <div className="flex items-center gap-3">
        <Sparkles className="h-[18px] w-[18px] text-mint-400" />
        <h3 className="text-[17px] font-semibold text-cockpit-text">Erkannte Signale</h3>
        <span className="ml-auto font-mono text-[13px] text-cockpit-faint">
          CRM · E-Mail &amp; Notizen
        </span>
      </div>

      <div className="mt-4 space-y-2.5">
        {signals.map((signal) => (
          <div
            key={signal.id}
            className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border border-cockpit-line bg-cockpit-raised px-4 py-3"
          >
            <span className="shrink-0 rounded-md border border-cockpit-line bg-white/[0.03] px-2.5 py-1 font-mono text-[12px] text-cockpit-dim">
              {signal.label}
            </span>

            <WithRefs
              text={signal.text}
              className="min-w-[16rem] flex-1 text-[15px] text-cockpit-dim"
            />

            <button
              type="button"
              onClick={() => onAct?.(signal)}
              className="shrink-0 rounded-lg border border-mint-700 px-4 py-2 text-[14px] text-mint-400 transition-colors hover:border-mint-600 hover:bg-mint-800/30"
            >
              {signal.action}
            </button>
          </div>
        ))}
      </div>
    </Panel>
  )
}
