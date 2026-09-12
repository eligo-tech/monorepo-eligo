// "Manager" — the client-side contact people. Live from /managers.
//
// A Manager is the person at a client company a mandate actually belongs to:
// Firma → Manager → Job. Companies do not hire, people do, and the relationship
// that wins the next mandate is with a person rather than a legal entity.
//
// It is deliberately NOT part of the shared market corpus — see ARCHITECTURE.md
// RULE 2. A manager is a natural person, so a shared table holding one would
// make a single erasure request reach across every workspace. Contacts stay
// tenant-scoped, carry provenance, and route through the GDPR Art. 14 flow when
// they come from a public source.
//
// That provenance is the reason this screen leads with an obligation counter
// rather than a headcount: "how many people do I hold data on who have not been
// told" is the question with a deadline attached.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Building2, Check, Mail, Phone, Search, ShieldAlert, UserRound } from 'lucide-react'
import { api } from '@/api/client'
import type { CompanyDTO, ManagerDTO, ManagerInteractionDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { Panel, SectionHeader } from '../ui/primitives'
import { Button, FIELD } from '../ui/forms'

const dateDe = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      })
    : '—'

const de = (n: number) => n.toLocaleString('de-DE')

/**
 * Where a contact's data came from, in the recruiter's language.
 *
 * Only two of these carry an obligation, and the label says which — a source
 * shown as an opaque enum value is a compliance fact nobody reads.
 */
const SOURCE_LABEL: Record<string, { text: string; owes: boolean }> = {
  self_reported: { text: 'selbst genannt', owes: false },
  human_verified: { text: 'selbst erfasst', owes: false },
  document_extraction: { text: 'aus Dokument', owes: false },
  public_web: { text: 'öffentlich gefunden', owes: true },
  third_party_source: { text: 'Dritte Quelle', owes: true },
}

/** One contact, expandable to their interaction history. */
function ManagerRow({
  manager,
  companyName,
  onNotified,
}: {
  manager: ManagerDTO
  companyName: string
  onNotified: (updated: ManagerDTO) => void
}) {
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState<ManagerInteractionDTO[] | null>(null)
  const [busy, setBusy] = useState(false)
  const source = SOURCE_LABEL[manager.source] ?? {
    text: manager.source,
    owes: false,
  }

  const toggle = useCallback(async () => {
    const next = !open
    setOpen(next)
    if (next && history === null) {
      // Loaded on demand: 650 contacts x their history is not a page load.
      setHistory(await api.managerInteractions(manager.id).catch(() => []))
    }
  }, [open, history, manager.id])

  const markNotified = useCallback(async () => {
    setBusy(true)
    try {
      onNotified(await api.markManagerArt14Notified(manager.id))
    } finally {
      setBusy(false)
    }
  }, [manager.id, onNotified])

  return (
    <li className="border-b border-cockpit-line/40 py-2.5 last:border-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <button
          type="button"
          onClick={toggle}
          className="text-left text-[15px] text-cockpit-text transition-colors hover:text-mint-400"
        >
          {manager.full_name}
        </button>
        {manager.role_title && (
          <span className="text-[13px] text-cockpit-dim">{manager.role_title}</span>
        )}
        <span className="flex items-center gap-1.5 font-mono text-[12px] text-cockpit-faint">
          <Building2 className="h-3.5 w-3.5 shrink-0" />
          {companyName}
        </span>

        <span className="ml-auto flex items-center gap-3 font-mono text-[12px] text-cockpit-faint">
          {manager.email && (
            <a
              href={`mailto:${manager.email}`}
              className="flex items-center gap-1 transition-colors hover:text-mint-400"
            >
              <Mail className="h-3.5 w-3.5" />
              {manager.email}
            </a>
          )}
          {manager.phone && (
            <span className="flex items-center gap-1">
              <Phone className="h-3.5 w-3.5" />
              {manager.phone}
            </span>
          )}
          {/* The obligation, where it is actionable rather than in a report. */}
          {manager.art14_outstanding ? (
            <Button onClick={markNotified} disabled={busy} tone="primary">
              <ShieldAlert className="h-3.5 w-3.5" />
              {busy ? 'Speichert…' : 'Art. 14 erledigt'}
            </Button>
          ) : (
            <span
              title={`Herkunft: ${source.text}${
                manager.art14_notified_at
                  ? ` · informiert am ${dateDe(manager.art14_notified_at)}`
                  : ''
              }`}
              className={cn(source.owes ? 'text-mint-400' : 'text-cockpit-faint')}
            >
              {source.text}
            </span>
          )}
        </span>
      </div>

      {open && (
        <div className="mt-2 rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2">
          {history === null ? (
            <p className="font-mono text-[12px] text-cockpit-faint">lädt Verlauf…</p>
          ) : history.length === 0 ? (
            <p className="text-[13px] text-cockpit-dim">
              Noch kein Kontaktverlauf. Anrufe, Mails und Termine erscheinen hier,
              sobald sie erfasst werden.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {history.map((entry) => (
                <li key={entry.id} className="flex gap-3 text-[13px]">
                  <span className="w-24 shrink-0 font-mono text-[12px] text-cockpit-faint">
                    {dateDe(entry.occurred_at)}
                  </span>
                  <span className="w-20 shrink-0 text-cockpit-dim">
                    {entry.interaction_type}
                  </span>
                  <span className="text-cockpit-text">{entry.summary ?? '—'}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  )
}

export function ManagerScreen() {
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [overrides, setOverrides] = useState<Record<string, ManagerDTO>>({})

  // Debounced: the search hits the database, and 650 rows is enough that a
  // request per keystroke is felt.
  useEffect(() => {
    const id = setTimeout(() => setQuery(draft.trim()), 250)
    return () => clearTimeout(id)
  }, [draft])

  const managers = useAsync<ManagerDTO[]>(
    () => api.managers({ q: query || undefined, limit: 200 }),
    [query],
  )
  const companies = useAsync<CompanyDTO[]>(() => api.companies(), [])
  const art14 = useAsync<ManagerDTO[]>(() => api.managersOwingArt14(), [])

  const companyName = useMemo(() => {
    const byId = new Map((companies.data ?? []).map((c) => [c.id, c.name]))
    return (id: string) => byId.get(id) ?? '—'
  }, [companies.data])

  const rows = (managers.data ?? []).map((m) => overrides[m.id] ?? m)
  // Counted from the live queue, then adjusted by anything discharged in this
  // session — so the number moves when the button is pressed rather than on a
  // reload.
  const owing =
    (art14.data ?? []).filter((m) => (overrides[m.id] ?? m).art14_outstanding).length

  return (
    <div className="space-y-8">
      <header id="section-manager" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Manager
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          Die Ansprechpartner auf Kundenseite — die Person, zu der ein Mandat gehört.
          Firmen stellen nicht ein, Menschen tun es. Diese Kontakte bleiben in diesem
          Workspace und sind kein Teil des geteilten Markt-Korpus.
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          index="01"
          title="Kontakte"
          hint={
            managers.loading
              ? 'lädt…'
              : `${de(rows.length)}${rows.length === 200 ? '+' : ''} angezeigt`
          }
        />

        <Panel className="p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[18rem] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-cockpit-faint" />
              <input
                className={cn(FIELD, 'pl-9')}
                placeholder="Name, Rolle oder Firma…"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
            </div>
            {/* An obligation with a deadline belongs next to the work, not in a
                report nobody opens. */}
            {owing > 0 && (
              <span className="flex items-center gap-1.5 rounded-lg border border-gold-400/40 bg-gold-400/10 px-3 py-2 text-[13px] text-gold-400">
                <ShieldAlert className="h-4 w-4" />
                {de(owing)} × Art.-14-Information offen
              </span>
            )}
            {owing === 0 && !art14.loading && (
              <span className="flex items-center gap-1.5 text-[13px] text-cockpit-faint">
                <Check className="h-4 w-4 text-mint-400" />
                keine Art.-14-Information offen
              </span>
            )}
          </div>
        </Panel>

        {managers.error && (
          <Panel className="p-5">
            <p className="text-[14px] text-coral-400">
              Kontakte konnten nicht geladen werden.
            </p>
          </Panel>
        )}

        {!managers.error && !managers.loading && rows.length === 0 && (
          <Panel className="p-5">
            <p className="text-[14px] text-cockpit-dim">
              {query
                ? `Kein Kontakt passt zu „${query}“.`
                : 'Noch keine Ansprechpartner. Übernehmen Sie ein Unternehmen aus dem Markt oder importieren Sie Ihr bestehendes System.'}
            </p>
          </Panel>
        )}

        {rows.length > 0 && (
          <Panel className="px-4 py-1">
            <ul>
              {rows.map((manager) => (
                <ManagerRow
                  key={manager.id}
                  manager={manager}
                  companyName={companyName(manager.company_id)}
                  onNotified={(updated) =>
                    setOverrides((prev) => ({ ...prev, [updated.id]: updated }))
                  }
                />
              ))}
            </ul>
          </Panel>
        )}

        {rows.length === 200 && (
          <p className="flex items-center gap-1.5 font-mono text-[12px] text-cockpit-faint">
            <UserRound className="h-3.5 w-3.5" />
            Es werden die ersten 200 Kontakte gezeigt — grenzen Sie die Suche ein.
          </p>
        )}
      </section>
    </div>
  )
}
