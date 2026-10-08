// "Aktivität · Was haben wir für diesen Job getan?"
//
// The funnel a client asks about on the phone: how many did you approach, how
// many answered, how many were interested, how many did you present. Only the
// last number exists in the record today (a presented candidate has a process
// row); the rest come from an outreach log that does not exist yet — the
// outreach agent is phase 5 of the build order.
//
// So the shape is the design's and every number that is not counted carries
// its mark. The "noch nicht probiert" row is the useful half even as a demo:
// it names the channels nobody has tried for this search.

import { useRemembered } from '@/hooks/useRemembered'
import { Panel } from '../../ui/primitives'
import { DEMO_HINT, DemoText, PanelHead } from './parts'
import type { Mandate } from '../../data/types'

const CHANNELS = [
  { name: 'LinkedIn', sent: 48, resp: 14, pos: 5 },
  { name: 'Xing', sent: 22, resp: 6, pos: 2 },
  { name: 'Eigene Datenbank', sent: 9, resp: 6, pos: 4 },
  { name: 'Mail', sent: 5, resp: 2, pos: 1 },
]
const UNTRIED = ['Telefon', 'Arbeitsagentur', 'Stepstone']

function Step({
  value,
  label,
  demo,
}: {
  value: string
  label: string
  demo?: boolean
}) {
  return (
    <div className="min-w-[104px] rounded-xl border border-cockpit-line bg-cockpit-inset px-4 py-2.5 text-center">
      <div className="font-mono text-[22px] text-cockpit-text">
        {demo ? <DemoText source="Kein Outreach-Log — Zähler folgen aus Phase 5">{value}</DemoText> : value}
      </div>
      <div className="mt-0.5 text-[11.5px] text-cockpit-faint">{label}</div>
    </div>
  )
}

export function ActivityPanel({ mandate }: { mandate: Mandate }) {
  const [collapsed, setCollapsed] = useRemembered(
    'eligo.panel.aktivitaet.collapsed',
    false,
  )
  const sent = CHANNELS.reduce((n, c) => n + c.sent, 0)
  const answered = CHANNELS.reduce((n, c) => n + c.resp, 0)
  const interested = CHANNELS.reduce((n, c) => n + c.pos, 0)
  // The one real number on this panel: a card exists because someone was
  // actually presented.
  const presented = mandate.cards.length

  return (
    <Panel className="px-6 py-5">
      <PanelHead
        tag="Aktivität"
        tone="lav"
        title="Was haben wir für diesen Job getan?"
        note={DEMO_HINT}
        collapsed={collapsed}
        onToggle={() => setCollapsed((shut) => !shut)}
      />

      {collapsed ? null : (
        <>
        <div className="flex flex-wrap items-center gap-2">
          <Step value={String(sent)} label="Angesprochen" demo />
          <span className="text-cockpit-faint">›</span>
          <Step
            value={`${answered} · ${Math.round((answered / sent) * 100)}%`}
            label="Antworten"
            demo
          />
          <span className="text-cockpit-faint">›</span>
          <Step value={String(interested)} label="Interessiert" demo />
          <span className="text-cockpit-faint">›</span>
          <Step value={String(presented)} label="Vorgestellt" />
        </div>

        <div className="mt-5 space-y-2">
          {CHANNELS.map((channel) => {
            const rate = Math.round((channel.resp / channel.sent) * 100)
            return (
              <div
                key={channel.name}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]"
              >
                <span className="w-[140px] shrink-0 text-cockpit-text">{channel.name}</span>
                <span className="w-[110px] shrink-0 font-mono text-[11.5px] text-cockpit-faint">
                  {channel.sent} angesprochen
                </span>
                <span className="h-1.5 min-w-[80px] flex-1 overflow-hidden rounded-full bg-cockpit-line">
                  <span
                    className="block h-full rounded-full bg-lav-400/70"
                    style={{ width: `${Math.min(100, rate)}%` }}
                  />
                </span>
                <span className="w-[42px] shrink-0 text-right font-mono text-[11.5px] text-cockpit-dim">
                  {rate}%
                </span>
                <span className="w-[72px] shrink-0 text-right font-mono text-[11.5px] text-mint-400">
                  {channel.pos} positiv
                </span>
              </div>
            )
          })}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-[12px]">
          <span className="text-cockpit-faint">Noch nicht probiert:</span>
          {UNTRIED.map((channel) => (
            <span
              key={channel}
              className="rounded-md border border-gold-600/45 px-2.5 py-1 font-mono text-[11.5px] text-gold-300"
            >
              {channel} · starten
            </span>
          ))}
        </div>
        </>
      )}
    </Panel>
  )
}
