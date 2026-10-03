// "Manager" — the client-side contact people. Live from /managers.
//
// A Manager is the person at a client company a mandate actually belongs to:
// Firma → Manager → Job. Companies do not hire, people do, and the relationship
// that wins the next mandate is with a person rather than a legal entity.
//
// It is deliberately NOT part of the shared market corpus — see ARCHITECTURE.md
// RULE 2. The corpus may show a person as a public ad names them; a Manager is
// this workspace's relationship with that person (imports, enriched contact
// details, notes), so it stays tenant-scoped, carries provenance, and routes
// through the GDPR Art. 14 flow when it comes from a public source.
//
// That provenance is the reason this screen leads with an obligation counter
// rather than a headcount: "how many people do I hold data on who have not been
// told" is the question with a deadline attached.

import { useMemo, useState } from 'react'
import {
  Building2,
  Check,
  Mail,
  MapPin,
  Phone,
  Search,
  ShieldAlert,
  UserRound,
} from 'lucide-react'
import { api } from '@/api/client'
import type { CompanyDTO, ManagerDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { searchScore } from '@/lib/search'
import { Panel, SectionHeader } from '../ui/primitives'
import { ManagerProfile } from './ManagerProfile'
import { FIELD } from '../ui/forms'

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
  onOpen,
}: {
  manager: ManagerDTO
  companyName: string
  onOpen: () => void
}) {
  const source = SOURCE_LABEL[manager.source] ?? {
    text: manager.source,
    owes: false,
  }

  return (
    <li className="border-b border-cockpit-line/40 py-2.5 last:border-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <button
          type="button"
          onClick={onOpen}
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
        {/* 642 of 647 contacts carry a city, and none of them showed it. A
            field you can search but not see reads as a search that guesses. */}
        {manager.city && (
          <span className="flex items-center gap-1.5 font-mono text-[12px] text-cockpit-faint">
            <MapPin className="h-3.5 w-3.5 shrink-0" />
            {manager.city}
          </span>
        )}

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
          {/* The source holds some people twice. Said plainly on the row so the
              reader is not left wondering whether they misread the list. */}
          {(manager.duplicate_count ?? 1) > 1 && (
            <span
              className="text-gold-400"
              title="Dieselbe E-Mail-Adresse existiert mehrfach — in der Quelle doppelt angelegt"
            >
              Dublette
            </span>
          )}
          {manager.last_contact_at && (
            <span title="Letzter Kontakt laut Quelle">
              {dateDe(manager.last_contact_at)}
            </span>
          )}
          {/* The obligation is visible in the list and dischargeable in the
              drawer — a row is the wrong place for an action with consequences. */}
          {manager.art14_outstanding ? (
            <span className="flex items-center gap-1 text-gold-400">
              <ShieldAlert className="h-3.5 w-3.5" />
              Art. 14 offen
            </span>
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

    </li>
  )
}

export function ManagerScreen() {
  const [query, setQuery] = useState('')
  const [overrides, setOverrides] = useState<Record<string, ManagerDTO>>({})
  const [selected, setSelected] = useState<ManagerDTO | null>(null)

  // The whole pool, once. It used to be a debounced database query per
  // keystroke, capped at 200 of 647 — so a term matching 300 people showed
  // 200 of them with nothing saying so, and a typo showed none. 647 contacts
  // fit comfortably in the browser, where the scorer can also rank them.
  const managers = useAsync(() => api.managersPage(), [])
  const companies = useAsync<CompanyDTO[]>(() => api.companies(), [])
  const art14 = useAsync<ManagerDTO[]>(() => api.managersOwingArt14(), [])

  const companyName = useMemo(() => {
    const byId = new Map((companies.data ?? []).map((c) => [c.id, c.name]))
    return (id: string) => byId.get(id) ?? '—'
  }, [companies.data])

  const all = useMemo(
    () => (managers.data?.items ?? []).map((m) => overrides[m.id] ?? m),
    [managers.data, overrides],
  )
  const poolTotal = managers.data?.total ?? all.length
  const truncated = poolTotal > all.length

  const term = query.trim()
  // Scored and ranked, like Jobs and Kandidaten: "CTO Bergfreunde" finds the
  // person although no single field holds both words, and "Bergfruende"
  // still finds them.
  const rows = useMemo(() => {
    if (!term) return all
    return all
      .map((m) => ({
        m,
        score: searchScore(
          [
            { text: m.full_name, weight: 3 },
            { text: m.role_title ?? '', weight: 3 },
            { text: companyName(m.company_id), weight: 2.5 },
            // Where the person sits. The contact's OWN address, which the
            // import carried all along — not the client company's
            // `location`, which is filled for 13 of 341 companies.
            { text: `${m.city ?? ''} ${m.postal_code ?? ''}`, weight: 2 },
            { text: `${m.email ?? ''} ${m.phone ?? ''}`, weight: 1 },
          ],
          term,
        ),
      }))
      .filter((r) => r.score > 0)
      .sort((a, b) => b.score - a.score)
      .map((r) => r.m)
  }, [all, companyName, term])
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
              : term
                ? `${de(rows.length)} von ${de(all.length)} · nach Relevanz`
                : `${de(all.length)} Kontakte${
                    truncated ? ` von ${de(poolTotal)} geladen` : ''
                  }`
          }
        />

        <Panel className="p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[18rem] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-cockpit-faint" />
              <input
                className={cn(FIELD, 'pl-9')}
                placeholder="Name, Rolle, Firma, Ort oder PLZ — Tippfehler erlaubt"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
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
              {term ? (
                <>
                  Kein Kontakt passt zu „{term}“.
                  <button
                    type="button"
                    onClick={() => setQuery('')}
                    className="ml-2 font-mono text-[12px] text-mint-300 transition-colors hover:text-cockpit-text"
                  >
                    Suche zurücksetzen
                  </button>
                </>
              ) : (
                'Noch keine Ansprechpartner. Übernehmen Sie ein Unternehmen aus dem Markt oder importieren Sie Ihr bestehendes System.'
              )}
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
                  onOpen={() => setSelected(manager)}
                />
              ))}
            </ul>
          </Panel>
        )}

        {selected && (
          <ManagerProfile
            manager={overrides[selected.id] ?? selected}
            companyName={companyName(selected.company_id)}
            onClose={() => setSelected(null)}
            onNotified={(updated) =>
              setOverrides((prev) => ({ ...prev, [updated.id]: updated }))
            }
          />
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
