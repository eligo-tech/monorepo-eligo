// "Projekte" — the recruiter's own named groupings of target companies.
//
// Markt answers "who is hiring X near Y". Beobachten keeps an employer. This
// screen is where forty interesting companies become a piece of work with a
// name and a boundary: "TypeScript Berlin Q4", "Pflege Rhein-Main".
//
// The shortlist, and the enrichment step on it: every company should end up
// with a contact person, and the screen's job is to show which ones do not.
// A contact comes either out of the company's own ads ("Anreichern") or from
// the recruiter, who found one somewhere the ads do not reach — today a
// LinkedIn profile they looked up, later a data provider.
//
// A project stores a NAME and a set of corpus companies — nothing else, and
// nothing copied. Sites, open roles and contacts are read back through that
// membership, so a project can never show a number the corpus and the record
// would disagree with. Deleting one removes the grouping and neither the
// companies (they are the shared corpus's) nor the contacts (they are this
// workspace's own).

import { useCallback, useState } from 'react'
import {
  ArrowLeft,
  Building2,
  Check,
  FolderPlus,
  Mail,
  MapPin,
  Phone,
  Plus,
  Search,
  Sparkles,
  Trash2,
  UserPlus,
} from 'lucide-react'
import { ApiError, api } from '@/api/client'
import type {
  ProjectCandidateDTO,
  ProjectCompanyDTO,
  ProjectContactDTO,
  ProjectDTO,
  ProjectDetailDTO,
} from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import { Button, FIELD } from '../ui/forms'
import { ContactsPanel, dateDe, de } from './ContactsPanel'

/** Create a project. A name is the whole form — everything else is optional
 *  later, and asking for it up front would stop the thought. */
function NewProject({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    const value = name.trim()
    if (!value) return
    setBusy(true)
    setError(null)
    try {
      await api.createProject(value)
      setName('')
      onCreated()
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? 'Ein Projekt mit diesem Namen gibt es schon.'
          : 'Projekt konnte nicht angelegt werden.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="Projektname — z. B. TypeScript Berlin Q4"
          className={cn(FIELD, 'min-w-[20rem] flex-1 py-2.5 text-[15px]')}
        />
        <Button tone="primary" onClick={submit} disabled={busy || !name.trim()}>
          <FolderPlus className="h-4 w-4" />
          {busy ? 'Legt an…' : 'Projekt anlegen'}
        </Button>
      </div>
      {error && <p className="text-[13px] text-coral-400">{error}</p>}
    </div>
  )
}

function ProjectCard({
  project,
  onOpen,
  onChanged,
}: {
  project: ProjectDTO
  onOpen: () => void
  onChanged: () => void
}) {
  const [confirming, setConfirming] = useState(false)

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <button
          type="button"
          onClick={onOpen}
          className="text-left text-[16px] font-medium text-cockpit-text transition-colors hover:text-mint-400"
        >
          {project.name}
        </button>
        {project.company_count > 0 && project.companies_with_contact === project.company_count && (
          <Chip tone="mint">
            <span title="Für jede Firma im Projekt ist ein Ansprechpartner hinterlegt">
              vollständig
            </span>
          </Chip>
        )}

        <span className="ml-auto flex items-center gap-4 font-mono text-[13px] text-cockpit-faint">
          <span>
            <span className="text-cockpit-text">{de(project.company_count)}</span> Firmen
          </span>
          <span title="Firmen mit mindestens einem Ansprechpartner in diesem Workspace">
            <span className="text-cockpit-text">{de(project.companies_with_contact)}</span> mit
            Kontakt
          </span>
          <span>
            <span className="text-cockpit-text">{de(project.open_roles)}</span> Rollen
          </span>
          <span title="Angelegt">{dateDe(project.created_at)}</span>
          <Button onClick={onOpen}>Öffnen</Button>
          {/* Two clicks, because a project is work someone organised — but no
              dialog, because deleting one removes only the grouping. */}
          {confirming ? (
            <button
              type="button"
              onClick={async () => {
                await api.deleteProject(project.id).catch(() => {})
                onChanged()
              }}
              className="font-mono text-[12px] text-coral-400 hover:text-coral-300"
            >
              wirklich löschen?
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              aria-label={`${project.name} löschen`}
              title="Projekt löschen — Firmen und Kontakte bleiben"
              className="text-cockpit-faint transition-colors hover:text-coral-400"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </span>
      </div>
      {project.note && <p className="mt-1.5 text-[13px] text-cockpit-dim">{project.note}</p>}
    </Panel>
  )
}

/** Watched employers not yet in this project. Opens on demand: it is a picker,
 *  not part of reading the project. */
function AddCompanies({
  projectId,
  onAdded,
}: {
  projectId: string
  onAdded: (detail: ProjectDetailDTO) => void
}) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const candidates = useAsync<ProjectCandidateDTO[]>(
    () => (open ? api.projectCandidates(projectId) : Promise.resolve([])),
    [projectId, open],
  )

  const add = async () => {
    if (picked.length === 0) return
    setBusy(true)
    try {
      onAdded(await api.addProjectCompanies(projectId, picked))
      setPicked([])
      setOpen(false)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" />
        Firmen hinzufügen
      </Button>
    )
  }

  const list = candidates.data ?? []
  return (
    <Panel tone="inset" className="w-full space-y-2 p-3">
      <div className="flex items-center gap-3">
        <span className="font-mono text-[12px] uppercase tracking-[0.12em] text-cockpit-faint">
          Beobachtete Firmen
        </span>
        <Button className="ml-auto" onClick={() => setOpen(false)}>
          Abbrechen
        </Button>
        <Button tone="primary" onClick={add} disabled={busy || picked.length === 0}>
          {busy ? 'Fügt hinzu…' : `${picked.length} hinzufügen`}
        </Button>
      </div>

      {candidates.loading && (
        <p className="font-mono text-[12px] text-cockpit-faint">lädt…</p>
      )}
      {!candidates.loading && list.length === 0 && (
        <p className="max-w-2xl text-[13px] leading-relaxed text-cockpit-dim">
          Keine weiteren beobachteten Firmen. Im Markt suchen und dort
          „Beobachten“ klicken — die Firmen erscheinen dann hier.
        </p>
      )}

      <ul className="max-h-72 space-y-1 overflow-y-auto">
        {list.map((candidate) => {
          const on = picked.includes(candidate.hub_company_id)
          return (
            <li key={candidate.hub_company_id}>
              <button
                type="button"
                onClick={() =>
                  setPicked((prev) =>
                    on
                      ? prev.filter((id) => id !== candidate.hub_company_id)
                      : [...prev, candidate.hub_company_id],
                  )
                }
                className={cn(
                  'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-white/[0.04]',
                  on ? 'text-cockpit-text' : 'text-cockpit-dim',
                )}
              >
                <Check
                  className={cn('h-3.5 w-3.5 shrink-0', on ? 'text-mint-400' : 'text-transparent')}
                />
                <span className="truncate text-[14px]">{candidate.name}</span>
                <span className="ml-auto shrink-0 font-mono text-[12px] text-cockpit-faint">
                  {candidate.cities.join(' · ')} · {de(candidate.open_roles)} Rollen
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

/** One attached person. The source is visible because it decides the GDPR
 *  obligation, and a contact with an outstanding notice must not look done. */
function ContactLine({ contact }: { contact: ProjectContactDTO }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1">
      <span className="text-[14px] text-cockpit-text">{contact.full_name}</span>
      {contact.role_title && (
        <span className="text-[13px] text-cockpit-dim">{contact.role_title}</span>
      )}
      <span className="flex flex-wrap items-center gap-3 font-mono text-[12px] text-cockpit-dim">
        {contact.phone && (
          <a
            href={`tel:${contact.phone.replace(/[^\d+]/g, '')}`}
            className="flex items-center gap-1 hover:text-mint-400"
          >
            <Phone className="h-3.5 w-3.5 text-cockpit-faint" />
            {contact.phone}
          </a>
        )}
        {contact.email && (
          <a href={`mailto:${contact.email}`} className="flex items-center gap-1 hover:text-mint-400">
            <Mail className="h-3.5 w-3.5 text-cockpit-faint" />
            {contact.email}
          </a>
        )}
        {contact.linkedin_url && (
          <a
            href={contact.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-mint-400"
          >
            LinkedIn
          </a>
        )}
      </span>
      {contact.art14_outstanding && (
        <Chip tone="gold" className="ml-auto cursor-help">
          <span title="Nicht vom Betroffenen selbst erhalten — die Information nach Art. 14 DSGVO ist fällig und unter „Manager“ vorgemerkt">
            Art. 14 offen
          </span>
        </Chip>
      )}
    </li>
  )
}

/** Add a person the ads do not name — looked up on LinkedIn, found on a career
 *  page, or already known. A NAME is the whole requirement. */
function AddContact({
  projectId,
  company,
  onAdded,
}: {
  projectId: string
  company: ProjectCompanyDTO
  onAdded: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [role, setRole] = useState('')
  const [self, setSelf] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    const value = name.trim()
    if (!value) return
    setBusy(true)
    setError(null)
    try {
      await api.addProjectContact(projectId, company.hub_company_id, {
        full_name: value,
        role_title: role.trim() || null,
        source: self ? 'self_reported' : 'public_web',
      })
      setName('')
      setRole('')
      setOpen(false)
      onAdded()
    } catch {
      setError('Kontakt konnte nicht gespeichert werden.')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)}>
        <UserPlus className="h-4 w-4" />
        Person hinzufügen
      </Button>
    )
  }

  return (
    <div className="w-full space-y-2 rounded-xl border border-cockpit-line bg-cockpit-inset p-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="Name — z. B. Corina Freund"
          className={cn(FIELD, 'min-w-[16rem] flex-1')}
        />
        <input
          value={role}
          onChange={(e) => setRole(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="Rolle (optional)"
          className={cn(FIELD, 'w-56')}
        />
        <Button onClick={() => setOpen(false)}>Abbrechen</Button>
        <Button tone="primary" onClick={submit} disabled={busy || !name.trim()}>
          {busy ? 'Speichert…' : 'Speichern'}
        </Button>
      </div>
      {/* The only field with legal weight: data we found ourselves owes an
          Art. 14 notice, data the person gave us does not. */}
      <label className="flex items-center gap-2 text-[12px] text-cockpit-dim">
        <input type="checkbox" checked={self} onChange={(e) => setSelf(e.target.checked)} />
        Die Person hat mir diese Daten selbst gegeben (sonst: öffentlich gefunden,
        Art.-14-Information wird fällig)
      </label>
      {error && <p className="text-[12px] text-coral-400">{error}</p>}
    </div>
  )
}

function CompanyRow({
  projectId,
  company,
  onRemove,
  onChanged,
}: {
  projectId: string
  company: ProjectCompanyDTO
  onRemove: () => void
  onChanged: () => void
}) {
  const [showContacts, setShowContacts] = useState(false)
  const [companyId, setCompanyId] = useState(company.company_id)

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <h3 className="text-[16px] font-medium text-cockpit-text">{company.name}</h3>
        {company.website_domain && (
          <span className="font-mono text-[12px] text-cockpit-faint">
            {company.website_domain}
          </span>
        )}
        {company.contact_count > 0 ? (
          <Chip tone="mint">
            {de(company.contact_count)} Ansprechpartner
          </Chip>
        ) : (
          <Chip tone="gold">
            <span title="Noch niemand hinterlegt — anreichern oder Person hinzufügen">
              kein Kontakt
            </span>
          </Chip>
        )}

        <span className="ml-auto flex items-center gap-4 font-mono text-[13px] text-cockpit-faint">
          {company.sites > 1 && (
            <span>
              <span className="text-cockpit-text">{de(company.sites)}</span> Standorte
            </span>
          )}
          <span>
            <span className="text-[15px] text-cockpit-text">{de(company.open_roles)}</span> Rollen
          </span>
          <span title="Jüngste offene Anzeige">{dateDe(company.last_posted_at)}</span>
          {/* Enrichment from the company's own ads: the contact the employer
              published, with the ad line as evidence. */}
          <Button
            tone={showContacts ? 'primary' : 'ghost'}
            onClick={() => setShowContacts((v) => !v)}
            title="Ansprechpartner aus den Anzeigen dieser Firma lesen"
          >
            <Sparkles className="h-4 w-4" />
            Anreichern
          </Button>
          <button
            type="button"
            onClick={onRemove}
            aria-label={`${company.name} aus dem Projekt entfernen`}
            title="Aus dem Projekt entfernen — die Firma und ihre Kontakte bleiben"
            className="text-cockpit-faint transition-colors hover:text-coral-400"
          >
            <Trash2 className="h-4 w-4" />
          </button>
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

      {/* The shortlist answer: who do I have at this company? */}
      <div className="mt-2 flex flex-wrap items-start gap-3 border-t border-cockpit-line/40 pt-2">
        {company.contacts.length > 0 ? (
          <ul className="min-w-[18rem] flex-1">
            {company.contacts.map((contact) => (
              <ContactLine key={contact.id} contact={contact} />
            ))}
          </ul>
        ) : (
          <p className="min-w-[18rem] flex-1 py-1 text-[13px] text-cockpit-dim">
            Noch kein Ansprechpartner. „Anreichern“ liest die Anzeigen dieser
            Firma; wen sie nicht nennen, tragen Sie selbst ein.
          </p>
        )}
        <AddContact projectId={projectId} company={company} onAdded={onChanged} />
      </div>

      {showContacts && (
        <div className="mt-3 border-t border-cockpit-line/60 pt-3">
          <ContactsPanel
            company={{ hub_company_id: company.hub_company_id, company_id: companyId }}
            onAdopted={(id) => {
              setCompanyId(id)
              onChanged()
            }}
          />
        </div>
      )}
    </Panel>
  )
}

function ProjectDetail({ projectId, onBack }: { projectId: string; onBack: () => void }) {
  const [reloadKey, setReloadKey] = useState(0)
  const [override, setOverride] = useState<ProjectDetailDTO | null>(null)
  const loaded = useAsync<ProjectDetailDTO>(() => api.project(projectId), [projectId, reloadKey])
  const detail = override ?? loaded.data
  const reload = useCallback(() => {
    setOverride(null)
    setReloadKey((k) => k + 1)
  }, [])

  if (loaded.loading && !detail) {
    return <p className="font-mono text-[13px] text-cockpit-faint">lädt Projekt…</p>
  }
  if (loaded.error || !detail) {
    return (
      <Panel className="p-5">
        <p className="text-[14px] text-coral-400">
          Projekt konnte nicht geladen werden
          {loaded.error ? ` — ${loaded.error.message.slice(0, 200)}` : ''}
        </p>
      </Panel>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Alle Projekte
        </Button>
        <h2 className="text-[22px] font-semibold text-cockpit-text">{detail.name}</h2>
        <span className="font-mono text-[13px] text-cockpit-faint">
          {de(detail.company_count)} Firmen · {de(detail.companies_with_contact)} mit Kontakt
          {detail.company_count > detail.companies_with_contact && (
            <span className="text-gold-400">
              {' '}
              · {de(detail.company_count - detail.companies_with_contact)} offen
            </span>
          )}{' '}
          · {de(detail.open_roles)} offene Rollen
        </span>
        <span className="ml-auto">
          <AddCompanies projectId={projectId} onAdded={setOverride} />
        </span>
      </div>

      {detail.companies.length === 0 ? (
        <Panel className="p-6">
          <div className="flex items-start gap-3">
            <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
              <Building2 className="h-5 w-5" />
            </span>
            <p className="max-w-2xl text-[14px] leading-relaxed text-cockpit-dim">
              Noch keine Firmen in diesem Projekt. „Firmen hinzufügen“ bietet
              alles an, was Sie im Markt beobachten.
            </p>
          </div>
        </Panel>
      ) : (
        <div className="space-y-3">
          {detail.companies.map((company) => (
            <CompanyRow
              key={company.hub_company_id}
              projectId={projectId}
              company={company}
              onChanged={reload}
              onRemove={async () => {
                await api.removeProjectCompany(projectId, company.hub_company_id).catch(() => {})
                reload()
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function ProjekteScreen() {
  const [reloadKey, setReloadKey] = useState(0)
  const [openId, setOpenId] = useState<string | null>(null)
  const projects = useAsync<ProjectDTO[]>(() => api.projects(), [reloadKey])
  const list = projects.data ?? []

  return (
    <div className="space-y-8">
      <header id="section-projekte" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Projekte
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          Ihre Zielfirmen, gruppiert unter einem Namen. Ein Projekt hält die
          Firmen aus dem Markt zusammen und zeigt, für welche davon schon ein
          Ansprechpartner hinterlegt ist.
        </p>
      </header>

      <section className="space-y-5">
        {openId ? (
          <ProjectDetail
            projectId={openId}
            onBack={() => {
              setOpenId(null)
              setReloadKey((k) => k + 1)
            }}
          />
        ) : (
          <>
            <SectionHeader
              index="01"
              title="Projekte"
              hint={
                projects.data
                  ? `${de(list.length)} ${list.length === 1 ? 'Projekt' : 'Projekte'}`
                  : projects.error
                    ? 'offline'
                    : 'lädt…'
              }
            />

            <NewProject onCreated={() => setReloadKey((k) => k + 1)} />

            {projects.error && (
              <Panel className="p-5">
                <p className="text-[14px] text-coral-400">
                  Projekte konnten nicht geladen werden — {projects.error.message.slice(0, 200)}
                </p>
              </Panel>
            )}

            {projects.data && list.length === 0 && (
              <Panel className="p-6">
                <div className="flex items-start gap-3">
                  <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
                    <Search className="h-5 w-5" />
                  </span>
                  <p className="max-w-2xl text-[14px] leading-relaxed text-cockpit-dim">
                    Noch kein Projekt. Geben Sie oben einen Namen ein — danach
                    können Sie die Firmen hinzufügen, die Sie im Markt
                    beobachten.
                  </p>
                </div>
              </Panel>
            )}

            <div className="space-y-3">
              {list.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onOpen={() => setOpenId(project.id)}
                  onChanged={() => setReloadKey((k) => k + 1)}
                />
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  )
}
