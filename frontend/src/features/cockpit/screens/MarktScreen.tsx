// "Markt" — the shared information hub, as a search surface.
//
// This is deliberately NOT a directory. A list of every company the crawler has
// seen answers "who has the most vacancies in Germany", and the answer is always
// a discounter. The question a recruiter actually has is "who is hiring X near
// Y", so the screen opens empty and waits to be asked.
//
// Two consequences shape the layout:
//
//   * Results are EMPLOYERS, rolled up across sites. `name_place` identity
//     yields one corpus row per branch, so Netto arrives as ~238 rows; grouped,
//     it is one line reading "238 Standorte · 264 offene Rollen" — which is the
//     useful form for business development anyway.
//   * Every hit shows the roles that made it match. An employer in a result
//     list without its matching roles is an assertion; with them it is evidence.
//
// The corpus itself is shared across workspaces and refreshed by a nightly job —
// nothing here can trigger a crawl (ARCHITECTURE.md RULE 1). Only "beobachten"
// writes anything, and it writes to this workspace alone.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Bookmark,
  BookmarkCheck,
  Building2,
  Check,
  ChevronDown,
  ExternalLink,
  Globe,
  MapPin,
  Search,
  Star,
  Trash2,
  UserRound,
  X,
} from 'lucide-react'
import { ApiError, api } from '@/api/client'
import type {
  FacetValueDTO,
  HubJobPostingDTO,
  HubCorpusStatsDTO,
  HubEmployerHitDTO,
  HubFacetsDTO,
  SavedSearchDTO,
} from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import { Button, FIELD } from '../ui/forms'

/**
 * Which rung of the identity ladder established this employer.
 *
 * Deliberately not collapsed into one "verified" tick: `name_place` is an
 * assumption that two postings naming the same employer in the same town are
 * the same company. True almost always, provable never — so it reads neutral
 * rather than green.
 */
const IDENTITY: Record<
  HubEmployerHitDTO['resolution_basis'],
  { label: string; tone?: 'mint' | 'gold'; title: string }
> = {
  vat: { label: 'USt-IdNr', tone: 'mint', title: 'Identität über die USt-IdNr bestimmt' },
  register: { label: 'HRB', tone: 'mint', title: 'Identität über das Handelsregister bestimmt' },
  domain: { label: 'Domain', tone: 'gold', title: 'Identität über die Unternehmensdomain bestimmt' },
  name_place: {
    label: 'Name + Ort',
    title: 'Angenommen aus Firmenname und Ort — nicht gegen ein Register geprüft',
  },
}

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
 * The source emits ASCII-folded region codes — `BADEN_WUERTTEMBERG`,
 * `THUERINGEN`. Title-casing them alone leaves "Baden-Wuerttemberg", so the 16
 * states are mapped explicitly: umlauts cannot be recovered by transformation,
 * and a German product spelling German states wrong is not a detail.
 */
const REGION_LABELS: Record<string, string> = {
  BADEN_WUERTTEMBERG: 'Baden-Württemberg',
  BAYERN: 'Bayern',
  BERLIN: 'Berlin',
  BRANDENBURG: 'Brandenburg',
  BREMEN: 'Bremen',
  HAMBURG: 'Hamburg',
  HESSEN: 'Hessen',
  MECKLENBURG_VORPOMMERN: 'Mecklenburg-Vorpommern',
  NIEDERSACHSEN: 'Niedersachsen',
  NORDRHEIN_WESTFALEN: 'Nordrhein-Westfalen',
  RHEINLAND_PFALZ: 'Rheinland-Pfalz',
  SAARLAND: 'Saarland',
  SACHSEN: 'Sachsen',
  SACHSEN_ANHALT: 'Sachsen-Anhalt',
  SCHLESWIG_HOLSTEIN: 'Schleswig-Holstein',
  THUERINGEN: 'Thüringen',
}

/** Falls back to title-case for anything the source adds later. */
const prettyRegion = (raw: string) =>
  REGION_LABELS[raw] ??
  raw
    .split('_')
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join('-')

/**
 * Multi-select filter. OR within one control, AND across the two — several
 * Bundesländer widen the area, a Berufsfeld narrows within it.
 *
 * Options come from `/hub/facets`, i.e. from the corpus itself with counts, so
 * the list never offers a filter that would return nothing. A Berufsfeld only
 * appears once postings carrying it have been ingested.
 */
function FacetFilter({
  label,
  options,
  selected,
  onChange,
  format = (v: string) => v,
  emptyHint,
}: {
  label: string
  options: FacetValueDTO[]
  selected: string[]
  onChange: (next: string[]) => void
  format?: (value: string) => string
  /** Why there is nothing to choose yet. A dead grey control explains nothing. */
  emptyHint?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = (value: string) =>
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value],
    )

  if (options.length === 0) {
    // Stay clickable and say why. The values arrive with ingestion, so an
    // empty list means "not crawled yet", not "broken".
    return (
      <span
        title={emptyHint}
        className="flex cursor-help items-center gap-1.5 rounded-xl border border-dashed border-cockpit-line px-4 py-2 text-[14px] text-cockpit-faint"
      >
        {label}
        <span className="font-mono text-[11px]">keine Werte</span>
      </span>
    )
  }

  return (
    <div ref={ref} className="relative">
      <Button onClick={() => setOpen((o) => !o)}>
        {label}
        {selected.length > 0 && (
          <span className="rounded-md bg-mint-800/70 px-1.5 font-mono text-[12px] text-mint-300">
            {selected.length}
          </span>
        )}
        <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} />
      </Button>

      {open && (
        <div className="absolute z-50 mt-1 max-h-80 w-[22rem] overflow-y-auto rounded-xl border border-cockpit-line bg-cockpit-surface shadow-panel">
          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="w-full border-b border-cockpit-line px-3 py-2 text-left font-mono text-[12px] text-cockpit-faint hover:text-coral-400"
            >
              Auswahl aufheben
            </button>
          )}
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => toggle(option.value)}
              className={cn(
                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] transition-colors hover:bg-white/[0.04]',
                selected.includes(option.value) ? 'text-cockpit-text' : 'text-cockpit-dim',
              )}
            >
              <Check
                className={cn(
                  'h-3.5 w-3.5 shrink-0',
                  selected.includes(option.value) ? 'text-mint-400' : 'text-transparent',
                )}
              />
              <span className="truncate">{format(option.value)}</span>
              <span className="ml-auto shrink-0 font-mono text-[11px] text-cockpit-faint">
                {option.count}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** Suggestions, so an empty screen teaches what the box accepts. */
const EXAMPLES = ['Embedded', 'SAP', 'Pflegefachkraft', 'Berlin', 'Netto']

/**
 * Standing questions — the thing that makes this a daily tool.
 *
 * A saved profile is also an ingestion directive: the nightly job crawls the
 * source with these keywords, which is how postings whose stack appears only in
 * the description reach the corpus at all. Measured, only 5% of TypeScript roles
 * name the stack in their title, so without this a corpus search misses 95% of
 * them. Saving one fetches nothing — the scheduled job acts on it later.
 */
function SavedSearches({
  active,
  onRun,
  onDeleted,
  searches,
  reload,
}: {
  active: string | null
  onRun: (search: SavedSearchDTO) => void
  onDeleted: () => void
  searches: SavedSearchDTO[]
  reload: () => void
}) {
  if (searches.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
        Suchprofile
      </span>
      {searches.map((saved) => (
        <span
          key={saved.id}
          className={cn(
            'flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[13px] transition-colors',
            saved.id === active
              ? 'border-mint-600 bg-mint-800/40 text-mint-300'
              : 'border-cockpit-line text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text',
          )}
        >
          <button type="button" onClick={() => onRun(saved)} className="flex items-center gap-2">
            {saved.label}
            {saved.last_result_count != null && (
              <span className="font-mono text-[11px] text-cockpit-faint">
                {saved.last_result_count}
              </span>
            )}
          </button>
          <button
            type="button"
            aria-label={`${saved.label} löschen`}
            onClick={async () => {
              await api.deleteSavedSearch(saved.id).catch(() => {})
              reload()
              onDeleted()
            }}
            className="text-cockpit-faint transition-colors hover:text-coral-400"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </span>
      ))}
    </div>
  )
}

/** One role, expandable to its full ad text when the corpus has it. */
function RoleRow({ role }: { role: HubJobPostingDTO }) {
  const [open, setOpen] = useState(false)
  const link = role.source_url ?? role.detail_url
  return (
    <li className="border-b border-cockpit-line/30 pb-1 last:border-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {role.description ? (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-1.5 text-left text-[14px] text-cockpit-text transition-colors hover:text-mint-400"
          >
            <ChevronDown
              className={cn(
                'h-3.5 w-3.5 shrink-0 text-cockpit-faint transition-transform',
                open && 'rotate-180',
              )}
            />
            {role.title}
          </button>
        ) : (
          <span className="text-[14px] text-cockpit-text">{role.title}</span>
        )}
        {role.city && <Chip>{role.city}</Chip>}
        {role.remote_possible && <Chip tone="lav">Homeoffice</Chip>}
        <span className="ml-auto flex items-center gap-3 font-mono text-[12px] text-cockpit-faint">
          <span>{dateDe(role.posted_at)}</span>
          {/* The employer's own ad when the source has one, otherwise the
              agency's page derived from the reference number — so every posting
              opens somewhere instead of most being dead ends. */}
          {link && (
            <a
              href={link}
              target="_blank"
              rel="noreferrer noopener"
              className="flex items-center gap-1 transition-colors hover:text-mint-400"
              title={
                role.source_url
                  ? 'Original-Stellenanzeige beim Unternehmen öffnen'
                  : 'Anzeige bei der Bundesagentur für Arbeit öffnen'
              }
            >
              {role.source_url ? 'Quelle' : 'Anzeige'}
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </span>
      </div>
      {open && role.description && (
        <p className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 text-[13px] leading-relaxed text-cockpit-dim">
          {role.description}
        </p>
      )}
    </li>
  )
}

function EmployerCard({ hit }: { hit: HubEmployerHitDTO }) {
  const [tracked, setTracked] = useState(hit.tracked)
  const [saving, setSaving] = useState(false)
  const identity = IDENTITY[hit.resolution_basis] ?? IDENTITY.name_place
  // Tracking is per corpus row; a rolled-up employer is tracked via its first
  // site, which is what the API reports back as `tracked`.
  const anchorId = hit.hub_company_ids[0]

  const toggle = async () => {
    if (!anchorId) return
    const next = !tracked
    setTracked(next)
    setSaving(true)
    try {
      if (next) await api.trackHubCompany(anchorId, 'watching')
      else await api.untrackHubCompany(anchorId)
    } catch {
      setTracked(!next)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <h3 className="text-[16px] font-medium text-cockpit-text">{hit.name}</h3>
        {hit.website_domain && (
          <span className="flex items-center gap-1 font-mono text-[12px] text-cockpit-faint">
            <Globe className="h-3.5 w-3.5" />
            {hit.website_domain}
          </span>
        )}
        <Chip tone={identity.tone} className="cursor-help">
          <span title={identity.title}>{identity.label}</span>
        </Chip>
        {hit.suspected_natural_person && (
          <Chip tone="coral" className="cursor-help">
            <span
              title="Der Firmenname sieht nach einer natürlichen Person aus (Einzelunternehmen). Damit stehen personenbezogene Daten im geteilten Korpus — automatisch erkannt, nicht geprüft."
              className="flex items-center gap-1"
            >
              <UserRound className="h-3 w-3" />
              mögl. Person
            </span>
          </Chip>
        )}

        <span className="ml-auto flex items-center gap-4 font-mono text-[13px] text-cockpit-faint">
          {hit.sites > 1 && (
            <span title="Standorte im Korpus — dieselbe Firma, mehrfach erfasst">
              <span className="text-cockpit-text">{de(hit.sites)}</span> Standorte
            </span>
          )}
          <span title="Treffer für diese Suche — nicht alle offenen Rollen des Unternehmens">
            <span className="text-[15px] text-cockpit-text">{de(hit.open_roles)}</span> Rollen
          </span>
          <Button onClick={toggle} disabled={saving || !anchorId} tone={tracked ? 'primary' : 'ghost'}>
            {tracked ? <BookmarkCheck className="h-4 w-4" /> : <Bookmark className="h-4 w-4" />}
            {tracked ? 'Beobachtet' : 'Beobachten'}
          </Button>
        </span>
      </div>

      <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[12px] text-cockpit-dim">
        <MapPin className="h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
        {hit.cities.join(' · ') || '—'}
        {hit.city_count > hit.cities.length && (
          <span className="text-cockpit-faint">
            +{hit.city_count - hit.cities.length} weitere
          </span>
        )}
      </p>

      {hit.matching_roles.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-cockpit-line/60 pt-2.5">
          {hit.matching_roles.map((role) => (
            <RoleRow key={role.id} role={role} />
          ))}
          {hit.open_roles > hit.matching_roles.length && (
            <li className="px-0 pt-1 font-mono text-[12px] text-cockpit-faint">
              +{de(hit.open_roles - hit.matching_roles.length)} weitere Treffer
            </li>
          )}
        </ul>
      )}
    </Panel>
  )
}

/**
 * What actually went wrong, rather than a guess.
 *
 * This previously read "ist die Sitzung noch gültig?" for EVERY failure. That
 * is one plausible cause out of many, and when the real answer was a 500 from a
 * query the database cancelled, the message sent the reader to re-authenticate
 * — a wrong instruction is worse than a vague one. The status code decides the
 * sentence now, and the server's own text is shown underneath, so a failure can
 * be diagnosed from the screen instead of from the Network tab.
 */
function SearchError({ error }: { error: Error }) {
  const status = error instanceof ApiError ? error.status : null

  // A fetch that never got a response (network down, CORS, aborted) has no
  // status at all — distinct from the server answering with a failure.
  const headline =
    status === null
      ? 'Keine Antwort vom Server — Netzwerk, CORS oder Abbruch.'
      : status === 401 || status === 403
        ? `Sitzung abgelaufen oder nicht berechtigt (HTTP ${status}) — bitte neu anmelden.`
        : status === 408 || status === 504 || status === 502 || status === 503
          ? `Zeitüberschreitung (HTTP ${status}) — die Suche war zu langsam für den Server.`
          : status >= 500
            ? `Serverfehler (HTTP ${status}) — die Abfrage wurde nicht zu Ende geführt.`
            : `Suche abgelehnt (HTTP ${status}).`

  // The body is the useful half for a 500 (Postgres names its own cancellation),
  // but it can be a long HTML error page, so it is capped.
  const detail = (error.message ?? '').trim().slice(0, 300)

  return (
    <Panel className="space-y-2 p-5">
      <p className="text-[14px] text-coral-400">Die Suche ist fehlgeschlagen — {headline}</p>
      {detail && (
        <p className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-cockpit-faint">
          {detail}
        </p>
      )}
    </Panel>
  )
}

export function MarktScreen() {
  const [draft, setDraft] = useState('')
  const [city, setCity] = useState('')
  // The executed query, distinct from the draft: results change when you search,
  // not on every keystroke against a 14k-row corpus.
  const [query, setQuery] = useState<{
    q: string
    city: string
    regions: string[]
    berufsfelder: string[]
  } | null>(null)
  const [regions, setRegions] = useState<string[]>([])
  const [berufsfelder, setBerufsfelder] = useState<string[]>([])
  const [activeSaved, setActiveSaved] = useState<string | null>(null)
  const [savedKey, setSavedKey] = useState(0)

  const stats = useAsync<HubCorpusStatsDTO>(() => api.hubStats(), [])
  const facets = useAsync<HubFacetsDTO>(() => api.hubFacets(), [])
  const saved = useAsync<SavedSearchDTO[]>(() => api.savedSearches(), [savedKey])
  const results = useAsync<HubEmployerHitDTO[]>(
    () =>
      query
        ? api.hubSearch({
            q: query.q,
            city: query.city,
            regions: query.regions,
            berufsfelder: query.berufsfelder,
            limit: 40,
          })
        : Promise.resolve([]),
    [query?.q, query?.city, query?.regions.join('|'), query?.berufsfelder.join('|')],
  )

  const run = useCallback(() => {
    setActiveSaved(null)
    setQuery({ q: draft.trim(), city: city.trim(), regions, berufsfelder })
  }, [draft, city, regions, berufsfelder])

  const runSaved = useCallback((search: SavedSearchDTO) => {
    setDraft(search.q ?? '')
    setCity(search.city ?? '')
    setRegions(search.regions ?? [])
    setBerufsfelder(search.berufsfelder ?? [])
    setActiveSaved(search.id)
    setQuery({
      q: search.q ?? '',
      city: search.city ?? '',
      regions: search.regions ?? [],
      berufsfelder: search.berufsfelder ?? [],
    })
  }, [])

  const saveCurrent = useCallback(async () => {
    if (!query) return
    const label =
      [query.q, query.city].filter(Boolean).join(' · ') ||
      [...query.berufsfelder, ...query.regions.map(prettyRegion)].join(' · ')
    if (!label) return
    await api
      .createSavedSearch({
        label: label.slice(0, 120),
        q: query.q || null,
        city: query.city || null,
        regions: query.regions,
        berufsfelder: query.berufsfelder,
      })
      .catch(() => {})
    setSavedKey((k) => k + 1)
  }, [query])

  const savedList = saved.data ?? []
  const same = (a: string[], b: string[]) =>
    a.length === b.length && [...a].sort().join('|') === [...b].sort().join('|')
  const alreadySaved = savedList.some(
    (x) =>
      (x.q ?? '') === (query?.q ?? '') &&
      (x.city ?? '') === (query?.city ?? '') &&
      same(x.regions ?? [], query?.regions ?? []) &&
      same(x.berufsfelder ?? [], query?.berufsfelder ?? []),
  )
  const hasCriteria =
    !!query && (!!query.q || !!query.city || query.regions.length > 0 || query.berufsfelder.length > 0)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') {
        const el = e.target as HTMLElement | null
        if (el?.tagName === 'INPUT') run()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [run])

  const s = stats.data
  const hits = results.data ?? []
  const totalRoles = useMemo(
    () => hits.reduce((sum, h) => sum + h.open_roles, 0),
    [hits],
  )

  return (
    <div className="space-y-8">
      <header id="section-markt" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Markt
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          Wer gerade einstellt — durchsuchbar nach Rolle, Firma und Ort. Der Korpus ist
          geteilt und wird nächtlich aktualisiert; was Sie beobachten, bleibt in diesem
          Workspace.
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          index="01"
          title="Suche"
          hint={
            s?.last_ingest_at
              ? `zuletzt aktualisiert ${dateDe(s.last_ingest_at)}`
              : stats.error
                ? 'offline'
                : 'live aus dem Korpus'
          }
        />

        {/* Corpus totals — counted in the database, never over the loaded page. */}
        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 font-mono text-[13px] text-cockpit-faint">
          {s ? (
            <>
              <span title="Unternehmen nach Zusammenfassung der Standorte">
                <span className="text-cockpit-text">{de(s.employers)}</span> Unternehmen
              </span>
              <span title="Einzelne Korpus-Einträge — eine Firma kann mehrere Standorte haben">
                <span className="text-cockpit-text">{de(s.companies)}</span> Standorte
              </span>
              <span>
                <span className="text-cockpit-text">{de(s.open_postings)}</span> offene Rollen
              </span>
              <span>
                <span className="text-cockpit-text">{de(s.cities)}</span> Orte
              </span>
              <span title="Identität aus Name + Ort angenommen, nicht gegen ein Register geprüft">
                <span className="text-cockpit-text">{de(s.unverified_identity)}</span> ohne
                Registerprüfung
              </span>
              {s.suspected_personal_data > 0 && (
                <span title="Firmennamen, die nach natürlichen Personen aussehen (Einzelunternehmen) — personenbezogene Daten im geteilten Korpus">
                  <span className="text-coral-400">{de(s.suspected_personal_data)}</span> mögl.
                  Personen
                </span>
              )}
            </>
          ) : (
            <span>{stats.error ? 'Korpus nicht erreichbar' : 'lädt Kennzahlen…'}</span>
          )}
        </div>

        {/* Query */}
        <div className="flex flex-wrap items-center gap-3">
          <label className="relative flex min-w-[18rem] flex-1 items-center">
            <Search className="pointer-events-none absolute left-3.5 h-[17px] w-[17px] text-cockpit-faint" />
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Rolle, Firma oder Stichwort — z. B. Embedded, SAP, Pflegefachkraft"
              className={cn(FIELD, 'py-2.5 pl-11 pr-9 text-[15px]')}
            />
            {draft && (
              <button
                type="button"
                onClick={() => setDraft('')}
                aria-label="Suche zurücksetzen"
                className="absolute right-3 text-cockpit-faint transition-colors hover:text-cockpit-text"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </label>
          <label className="relative flex w-52 items-center">
            <MapPin className="pointer-events-none absolute left-3.5 h-[17px] w-[17px] text-cockpit-faint" />
            <input
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="Ort"
              className={cn(FIELD, 'py-2.5 pl-11 text-[15px]')}
            />
          </label>
          <FacetFilter
            label="Bundesland"
            options={facets.data?.regions ?? []}
            selected={regions}
            onChange={setRegions}
            format={prettyRegion}
            emptyHint="Das Bundesland wird beim Ingest aus der Adresse der Anzeige übernommen. Anzeigen, die vor Einführung des Feldes erfasst wurden, tragen es erst nach dem nächsten Lauf."
          />
          <FacetFilter
            label="Berufsfeld"
            options={facets.data?.berufsfelder ?? []}
            selected={berufsfelder}
            onChange={setBerufsfelder}
            emptyHint="Das Berufsfeld liefert die Quelle nicht pro Anzeige — es entsteht nur, wenn der nächtliche Lauf gezielt danach fragt. Werte erscheinen nach dem ersten berufsfeld-Durchlauf."
          />
          <Button tone="primary" onClick={run} disabled={results.loading}>
            <Search className="h-4 w-4" />
            {results.loading ? 'Sucht…' : 'Suchen'}
          </Button>
          {hasCriteria && !alreadySaved && (
            <Button
              onClick={saveCurrent}
              title="Als Suchprofil merken — der nächtliche Lauf holt dafür gezielt neue Anzeigen"
            >
              <Star className="h-4 w-4" /> Merken
            </Button>
          )}
        </div>

        <SavedSearches
          searches={savedList}
          active={activeSaved}
          onRun={runSaved}
          onDeleted={() => setActiveSaved(null)}
          reload={() => setSavedKey((k) => k + 1)}
        />

        {/* Results */}
        {!query && (
          <Panel className="p-6">
            <div className="flex items-start gap-3">
              <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
                <Building2 className="h-5 w-5" />
              </span>
              <div className="space-y-3">
                <p className="max-w-2xl text-[14px] leading-relaxed text-cockpit-dim">
                  {s && s.companies === 0
                    ? 'Der Korpus ist noch leer. Er wird von einem nächtlichen Job befüllt — eine Suche löst nie eine Abfrage bei einer öffentlichen Quelle aus.'
                    : 'Suchen Sie nach einer Rolle, einer Firma oder einem Ort. Die Liste aller Unternehmen wäre keine Antwort auf eine Frage, die jemand stellt.'}
                </p>
                <p className="max-w-2xl text-[13px] leading-relaxed text-cockpit-faint">
                  Wiederkehrende Suchen als Profil merken: der nächtliche Lauf fragt die
                  Quelle gezielt danach ab — inklusive Anzeigentexten, die hier sonst nicht
                  durchsuchbar sind.
                </p>
                <div className="flex flex-wrap gap-2">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => {
                        setDraft(example)
                        setQuery({
                          q: example,
                          city: city.trim(),
                          regions,
                          berufsfelder,
                        })
                      }}
                      className="rounded-md border border-cockpit-line px-2.5 py-1 font-mono text-[12px] text-cockpit-dim transition-colors hover:border-mint-600 hover:text-mint-400"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </Panel>
        )}

        {query && results.loading && (
          <p className="font-mono text-[13px] text-cockpit-faint">sucht im Korpus…</p>
        )}

        {query && results.error && <SearchError error={results.error} />}

        {query && !results.loading && !results.error && (
          <>
            <p className="font-mono text-[13px] text-cockpit-faint">
              <span className="text-cockpit-text">{de(hits.length)}</span> Unternehmen ·{' '}
              <span className="text-cockpit-text">{de(totalRoles)}</span> offene Rollen
              {hits.length >= 40 && <span> · nur die stärksten 40 gezeigt</span>}
            </p>

            {hits.length === 0 ? (
              <Panel className="p-6">
                <p className="text-[14px] text-cockpit-dim">
                  Nichts gefunden für „{query.q || query.city}“. Der Korpus enthält heute nur
                  Titel und Berufsbezeichnungen — keine Anzeigentexte —, deshalb trifft eine
                  Suche nach Anforderungen noch nicht.
                </p>
              </Panel>
            ) : (
              <div className="space-y-3">
                {hits.map((hit) => (
                  <EmployerCard key={hit.normalized_name} hit={hit} />
                ))}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
