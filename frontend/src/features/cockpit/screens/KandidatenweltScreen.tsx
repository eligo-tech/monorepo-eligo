// "Kandidatenwelt · Profilvertrieb" — the candidate-out view.
//
// Starting from one candidate: who in our own database could hire them, and which
// vacancies exist for them on the open market. The right column is public job data
// only (GDPR Art. 14 / market-map scope), which is why every contact route there is
// "Daten generieren" — a draft for a human to approve, not an automatic send.

import { ArrowRight, Mail, Phone, User } from 'lucide-react'
import { LinkedInMark } from '@/components/ui/LinkedInMark'
import { Chip, Figure, Panel } from '../ui/primitives'
import type { ManagerLead, MarketRole, ProfileSaleData } from '../data/types'

export const KANDIDATENWELT_SECTIONS = ['section-subject', 'section-managers']

export function KandidatenweltScreen({ data }: { data: ProfileSaleData }) {
  const { subject, managers, market } = data

  return (
    <div className="space-y-8">
      <header id="section-subject" className="scroll-mt-24">
        <div className="flex items-start gap-5">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-coral-600 bg-coral-800/30 text-coral-400">
            <User className="h-6 w-6" />
          </span>
          <div>
            <p className="font-mono text-[13px] uppercase tracking-[0.16em] text-coral-400">
              Rechts · Ausgangspunkt Kandidat
            </p>
            <h1 className="mt-1.5 text-[42px] font-semibold leading-tight tracking-tight text-cockpit-text">
              Kandidatenwelt · Profilvertrieb
            </h1>
            <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
              Ausgehend vom Kandidaten: das System screent die eigene Datenbank nach
              passenden Managern und Jobs und findet konkrete offene Stellen am Markt —
              Vorstellung und Ansprache per Knopfdruck.
            </p>
          </div>
        </div>
      </header>

      {/* Subject card */}
      <Panel className="flex flex-wrap items-center gap-x-6 gap-y-4 px-7 py-5">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-coral-600 bg-coral-800/30 font-mono text-[15px] text-coral-300">
          {subject.badge}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-[21px] font-semibold text-cockpit-text">{subject.headline}</h2>
          <p className="mt-1 text-[15px] text-cockpit-dim">{subject.summary}</p>
        </div>
        <div className="shrink-0 text-right">
          <Figure figure={subject.optionCount} className="block text-[30px] text-mint-400" />
          <span className="font-mono text-[12px] text-cockpit-faint">Passende Optionen</span>
        </div>
      </Panel>

      <div id="section-managers" className="grid scroll-mt-24 gap-5 xl:grid-cols-2">
        <Column
          badge="In der Datenbank"
          badgeTone="mint"
          title="Passende Manager & offene Jobs"
          hint="Skill-Screening"
        >
          {managers.map((lead) => (
            <ManagerRow key={lead.id} lead={lead} />
          ))}
        </Column>

        <Column
          badge="Am Markt"
          badgeTone="gold"
          title="Passende offene Stellen"
          hint="extern · Job-Portale"
        >
          {market.map((role) => (
            <MarketRow key={role.id} role={role} />
          ))}
        </Column>
      </div>
    </div>
  )
}

function Column({
  badge,
  badgeTone,
  title,
  hint,
  children,
}: {
  badge: string
  badgeTone: 'mint' | 'gold'
  title: string
  hint: string
  children: React.ReactNode
}) {
  return (
    <Panel className="p-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span
          className={
            badgeTone === 'mint'
              ? 'rounded-md border border-mint-700 bg-mint-800/40 px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.1em] text-mint-400'
              : 'rounded-md border border-gold-600 bg-gold-800/40 px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.1em] text-gold-400'
          }
        >
          {badge}
        </span>
        <h3 className="text-[19px] font-semibold text-cockpit-text">{title}</h3>
        <span className="ml-auto font-mono text-[12px] text-cockpit-faint">{hint}</span>
      </div>

      <div className="mt-5 space-y-3">{children}</div>
    </Panel>
  )
}

function ManagerRow({ lead }: { lead: ManagerLead }) {
  return (
    <div className="rounded-2xl border border-cockpit-line bg-cockpit-raised px-5 py-4">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 text-[16px] text-cockpit-dim">
          <span className="font-semibold text-cockpit-text">{lead.person}</span> · {lead.role} ·{' '}
          {lead.company}
        </p>
        {/* Tone of address on file — the outreach agent must not guess it. */}
        <Chip tone={lead.address === 'Sie' ? 'mint' : 'gold'}>per {lead.address}</Chip>
      </div>

      <p className="mt-2 text-[15px] text-cockpit-dim">
        offen: <span className="font-semibold text-cockpit-text">{lead.openRole}</span>
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {lead.skills.map((skill) => (
          <Chip key={skill}>{skill}</Chip>
        ))}
        <span className="font-mono text-[13px] text-mint-400">
          <Figure figure={lead.match} suffix="%" /> Match
        </span>
        <button
          type="button"
          className="ml-auto flex items-center gap-2 rounded-lg border border-coral-600 bg-coral-800/20 px-4 py-2 text-[14px] text-coral-300 transition-colors hover:bg-coral-800/40"
        >
          Vorstellen <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

const CONTACT_ROUTES = [
  { key: 'phone', label: 'Telefon', caption: 'Daten generieren', Icon: Phone },
  { key: 'mail', label: 'Mail', caption: 'Daten generieren', Icon: Mail },
  { key: 'linkedin', label: 'LinkedIn', caption: 'Vernetzen / Nachricht', Icon: null },
] as const

function MarketRow({ role }: { role: MarketRole }) {
  return (
    <div className="rounded-2xl border border-cockpit-line bg-cockpit-raised px-5 py-4">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <p className="min-w-0 flex-1 text-[16px] text-cockpit-dim">
          <span className="font-semibold text-cockpit-text">{role.title}</span> · {role.company}
        </p>
        <Figure figure={role.match} suffix="%" className="text-[19px] text-mint-400" />
      </div>

      <p className="mt-1 text-[14px] text-cockpit-dim">
        {role.meta} · Quelle: {role.source}
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        {role.skills.map((skill) => (
          <Chip key={skill}>{skill}</Chip>
        ))}
      </div>

      {/* Drafts only — a human approves before anything leaves the building. */}
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {CONTACT_ROUTES.map(({ key, label, caption, Icon }) => (
          <button
            key={key}
            type="button"
            className="rounded-xl border border-cockpit-line bg-white/[0.02] px-3.5 py-2.5 text-left transition-colors hover:border-cockpit-edge"
          >
            <span className="flex items-center gap-2 text-[14px] font-semibold text-cockpit-text">
              {Icon ? <Icon className="h-[15px] w-[15px]" /> : <LinkedInMark />}
              {label}
            </span>
            <span className="mt-0.5 block font-mono text-[11px] text-cockpit-faint">
              {caption}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
