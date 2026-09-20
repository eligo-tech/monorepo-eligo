// "Workspace" — the funnel's second step: the employers this workspace
// watches, and the people their public ads name.
//
// Markt answers "who is hiring X near Y" across the shared corpus. Beobachten
// there lands the employer here, and this screen answers the next question:
// "who do I call?". A German job ad usually says — "Ihre Ansprechpartnerin:
// Frau Sophie Bennicke, Tel. …" — and that text is already in the corpus, so
// "Ansprechpartner finden" is a read over it. It fetches nothing (ARCHITECTURE.md
// RULE 1) and stores nothing: a person reaches this workspace's record only
// when a recruiter clicks "Übernehmen", which is where provenance and the
// GDPR Art. 14 notice attach.
//
// Every contact shows the ad line it was read from. The parser is regex, not
// judgement, and a recruiter should be able to see in one glance whether it
// read the ad right.

import { useState } from 'react'
import { Building2, MapPin, Search, Trash2, Users } from 'lucide-react'
import { api } from '@/api/client'
import type { WorkspaceCompanyDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import { Button } from '../ui/forms'
import { ContactsPanel, dateDe, de } from './ContactsPanel'


function WorkspaceCard({
  company,
  onRemoved,
}: {
  company: WorkspaceCompanyDTO
  onRemoved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [companyId, setCompanyId] = useState(company.company_id)
  const [removing, setRemoving] = useState(false)
  const adopted = companyId !== null

  const remove = async () => {
    setRemoving(true)
    try {
      await api.untrackHubCompany(company.hub_company_id)
      onRemoved()
    } finally {
      setRemoving(false)
    }
  }

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <h3 className="text-[16px] font-medium text-cockpit-text">{company.name}</h3>
        {company.website_domain && (
          <span className="font-mono text-[12px] text-cockpit-faint">{company.website_domain}</span>
        )}
        {adopted ? (
          <Chip tone="mint">Kunde</Chip>
        ) : (
          <Chip>{company.relationship === 'prospect' ? 'Prospect' : 'beobachtet'}</Chip>
        )}

        <span className="ml-auto flex items-center gap-4 font-mono text-[13px] text-cockpit-faint">
          {company.sites > 1 && (
            <span>
              <span className="text-cockpit-text">{de(company.sites)}</span> Standorte
            </span>
          )}
          <span title="Offene Rollen über alle Standorte">
            <span className="text-[15px] text-cockpit-text">{de(company.open_roles)}</span> Rollen
          </span>
          <span title="Jüngste offene Anzeige">{dateDe(company.last_posted_at)}</span>
          <Button tone={open ? 'primary' : 'ghost'} onClick={() => setOpen((o) => !o)}>
            <Users className="h-4 w-4" />
            Ansprechpartner finden
          </Button>
          {/* Removing an adopted company's link would orphan the adoption, so
              only a watched-but-not-adopted company can be dropped here. */}
          {!adopted && (
            <button
              type="button"
              onClick={remove}
              disabled={removing}
              aria-label={`${company.name} nicht mehr beobachten`}
              title="Nicht mehr beobachten"
              className="text-cockpit-faint transition-colors hover:text-coral-400"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </span>
      </div>

      <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[12px] text-cockpit-dim">
        <MapPin className="h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
        {company.cities.join(' · ') || '—'}
        {company.city_count > company.cities.length && (
          <span className="text-cockpit-faint">
            +{company.city_count - company.cities.length} weitere
          </span>
        )}
      </p>

      {open && (
        <div className="mt-3 border-t border-cockpit-line/60 pt-3">
          <ContactsPanel
            company={{ ...company, company_id: companyId }}
            onAdopted={setCompanyId}
          />
        </div>
      )}
    </Panel>
  )
}

export function WorkspaceScreen() {
  const [reloadKey, setReloadKey] = useState(0)
  const companies = useAsync<WorkspaceCompanyDTO[]>(() => api.hubWorkspace(), [reloadKey])
  const list = companies.data ?? []
  const roles = list.reduce((sum, c) => sum + c.open_roles, 0)

  return (
    <div className="space-y-8">
      <header id="section-workspace" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Workspace
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          Die Unternehmen, die Sie im Markt beobachten — und die Menschen, die ihre
          Anzeigen namentlich als Ansprechpartner nennen. Übernommene Kontakte
          bleiben in diesem Workspace.
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          index="01"
          title="Zielfirmen"
          hint={
            companies.data
              ? `${de(list.length)} Unternehmen · ${de(roles)} offene Rollen`
              : companies.error
                ? 'offline'
                : 'lädt…'
          }
        />

        {companies.error && (
          <Panel className="p-5">
            <p className="text-[14px] text-coral-400">
              Workspace konnte nicht geladen werden — {companies.error.message.slice(0, 200)}
            </p>
          </Panel>
        )}

        {companies.data && list.length === 0 && (
          <Panel className="p-6">
            <div className="flex items-start gap-3">
              <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
                <Building2 className="h-5 w-5" />
              </span>
              <div className="space-y-3">
                <p className="max-w-2xl text-[14px] leading-relaxed text-cockpit-dim">
                  Noch keine Unternehmen. Suchen Sie im Markt nach einer Rolle oder
                  einem Ort und klicken Sie bei passenden Arbeitgebern auf
                  „Beobachten“ — sie erscheinen dann hier.
                </p>
                <a
                  href="#markt"
                  className="inline-flex items-center gap-2 rounded-lg border border-mint-600 bg-mint-800/40 px-3 py-1.5 text-[13px] text-mint-300 transition-colors hover:bg-mint-800/70"
                >
                  <Search className="h-4 w-4" /> Zum Markt
                </a>
              </div>
            </div>
          </Panel>
        )}

        <div className="space-y-3">
          {list.map((company) => (
            <WorkspaceCard
              key={company.hub_company_id}
              company={company}
              onRemoved={() => setReloadKey((k) => k + 1)}
            />
          ))}
        </div>
      </section>
    </div>
  )
}
