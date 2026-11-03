// Agenturen — Eligo's own business development over the shared corpus.
//
// Private recruiters, ranked as LEADS: one row per agency (its branches folded
// together), with the deterministic verdict and score the nightly job worked
// out, and every reason's evidence. Reached only by workspaces the backend
// allowlists (`agency_finder_tenants`); see `agencyCopy.probeAgencyFinder`.
//
// Nothing is invented: before the first nightly rebuild the list is empty and
// says so, and a failed call says so and shows nothing.

import { useEffect, useRef, useState } from 'react'
import { Building2, Check, ExternalLink, Loader2, UserPlus } from 'lucide-react'

import { api } from '@/api/client'
import type {
  AgencyDetailDTO,
  AgencyProfileDTO,
  AgencyVerdict,
  ContactCandidateDTO,
  HubFacetsDTO,
} from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { t } from '@/i18n'
import { dateTime, num } from '@/i18n/format'
import { cn } from '@/lib/cn'
import { Chip, Panel, SectionHeader, Tag } from '../../ui/primitives'
import { NetworkLink, dateDe, linkedInSearch, xingSearch } from '../ContactsPanel'
import { prettyRegion } from '../MarktScreen'
import {
  VERDICT_LABEL,
  appendPage,
  contactPayload,
  latestOnly,
  nothingSelected,
  reasonText,
  verdictTone,
  websiteCandidates,
} from './agencyCopy'

const PAGE = 50
const VERDICTS: AgencyVerdict[] = ['agency', 'unclear', 'client']

const statusOf = (e: unknown): number | undefined =>
  typeof e === 'object' && e && 'status' in e ? Number((e as { status: unknown }).status) : undefined

export function AgenturenScreen({
  agencyId,
  onSelect,
}: {
  agencyId: string | null
  onSelect: (id: string | null) => void
}) {
  const [verdicts, setVerdicts] = useState<AgencyVerdict[]>(['agency', 'unclear'])
  const [region, setRegion] = useState('')
  const [field, setField] = useState('')
  const [chains, setChains] = useState(false)
  const [rows, setRows] = useState<AgencyProfileDTO[]>([])
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const facets = useAsync<HubFacetsDTO>(() => api.hubFacets(), [])
  const gate = useRef(latestOnly())

  const load = async (offset: number) => {
    const token = gate.current.next()
    setError(null)
    if (nothingSelected(verdicts)) {
      setRows([])
      setMore(false)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const page = await api.agencies({
        verdict: verdicts,
        region: region || undefined,
        berufsfeld: field || undefined,
        includeChains: chains,
        limit: PAGE,
        offset,
      })
      if (!gate.current.isCurrent(token)) return
      setRows((prev) => appendPage(prev, page.items, offset))
      setMore(page.items.length === PAGE)
    } catch (e) {
      if (!gate.current.isCurrent(token)) return
      setError(t('Agenturen konnten nicht geladen werden (HTTP {status}).', { status: statusOf(e) ?? '—' }))
      if (!offset) setRows([])
    } finally {
      if (gate.current.isCurrent(token)) setLoading(false)
    }
  }

  useEffect(() => {
    void load(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [verdicts.join(','), region, field, chains])

  const toggle = (v: AgencyVerdict) =>
    setVerdicts((cur) => (cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]))
  const refreshed = rows[0]?.refreshed_at

  return (
    <div className="space-y-8">
      <header id="section-agenturen" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          {t('Agenturen')}
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          {t('Private Arbeitsvermittler aus den öffentlichen Anzeigen — als Leads für Eligo, nach Regeln bewertet, jede Einstufung mit ihren Belegen. Nur in diesem Workspace sichtbar.')}
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          index="01"
          tone="gold"
          title={t('Rangliste')}
          hint={refreshed ? t('Stand {when}', { when: dateTime(refreshed) }) : undefined}
        />

        <div className="flex flex-wrap items-center gap-2">
          {VERDICTS.map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={verdicts.includes(v)}
              onClick={() => toggle(v)}
              className={cn(
                'rounded-lg border px-3 py-1.5 font-mono text-[12px] transition-colors',
                verdicts.includes(v)
                  ? 'border-gold-600 bg-gold-800/40 text-gold-400'
                  : 'border-cockpit-line text-cockpit-faint hover:border-cockpit-edge',
              )}
            >
              {verdicts.includes(v) && <Check className="mr-1 inline h-3 w-3" />}
              {VERDICT_LABEL[v]}
            </button>
          ))}
          <select
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="rounded-lg border border-cockpit-line bg-cockpit-inset px-2 py-1.5 text-[13px] text-cockpit-dim"
            aria-label={t('Bundesland')}
          >
            <option value="">{t('Alle Bundesländer')}</option>
            {(facets.data?.regions ?? []).map((r) => (
              <option key={r.value} value={r.value}>
                {prettyRegion(r.value)}
              </option>
            ))}
          </select>
          <select
            value={field}
            onChange={(e) => setField(e.target.value)}
            className="max-w-[260px] rounded-lg border border-cockpit-line bg-cockpit-inset px-2 py-1.5 text-[13px] text-cockpit-dim"
            aria-label={t('Berufsfeld')}
          >
            <option value="">{t('Alle Berufsfelder')}</option>
            {(facets.data?.berufsfelder ?? []).map((f) => (
              <option key={f.value} value={f.value}>
                {f.value}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-[13px] text-cockpit-dim">
            <input type="checkbox" checked={chains} onChange={(e) => setChains(e.target.checked)} />
            {t('Ketten (über 50 Anzeigen)')}
          </label>
        </div>

        {error && <Panel className="p-5 text-[14px] text-coral-400">{error}</Panel>}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div className="space-y-2">
            {!error && !loading && rows.length === 0 && (
              <Panel className="p-6 text-[14px] text-cockpit-dim">
                {t('Noch keine Agenturprofile für diese Auswahl — der nächste Nachtlauf baut sie aus den Anzeigen.')}
              </Panel>
            )}
            {rows.map((a) => (
              <AgencyRow key={a.id} agency={a} active={a.id === agencyId} onOpen={() => onSelect(a.id)} />
            ))}
            {loading && (
              <p className="flex items-center gap-2 font-mono text-[13px] text-cockpit-faint">
                <Loader2 className="h-4 w-4 animate-spin" /> {t('lädt …')}
              </p>
            )}
            {more && !loading && (
              <button
                type="button"
                onClick={() => void load(rows.length)}
                className="w-full rounded-lg border border-cockpit-line py-2 font-mono text-[13px] text-cockpit-dim hover:border-cockpit-edge"
              >
                {t('Mehr laden')}
              </button>
            )}
          </div>
          <div>
            {agencyId ? (
              <AgencyDetail key={agencyId} id={agencyId} onClose={() => onSelect(null)} />
            ) : (
              <Panel tone="inset" className="p-6 text-[14px] text-cockpit-faint">
                {t('Eine Agentur wählen, um Standorte, Anzeigen und Kontakte zu sehen.')}
              </Panel>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}

function AgencyRow({ agency: a, active, onOpen }: { agency: AgencyProfileDTO; active: boolean; onOpen: () => void }) {
  const fields = Object.entries(a.fields).sort((x, y) => y[1] - x[1]).slice(0, 3)
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        'block w-full rounded-panel border bg-cockpit-surface p-4 text-left transition-colors',
        active ? 'border-gold-600' : 'border-cockpit-line hover:border-cockpit-edge',
      )}
    >
      <div className="flex items-baseline gap-3">
        <span className="w-8 shrink-0 font-mono text-[18px] text-gold-400">{a.score}</span>
        <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-cockpit-text">{a.name}</span>
        <Tag tone={verdictTone(a.verdict) ?? 'lav'}>{VERDICT_LABEL[a.verdict]}</Tag>
      </div>
      <p className="mt-1 pl-11 font-mono text-[12px] text-cockpit-faint">
        {[
          a.city,
          a.branches === 1 ? t('1 Standort') : t('{n} Standorte', { n: num(a.branches) }),
          t('{n} offen', { n: num(a.open_postings) }),
          t('+{n} in 28 T', { n: num(a.new_28d) }),
        ]
          .filter(Boolean)
          .join(' · ')}
      </p>
      {fields.length > 0 && (
        <p className="mt-1 truncate pl-11 text-[12px] text-cockpit-dim">{fields.map(([f]) => f).join(' · ')}</p>
      )}
      <div className="mt-2 flex flex-wrap gap-1.5 pl-11">
        {a.reasons.slice(0, 4).map((r) => (
          <Chip key={r.code} title={JSON.stringify(r.evidence)}>
            {reasonText(r)}
          </Chip>
        ))}
      </div>
    </button>
  )
}

function AgencyDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const detail = useAsync<AgencyDetailDTO>(() => api.agency(id), [id])
  const [contactKey, setContactKey] = useState<string | null>(null)
  const [adopting, setAdopting] = useState(false)
  const [outcome, setOutcome] = useState<string | null>(null)

  if (detail.loading) {
    return (
      <Panel className="flex items-center gap-2 p-6 font-mono text-[13px] text-cockpit-faint">
        <Loader2 className="h-4 w-4 animate-spin" /> {t('lädt …')}
      </Panel>
    )
  }
  if (detail.error || !detail.data) {
    return (
      <Panel className="p-6 text-[14px] text-coral-400">
        {statusOf(detail.error) === 404
          ? t('Diese Agentur ist nicht mehr im Korpus.')
          : t('Die Agentur konnte nicht geladen werden.')}
      </Panel>
    )
  }
  const { profile, branches, postings, contacts } = detail.data
  const chosen: ContactCandidateDTO | undefined = contacts.contacts.find((c) => c.key === contactKey)

  const [art14, setArt14] = useState(false)

  const adopt = async () => {
    setAdopting(true)
    setOutcome(null)
    try {
      const result = await api.adoptAgency(
        profile.id,
        chosen ? contactPayload(chosen) : null,
      )
      setArt14(result.art14_outstanding)
      setOutcome(
        !chosen
          ? t('Im CRM angelegt.')
          : result.manager_id
            ? t('Im CRM angelegt, mit {name} als Kontakt.', { name: chosen.full_name })
            // The person asked to be erased in this workspace: the agency is
            // in, the person deliberately is not.
            : t('Im CRM angelegt — ohne Kontakt: {name} wurde hier auf Wunsch gelöscht.', { name: chosen.full_name }),
      )
    } catch (e) {
      setOutcome(statusOf(e) === 409 ? t('Bereits im CRM.') : t('Übernahme fehlgeschlagen.'))
    } finally {
      setAdopting(false)
    }
  }

  return (
    <Panel className="space-y-6 p-5">
      <div className="flex items-start gap-3">
        <Building2 className="mt-1 h-5 w-5 text-gold-400" />
        <div className="min-w-0 flex-1">
          <h3 className="text-[20px] font-semibold text-cockpit-text">{profile.name}</h3>
          <p className="font-mono text-[12px] text-cockpit-faint">
            {VERDICT_LABEL[profile.verdict]} · {t('Score {n}', { n: profile.score })}
          </p>
        </div>
        <button type="button" onClick={onClose} className="font-mono text-[12px] text-cockpit-faint hover:text-cockpit-text">
          {t('schließen')}
        </button>
      </div>

      <div className="space-y-2">
        <h4 className="font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint">{t('Warum')}</h4>
        <div className="flex flex-wrap gap-1.5">
          {profile.reasons.map((r) => (
            <Chip key={r.code} tone={r.points != null ? 'gold' : undefined} title={JSON.stringify(r.evidence)}>
              {reasonText(r)}
            </Chip>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <h4 className="font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint">
          {t('Website (unbestätigt)')}
        </h4>
        {websiteCandidates(profile).length === 0 ? (
          <p className="text-[13px] text-cockpit-faint">{t('Keine Domain in den Anzeigentexten.')}</p>
        ) : (
          <ul className="space-y-1 text-[13px]">
            {websiteCandidates(profile).map((c) => (
              <li key={c.domain} className="flex flex-wrap items-baseline gap-2">
                {/* Plain text, not a link: nobody has checked this site yet —
                    it may be the client's, or a look-alike. PR7 verifies. */}
                <span className="select-all font-mono text-cockpit-text">{c.domain}</span>
                <span className="font-mono text-[12px] text-cockpit-faint">
                  {c.ads === 1 ? t('1 Anzeige') : t('{n} Anzeigen', { n: num(c.ads) })}
                </span>
                {c.name_match && <Chip tone="mint">{t('Name passt')}</Chip>}
                {c.likely_client && <Chip tone="gold">{t('vermutlich Kunde')}</Chip>}
              </li>
            ))}
          </ul>
        )}
        <p className="text-[12px] text-cockpit-faint">
          {t('Aus den Anzeigen gelesen, nicht geprüft — bestätigt erst ein Impressum, das die Firma nennt.')}
        </p>
      </div>

      <div className="space-y-2">
        <h4 className="font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint">
          {t('Standorte ({n})', { n: branches.length })}
        </h4>
        <ul className="space-y-1 text-[13px] text-cockpit-dim">
          {branches.map((b) => (
            <li key={b.id}>
              {b.name}
              {b.city ? ` · ${b.city}` : ''}
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-2">
        <h4 className="font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint">
          {t('Anzeigen ({n})', { n: postings.length })}
        </h4>
        <ul className="max-h-64 space-y-1 overflow-y-auto pr-2 text-[13px]">
          {postings.map((p) => (
            <li key={p.id} className="flex items-baseline gap-2">
              <span className="w-20 shrink-0 font-mono text-[12px] text-cockpit-faint">{dateDe(p.posted_at)}</span>
              <span className={cn('min-w-0 flex-1 truncate', p.is_active ? 'text-cockpit-text' : 'text-cockpit-faint')}>
                {p.title}
              </span>
              {(p.detail_url || p.source_url) && (
                <a
                  href={p.detail_url ?? p.source_url ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cockpit-faint hover:text-cockpit-text"
                  aria-label={t('Anzeige öffnen')}
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-2">
        <h4 className="font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint">
          {t('Kontakte aus den Anzeigen')}
        </h4>
        {contacts.contacts.length === 0 ? (
          <p className="text-[13px] text-cockpit-faint">
            {contacts.postings_with_text
              ? t('Keine Person in {n} Anzeigentexten genannt.', { n: num(contacts.postings_with_text) })
              : t('Noch keine Anzeigentexte geladen.')}
          </p>
        ) : (
          <ul className="space-y-2">
            {contacts.contacts.map((c) => (
              <li key={c.key} className="flex flex-wrap items-center gap-2 text-[13px]">
                <label className="flex min-w-0 flex-1 items-center gap-2 text-cockpit-text">
                  <input
                    type="radio"
                    name="agency-contact"
                    checked={contactKey === c.key}
                    onChange={() => setContactKey(c.key)}
                    onClick={() => contactKey === c.key && setContactKey(null)}
                  />
                  <span className="truncate">
                    {c.full_name}
                    {c.role_title ? <span className="text-cockpit-faint"> · {c.role_title}</span> : null}
                  </span>
                </label>
                <NetworkLink href={linkedInSearch(c, profile.name)} label="LinkedIn" className="bg-[#0a66c2]" />
                <NetworkLink href={xingSearch(c, profile.name)} label="XING" className="bg-[#006567]" />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-cockpit-line pt-4">
        <button
          type="button"
          disabled={adopting}
          onClick={() => void adopt()}
          className="flex items-center gap-2 rounded-lg border border-gold-600 bg-gold-800/40 px-3 py-2 text-[13px] text-gold-400 hover:bg-gold-800/60 disabled:opacity-50"
        >
          {adopting ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
          {chosen ? t('Mit Kontakt ins CRM übernehmen') : t('Ins CRM übernehmen')}
        </button>
        <span aria-live="polite" className="font-mono text-[12px] text-cockpit-dim">
          {outcome}
        </span>
        {chosen && (
          <button
            type="button"
            onClick={() => setContactKey(null)}
            className="font-mono text-[12px] text-cockpit-faint hover:text-cockpit-text"
          >
            {t('ohne Kontakt')}
          </button>
        )}
      </div>
      {art14 && (
        <p className="text-[13px] text-gold-400">
          {t('Art.-14-Hinweis offen: Die Person wurde aus einer öffentlichen Anzeige übernommen und muss informiert werden.')}
        </p>
      )}
    </Panel>
  )
}
