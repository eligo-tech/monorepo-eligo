// "Zentrale Suche · Datenbank & Portale" and "Ansprache · Nachricht an
// Kandidaten", side by side as the design pairs them.
//
// Neither is connected. Searching portals is an outbound crawl, which
// ARCHITECTURE.md RULE 1 forbids from a user action — it belongs to a
// scheduled job — and the outreach agent is phase 5 and may only ever produce
// drafts a human approves. Both constraints are product decisions, not
// missing wiring, so the controls are drawn and disabled with the reason on
// hover rather than left to look broken.

import { useState } from 'react'
import { Search, Sparkles } from 'lucide-react'

import { cn } from '@/lib/cn'
import { Panel } from '../../ui/primitives'
import { Button } from '../../ui/forms'
import { DEMO_HINT, PanelHead } from './parts'
import type { Mandate } from '../../data/types'

const SOURCES = [
  { key: 'db', label: 'Eigene Datenbank', tone: 'bg-lav-400' },
  { key: 'li', label: 'LinkedIn', tone: 'bg-coral-400' },
  { key: 'xing', label: 'Xing', tone: 'bg-mint-400' },
  { key: 'aa', label: 'Arbeitsagentur', tone: 'bg-gold-400' },
  { key: 'step', label: 'Stepstone', tone: 'bg-lav-400' },
]

const CRAWL_REASON =
  'Portalsuche ist ein ausgehender Abruf — die laufen als geplanter Job, nie aus einem Klick (ARCHITECTURE.md Regel 1).'

export function SourcingPanel({ mandate }: { mandate: Mandate }) {
  const [active, setActive] = useState<string[]>(['db'])
  const [form, setForm] = useState<'Sie' | 'Du'>('Sie')

  const toggle = (key: string) =>
    setActive((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )

  const greeting = form === 'Sie' ? 'Sehr geehrte(r) [Name]' : 'Hallo [Vorname]'
  const verb = form === 'Sie' ? 'Ihr Profil' : 'dein Profil'
  const closing =
    form === 'Sie'
      ? 'Hätten Sie Interesse an einem kurzen Austausch?'
      : 'Hast du Lust auf einen kurzen Austausch?'

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel className="px-6 py-5">
        <PanelHead
          tag="Zentrale Suche"
          tone="lav"
          title="Datenbank & Portale"
          note={DEMO_HINT}
        />

        <div className="flex items-center gap-2.5 rounded-lg border border-cockpit-line bg-cockpit-inset px-3">
          <Search className="h-[15px] w-[15px] shrink-0 text-cockpit-faint" />
          <input
            disabled
            placeholder="Intelligente Suche über alle Quellen …"
            className="flex-1 bg-transparent py-2.5 text-[13px] text-cockpit-text placeholder:text-cockpit-faint focus:outline-none"
          />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {SOURCES.map((source) => (
            <button
              key={source.key}
              type="button"
              onClick={() => toggle(source.key)}
              className={cn(
                'flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[12.5px] transition-colors',
                active.includes(source.key)
                  ? 'border-cockpit-edge bg-white/[0.06] text-cockpit-text'
                  : 'border-cockpit-line text-cockpit-faint hover:text-cockpit-dim',
              )}
            >
              <span
                className={cn(
                  'h-2 w-2 rounded-full',
                  active.includes(source.key) ? source.tone : 'bg-cockpit-line',
                )}
              />
              {source.label}
            </button>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-[12.5px] text-cockpit-dim">
            <input type="checkbox" className="h-[15px] w-[15px] accent-[#e0897a]" />
            Nur eigene Datenbank
          </label>
          <Button tone="primary" disabled title={CRAWL_REASON}>
            Kandidaten suchen →
          </Button>
        </div>

        <p className="mt-3 border-t border-cockpit-line pt-3 text-[12px] text-cockpit-faint">
          {CRAWL_REASON}
        </p>
      </Panel>

      <Panel className="px-6 py-5">
        <PanelHead
          tag="Ansprache"
          tone="gold"
          title="Nachricht an Kandidaten"
          note={`${form}-Form · ${DEMO_HINT}`}
        />

        <div className="inline-flex gap-1 rounded-xl border border-cockpit-line bg-cockpit-inset p-1">
          {(['Sie', 'Du'] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setForm(option)}
              aria-pressed={form === option}
              className={cn(
                'rounded-lg px-4 py-1.5 text-[13px] transition-colors',
                form === option
                  ? 'bg-white/[0.07] text-cockpit-text'
                  : 'text-cockpit-dim hover:text-cockpit-text',
              )}
            >
              {option}
            </button>
          ))}
        </div>

        <p className="mt-3 rounded-xl border border-cockpit-line bg-cockpit-inset px-4 py-3 text-[13.5px] leading-relaxed text-cockpit-dim">
          {greeting}, ich bin auf {verb} aufmerksam geworden — für eine spannende Rolle
          als <span className="text-cockpit-text">{mandate.title}</span>
          {mandate.location ? ` (${mandate.location})` : ''} suche ich jemanden mit Ihrem
          Hintergrund. {closing}
        </p>

        <p className="mt-3 flex items-center gap-2 text-[12px] text-cockpit-faint">
          <Sparkles className="h-3.5 w-3.5 text-gold-400" />
          Entwurf aus dem Mandat zusammengesetzt — der Outreach-Agent (Phase 5)
          schreibt und lernt ihn später, und verschickt nie ohne Freigabe.
        </p>
      </Panel>
    </div>
  )
}
