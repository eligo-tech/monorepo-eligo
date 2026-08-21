// "Markt" — the shared information hub as a cockpit screen.
//
// The outside world, not the own record: companies and their open roles
// aggregated from public sources, ordered by who is hiring hardest. That
// ordering IS the product — a recruiter wants whoever has the most open roles
// right now, not an alphabetical register extract.
//
// The corpus itself is SHARED across workspaces — public facts, crawled once.
// What this workspace makes of it is not: "beobachten" writes a tenant-scoped
// overlay row, and that toggle is the only thing on this screen that belongs to
// you rather than to everybody.
//
// The identity badge on each row is the other half. Every company here was
// deduplicated by a deterministic ladder (VAT → Handelsregister → domain →
// name + PLZ), and the badge says WHICH rung matched. A company proven by VAT
// id is a different claim from one assumed from a name and a postcode, and the
// surface refuses to blur the two.

import { useMemo, useState } from 'react'
import {
  Bookmark,
  BookmarkCheck,
  Building2,
  ChevronRight,
  ExternalLink,
  Globe,
  MapPin,
  Search,
  X,
} from 'lucide-react'
import { api } from '@/api/client'
import type { HubCompanyDTO, HubJobPostingDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import { Button, FIELD } from '../ui/forms'

const GRID = 'grid-cols-[minmax(0,3fr)_minmax(0,1.6fr)_minmax(0,1.4fr)_5.5rem]'
const COLUMNS = ['Unternehmen', 'Ort', 'Identität', 'Rollen']

/**
 * How the identity was established, in the recruiter's language.
 *
 * Deliberately not collapsed into a single "verified" flag: `name_place` is an
 * assumption that two postings naming the same employer in the same town are
 * the same company. True almost always, provable never — so it reads as neutral
 * rather than green.
 */
const IDENTITY: Record<
  HubCompanyDTO['resolution_basis'],
  { label: string; tone?: 'mint' | 'gold'; title: string }
> = {
  vat: {
    label: 'USt-IdNr',
    tone: 'mint',
    title: 'Identität über die Umsatzsteuer-Identifikationsnummer bestimmt',
  },
  register: {
    label: 'HRB',
    tone: 'mint',
    title: 'Identität über Registergericht und Handelsregisternummer bestimmt',
  },
  domain: {
    label: 'Domain',
    tone: 'gold',
    title: 'Identität über die Unternehmensdomain bestimmt',
  },
  name_place: {
    label: 'Name + Ort',
    title: 'Angenommen aus Firmenname und Ort — nicht gegen ein Register geprüft',
  },
}

const dateDe = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—'

/** Free-text haystack for one company row. */
function matches(c: HubCompanyDTO, q: string): boolean {
  return [c.name, c.city, c.postal_code, c.website_domain, c.industry]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .includes(q)
}

/** The open roles for one company, loaded on expand rather than up front. */
function PostingList({ companyId }: { companyId: string }) {
  const { data, loading, error } = useAsync<HubJobPostingDTO[]>(
    () => api.hubCompanyPostings(companyId),
    [companyId],
  )

  if (loading) {
    return <p className="px-3 py-3 font-mono text-[12px] text-cockpit-faint">lädt…</p>
  }
  if (error || !data) {
    return (
      <p className="px-3 py-3 font-mono text-[12px] text-coral-400">
        Rollen konnten nicht geladen werden.
      </p>
    )
  }

  return (
    <ul className="divide-y divide-cockpit-line/60">
      {data.map((p) => (
        <li key={p.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2">
          <span className="text-[14px] text-cockpit-text">{p.title}</span>
          {p.occupation && p.occupation !== p.title && (
            <Chip className="shrink-0">{p.occupation}</Chip>
          )}
          {p.remote_possible && <Chip tone="lav">Homeoffice</Chip>}
          <span className="ml-auto flex items-center gap-3 font-mono text-[12px] text-cockpit-faint">
            <span title="Erstveröffentlichung">{dateDe(p.posted_at)}</span>
            {p.source_url && (
              // The employer's own posting — the entry point for upgrading this
              // company from a shallow board record to its real ATS feed.
              <a
                href={p.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="flex items-center gap-1 transition-colors hover:text-mint-400"
                title="Original-Stellenanzeige öffnen"
              >
                Quelle <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

function CompanyRow({ company }: { company: HubCompanyDTO }) {
  const [open, setOpen] = useState(false)
  // Optimistic: the overlay row is this workspace's own state, so the toggle
  // should feel immediate. Reverted if the write fails.
  const [tracked, setTracked] = useState(company.tracked)
  const [saving, setSaving] = useState(false)
  const identity = IDENTITY[company.resolution_basis] ?? IDENTITY.name_place

  const toggleTracked = async () => {
    const next = !tracked
    setTracked(next)
    setSaving(true)
    try {
      if (next) await api.trackHubCompany(company.id, 'watching')
      else await api.untrackHubCompany(company.id)
    } catch {
      setTracked(!next)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border-b border-cockpit-line/60">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(
          'grid w-full items-center gap-4 px-3 py-2.5 text-left transition-colors hover:bg-white/[0.02]',
          GRID,
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <ChevronRight
            className={cn(
              'h-4 w-4 shrink-0 text-cockpit-faint transition-transform',
              open && 'rotate-90',
            )}
          />
          <span className="truncate text-[15px] text-cockpit-text">{company.name}</span>
          {company.website_domain && (
            <Globe className="h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
          )}
          {tracked && (
            <BookmarkCheck
              className="h-3.5 w-3.5 shrink-0 text-mint-400"
              aria-label="Wird beobachtet"
            />
          )}
        </span>

        <span className="truncate font-mono text-[13px] text-cockpit-dim">
          {[company.postal_code, company.city].filter(Boolean).join(' ') || '—'}
        </span>

        <span>
          <Chip tone={identity.tone} className="cursor-help" >
            <span title={identity.title}>{identity.label}</span>
          </Chip>
        </span>

        <span className="text-right font-mono text-[15px] text-cockpit-text">
          {company.open_postings_count}
        </span>
      </button>

      {open && (
        <div className="bg-cockpit-inset/50">
          {/* The one action on this screen that writes tenant-scoped state.
              Everything above it is shared corpus, identical for every workspace. */}
          <div className="flex items-center gap-3 px-3 pt-3">
            <Button onClick={toggleTracked} disabled={saving} tone={tracked ? 'primary' : 'ghost'}>
              {tracked ? <BookmarkCheck className="h-4 w-4" /> : <Bookmark className="h-4 w-4" />}
              {tracked ? 'Wird beobachtet' : 'Beobachten'}
            </Button>
            <span className="font-mono text-[11px] text-cockpit-faint">
              nur in diesem Workspace sichtbar
            </span>
          </div>
          <PostingList companyId={company.id} />
        </div>
      )}
    </div>
  )
}

/**
 * Shown when the corpus is empty — which it is until somebody ingests.
 *
 * An empty table reads as "broken"; naming the exact command that fills it
 * reads as "not started yet". The hub has no automatic population by design:
 * ingestion only ever runs when it is asked to.
 */
function EmptyCorpus() {
  return (
    <Panel className="p-6">
      <div className="flex items-start gap-3">
        <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
          <Building2 className="h-5 w-5" />
        </span>
        <div className="min-w-0 space-y-2">
          <h3 className="text-[16px] font-medium text-cockpit-text">
            Noch keine Unternehmen im Korpus
          </h3>
          <p className="max-w-2xl text-[14px] leading-relaxed text-cockpit-dim">
            Der Korpus wird von einem nächtlichen Job befüllt, nicht aus der Oberfläche —
            eine Suche löst niemals eine Abfrage bei einer öffentlichen Quelle aus. Bis der
            erste Lauf durch ist, bleibt diese Ansicht leer. Erstbefüllung einer Region:
          </p>
          <pre className="overflow-x-auto rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 font-mono text-[12px] text-cockpit-dim">
python -m scripts.hub_backfill --where München --radius 25
          </pre>
        </div>
      </div>
    </Panel>
  )
}

export function MarktScreen() {
  const [query, setQuery] = useState('')
  const { data, loading, error } = useAsync<HubCompanyDTO[]>(
    () => api.hubCompanies({ limit: 500 }),
    [],
  )

  const all = useMemo(() => data ?? [], [data])
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? all.filter((c) => matches(c, q)) : all
  }, [all, query])

  const openRoles = all.reduce((sum, c) => sum + c.open_postings_count, 0)
  const hiring = all.filter((c) => c.open_postings_count > 0).length
  const cities = new Set(all.map((c) => c.city).filter(Boolean)).size
  // How much of the corpus rests on an assumption rather than a register.
  const assumed = all.filter((c) => c.resolution_basis === 'name_place').length
  const tracked = all.filter((c) => c.tracked).length

  return (
    <div className="space-y-8">
      <header id="section-markt" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Markt
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          Unternehmen und ihre offenen Rollen aus öffentlichen Quellen — wer gerade
          einstellt, zuerst. Der Korpus ist geteilt und wird nächtlich aktualisiert;
          was Sie beobachten, bleibt in diesem Workspace. Jede Zeile zeigt, woraus die
          Identität des Unternehmens bestimmt wurde.
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          id="section-unternehmen"
          index="01"
          title="Unternehmen"
          hint={error ? 'offline' : 'live aus dem Korpus'}
        />

        {/* Stats strip */}
        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 font-mono text-[13px] text-cockpit-faint">
          <span>
            <span className="text-cockpit-text">{all.length}</span> Unternehmen
          </span>
          <span>
            <span className="text-cockpit-text">{hiring}</span> stellen ein
          </span>
          <span>
            <span className="text-cockpit-text">{openRoles}</span> offene Rollen
          </span>
          <span>
            <span className="text-cockpit-text">{cities}</span> Orte
          </span>
          <span title="Von diesem Workspace beobachtet — nicht Teil des geteilten Korpus">
            <span className="text-cockpit-text">{tracked}</span> beobachtet
          </span>
          {assumed > 0 && (
            <span title="Identität aus Name + Ort angenommen, nicht gegen ein Register geprüft">
              <span className="text-cockpit-text">{assumed}</span> ohne Registerprüfung
            </span>
          )}
        </div>

        {/* Toolbar */}
        <label className="relative flex min-w-[16rem] max-w-xl items-center">
          <Search className="pointer-events-none absolute left-3.5 h-[17px] w-[17px] text-cockpit-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Unternehmen, Ort, Domain…"
            className={cn(FIELD, 'py-2.5 pl-11 pr-9 text-[15px]')}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Suche zurücksetzen"
              className="absolute right-3 text-cockpit-faint transition-colors hover:text-cockpit-text"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </label>

        {loading && (
          <p className="font-mono text-[13px] text-cockpit-faint">lädt Korpus…</p>
        )}

        {error && (
          <Panel className="p-5">
            <p className="text-[14px] text-coral-400">
              Der Korpus konnte nicht geladen werden — ist die Sitzung noch gültig?
            </p>
          </Panel>
        )}

        {!loading && !error && all.length === 0 && <EmptyCorpus />}

        {!loading && !error && all.length > 0 && (
          <div>
            <div
              className={cn(
                'grid gap-4 border-b border-cockpit-line px-3 pb-2.5',
                'font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint',
                GRID,
              )}
            >
              {COLUMNS.map((c) => (
                <div key={c} className={c === 'Rollen' ? 'text-right' : undefined}>
                  {c}
                </div>
              ))}
            </div>

            {rows.map((c) => (
              <CompanyRow key={c.id} company={c} />
            ))}

            {rows.length === 0 && (
              <p className="flex items-center gap-2 px-3 py-6 text-[14px] text-cockpit-dim">
                <MapPin className="h-4 w-4 text-cockpit-faint" />
                Kein Unternehmen passt zu „{query}“.
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
