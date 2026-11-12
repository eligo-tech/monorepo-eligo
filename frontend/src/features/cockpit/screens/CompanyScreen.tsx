// "Unternehmen" (ELI-33): every company of this workspace — clients from the
// import and companies whose contacts were taken from Markt — filtered by
// Alle / Kunden / Leads, and one page per company (`#companies/<id>`) with its
// managers, leads, mandates and the switchboard from its Impressum. A manager
// can be added right there; names link to the manager (`#managers/<id>`).

import { t } from '@/i18n'
import { locale } from '@/i18n/format'

import { useMemo, useState } from 'react'
import { ArrowLeft, Briefcase, Building2, Mail, MapPin, Newspaper, Phone, Plus, Search, UserRound, Users } from 'lucide-react'
import { api } from '@/api/client'
import type { CompanyOverviewRowDTO, CompanyPersonDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { ReaddDeclined, withReaddConfirm } from '../erasure/readd'
import { Button, FIELD } from '../ui/forms'
import { Chip, Panel, SectionHeader, SegmentedControl } from '../ui/primitives'
import { type CompanyKind, filterCompanies, kindCounts } from '../ui/companyList'
import { JOB_STATUS_TONE, jobStatus, jobStatusLabel } from '../ui/jobStatus'
import { telHref } from '../ui/switchboard'
import { SwitchboardLine } from '../ui/SwitchboardLine'
import { CareersLink, OpenJobs } from '../ui/OpenJobsList'

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(locale(), { day: '2-digit', month: '2-digit', year: 'numeric' }) : null

export function CompanyScreen({
  companyId,
  onSelect,
}: {
  companyId: string | null
  onSelect: (id: string | null) => void
}) {
  return companyId ? (
    <CompanyPage companyId={companyId} onBack={() => onSelect(null)} />
  ) : (
    <CompanyList onOpen={onSelect} />
  )
}

function CompanyList({ onOpen }: { onOpen: (id: string) => void }) {
  const rows = useAsync<CompanyOverviewRowDTO[]>(() => api.companiesOverview(), [])
  const [kind, setKind] = useState<CompanyKind>('all')
  const [q, setQ] = useState('')
  const all = rows.data ?? []
  const counts = kindCounts(all)
  const shown = useMemo(() => filterCompanies(all, kind, q), [all, kind, q])

  return (
    <div className="space-y-5">
      <SectionHeader
        title={t('Unternehmen')}
        hint={t('Alle Unternehmen dieses Workspaces — Kunden mit Managern und Unternehmen mit neuen Leads aus dem Markt.')}
        icon={<Building2 className="h-4 w-4" />}
      />
      <Panel className="p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <SegmentedControl
            size="sm"
            value={kind}
            onChange={setKind}
            options={[
              { key: 'all', label: t('Alle ({n})', { n: String(counts.all) }) },
              { key: 'clients', label: t('Kunden ({n})', { n: String(counts.clients) }) },
              { key: 'leads', label: t('Leads ({n})', { n: String(counts.leads) }) },
            ]}
          />
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-cockpit-faint" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('Unternehmen oder Ort')}
              className={cn(FIELD, 'pl-8')}
            />
          </div>
        </div>
        {rows.error && <p className="text-[13px] text-coral-400">{t('Unternehmen konnten nicht geladen werden.')}</p>}
        {rows.loading && !rows.data && <p className="text-[13px] text-cockpit-faint">{t('lädt…')}</p>}
        {rows.data && shown.length === 0 && (
          <p className="text-[13px] text-cockpit-dim">{t('Kein Unternehmen passt zu dieser Auswahl.')}</p>
        )}
        <ul>
          {shown.map((c) => (
            <li key={c.id} className="border-b border-cockpit-line/60 last:border-0">
              <button
                type="button"
                onClick={() => onOpen(c.id)}
                className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-left hover:bg-white/[0.02]"
              >
                <span className="flex min-w-0 flex-1 items-center gap-2 text-[14px] font-medium text-cockpit-text">
                  <Building2 className="h-4 w-4 shrink-0 text-cockpit-faint" />
                  <span className="truncate">{c.name}</span>
                  {c.location && <span className="truncate text-[13px] font-normal text-cockpit-faint">{c.location}</span>}
                </span>
                <span className="flex items-center gap-3 font-mono text-[12px] text-cockpit-dim">
                  {c.managers > 0 && <span>{t('{n} Manager', { n: String(c.managers) })}</span>}
                  {c.leads > 0 && <Chip tone="gold">{t('{n} Leads', { n: String(c.leads) })}</Chip>}
                  {c.mandates > 0 && <span>{t('{n} Mandate', { n: String(c.mandates) })}</span>}
                  {c.last_contact_at && (
                    <span className="text-cockpit-faint">{t('zuletzt {date}', { date: day(c.last_contact_at) ?? '' })}</span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}

function PersonRow({ person, href }: { person: CompanyPersonDTO; href: string }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-cockpit-line/60 py-2 last:border-0">
      <a href={href} className="min-w-0 flex-1 text-[14px] text-cockpit-text hover:text-mint-400">
        {person.full_name}
        {person.role_title && <span className="ml-2 text-[13px] text-cockpit-faint">{person.role_title}</span>}
      </a>
      <span className="flex flex-wrap items-center gap-3 font-mono text-[12px] text-cockpit-dim">
        {person.phone && (
          <a href={telHref(person.phone)} className="flex items-center gap-1 hover:text-mint-400">
            <Phone className="h-3.5 w-3.5 text-cockpit-faint" />
            {person.phone}
          </a>
        )}
        {person.email && (
          <a href={`mailto:${person.email}`} className="flex items-center gap-1 hover:text-mint-400">
            <Mail className="h-3.5 w-3.5 text-cockpit-faint" />
            {person.email}
          </a>
        )}
        {person.last_contact_at && (
          <span className="text-cockpit-faint">{t('zuletzt {date}', { date: day(person.last_contact_at) ?? '' })}</span>
        )}
      </span>
    </li>
  )
}

function CompanyPage({ companyId, onBack }: { companyId: string; onBack: () => void }) {
  const [bump, setBump] = useState(0)
  const page = useAsync(() => api.companyPage(companyId), [companyId, bump])
  const data = page.data

  return (
    <div className="space-y-5">
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint hover:text-cockpit-text"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t('Unternehmen')}
      </button>
      {page.error && <p className="text-[13px] text-coral-400">{t('Unternehmen konnte nicht geladen werden.')}</p>}
      {data && (
        <>
          <header>
            <h1 className="text-[36px] font-semibold leading-tight tracking-tight text-cockpit-text">{data.company.name}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 text-[14px] text-cockpit-dim">
              {data.company.location && (
                <span className="flex items-center gap-1">
                  <MapPin className="h-3.5 w-3.5 text-cockpit-faint" />
                  {data.company.location}
                </span>
              )}
              {data.company.industry && <span>{data.company.industry}</span>}
              <CareersLink market={data.market} />
            </p>
            {data.switchboard && (
              <div className="mt-2">
                <SwitchboardLine board={data.switchboard} />
              </div>
            )}
          </header>

          <Panel className="p-4">
            <SectionHeader
              title={t('Offene Stellen im Markt')}
              hint={data.market.linked ? String(data.market.total) : undefined}
              icon={<Newspaper className="h-4 w-4" />}
            />
            <div className="mt-2">
              <OpenJobs market={data.market} />
            </div>
          </Panel>

          <Panel className="p-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <SectionHeader title={t('Manager')} hint={String(data.managers.length)} icon={<UserRound className="h-4 w-4" />} />
            </div>
            {data.managers.length === 0 && (
              <p className="text-[13px] text-cockpit-dim">{t('Noch kein Manager bei diesem Unternehmen.')}</p>
            )}
            <ul>
              {data.managers.map((m) => (
                <PersonRow key={m.id} person={m} href={`#managers/${m.id}`} />
              ))}
            </ul>
            <AddManager companyId={data.company.id} companyName={data.company.name} onAdded={() => setBump((b) => b + 1)} />
          </Panel>

          {data.leads.length > 0 && (
            <Panel className="p-4">
              <SectionHeader
                title={t('Leads')}
                hint={t('Neue Kontakte aus dem Markt — in den Leads anrufen und „Zu Managern“ übernehmen.')}
                icon={<Users className="h-4 w-4" />}
              />
              <ul className="mt-2">
                {data.leads.map((m) => (
                  <PersonRow key={m.id} person={m} href="#leads" />
                ))}
              </ul>
            </Panel>
          )}

          <Panel className="p-4">
            <SectionHeader title={t('Mandate')} hint={String(data.mandates.length)} icon={<Briefcase className="h-4 w-4" />} />
            {data.mandates.length === 0 ? (
              <p className="mt-2 text-[13px] text-cockpit-dim">{t('Keine Mandate bei diesem Unternehmen.')}</p>
            ) : (
              <ul className="mt-2">
                {data.mandates.map((j) => (
                  <li key={j.id} className="flex items-center gap-3 border-b border-cockpit-line/60 py-2 last:border-0">
                    <a href={`#cockpit/${j.id}`} className="flex-1 text-[14px] text-cockpit-text hover:text-mint-400">
                      {j.title}
                    </a>
                    {j.location && <span className="text-[13px] text-cockpit-faint">{j.location}</span>}
                    <Chip tone={JOB_STATUS_TONE[jobStatus(j.status)]}>{jobStatusLabel(jobStatus(j.status))}</Chip>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </>
      )}
    </div>
  )
}

function AddManager({
  companyId,
  companyName,
  onAdded,
}: {
  companyId: string
  companyName: string
  onAdded: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [role, setRole] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open)
    return (
      <div className="mt-3">
        <Button onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" />
          {t('Manager hinzufügen')}
        </Button>
      </div>
    )

  async function save() {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await withReaddConfirm((override) =>
        api.createManager({
          override_suppression: override || undefined,
          company_id: companyId,
          full_name: name.trim(),
          role_title: role.trim() || null,
          email: email.trim() || null,
          phone: phone.trim() || null,
          source: 'self_reported',
          source_detail: t('Bei {company} von Hand erfasst', { company: companyName }),
        }),
      )
      setName('')
      setRole('')
      setEmail('')
      setPhone('')
      setOpen(false)
      onAdded()
    } catch (e) {
      setError(e instanceof ReaddDeclined ? e.message : t('Nicht gespeichert — bitte erneut versuchen.'))
    }
    setBusy(false)
  }

  return (
    <form
      className="mt-3 grid gap-2 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      <input className={FIELD} placeholder={t('Name *')} value={name} onChange={(e) => setName(e.target.value)} required />
      <input className={FIELD} placeholder={t('Rolle')} value={role} onChange={(e) => setRole(e.target.value)} />
      <input className={FIELD} type="email" placeholder={t('E-Mail')} value={email} onChange={(e) => setEmail(e.target.value)} />
      <input className={FIELD} placeholder={t('Telefon')} value={phone} onChange={(e) => setPhone(e.target.value)} />
      <div className="flex items-center gap-2 sm:col-span-2">
        <Button type="submit" tone="primary" disabled={busy || !name.trim()}>
          {t('Speichern')}
        </Button>
        <Button onClick={() => setOpen(false)}>{t('Abbrechen')}</Button>
        {error && <span className="text-[13px] text-coral-400">{error}</span>}
      </div>
    </form>
  )
}
