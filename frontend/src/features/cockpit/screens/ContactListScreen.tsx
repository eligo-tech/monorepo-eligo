// "Kontaktliste" — the workspace's contacts and the call list (ELI-22/23).
//
// Kontakte — everyone in this workspace, newest first; a person adopted on
// Markt lands here. Filter or group by company (companies are how this list is
// cut, not a screen of their own).
//
// Two tabs over the backend's `/hub/call-list`:
//   * Anrufen — people open job ads name, across the market, that this
//     workspace has not called yet. Direct lines first. The ad line is shown
//     as evidence, because the name came out of a parser.
//   * Wiedervorlage — people this workspace has called, due call-backs first.
//
// Logging the first call takes the person into the workspace (company as a
// prospect, the person as a manager sourced from the ad — GDPR Art. 14 owed)
// and records the outcome. A person this workspace erased never shows here
// and cannot be called back in (the backend refuses with 409).

import { t } from '@/i18n'
import { locale } from '@/i18n/format'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Building2, ExternalLink, Mail, Phone, PhoneCall, Search, Users } from 'lucide-react'
import { ApiError, api } from '@/api/client'
import type { CallListRowDTO, ContactPageDTO, ContactRowDTO, FollowUpDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Button, FIELD, SelectInput } from '../ui/forms'
import { Chip, Panel, SectionHeader, SegmentedControl } from '../ui/primitives'
import {
  CALL_OUTCOMES,
  CALL_OUTCOME_TONE,
  callOutcomeLabel,
  canSaveCall,
  needsDate,
} from '../ui/callOutcomes'

type Tab = 'contacts' | 'market' | 'follow_ups'

const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString(locale(), {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—'

/** `datetime-local` → ISO in the browser's time zone. */
const toIso = (local: string) => (local ? new Date(local).toISOString() : null)

function PhoneLink({ phone, kind, fromAd = false }: { phone: string | null; kind?: string | null; fromAd?: boolean }) {
  if (!phone)
    return <span className="text-cockpit-faint">{fromAd ? t('keine Nummer im Inserat') : t('keine Nummer')}</span>
  return (
    <span className="flex items-center gap-2">
      <a
        href={`tel:${phone.replace(/[^\d+]/g, '')}`}
        className="flex items-center gap-1 font-mono text-[13px] text-cockpit-text hover:text-mint-400"
      >
        <Phone className="h-3.5 w-3.5 text-cockpit-faint" />
        {phone}
      </a>
      {kind === 'switchboard' && (
        <span
          className="rounded border border-gold-600/50 px-1.5 text-[11px] text-gold-400"
          title={t('Die Nummer endet auf -0 oder ist eine Service-Nummer: Sie erreichen die Zentrale, nicht die Person direkt.')}
        >
          {t('Zentrale')}
        </span>
      )}
    </span>
  )
}

/** Outcome, optional next date, optional note — then save. */
function CallForm({
  onSave,
  onCancel,
}: {
  onSave: (outcome: string, nextAt: string | null, note: string) => Promise<void>
  onCancel: () => void
}) {
  const [outcome, setOutcome] = useState<string>('')
  const [nextAt, setNextAt] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await onSave(outcome, toIso(nextAt), note.trim())
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? t('Diese Person wurde in diesem Workspace gelöscht und wird nicht wieder angelegt.')
          : t('Speichern fehlgeschlagen.'),
      )
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="mt-3 grid gap-3 rounded-lg border border-cockpit-line/70 bg-cockpit-inset p-3 sm:grid-cols-[1fr_1fr]">
      <SelectInput
        label={t('Ergebnis')}
        value={outcome}
        onChange={setOutcome}
        options={[{ value: '', label: t('— bitte wählen —') }, ...CALL_OUTCOMES.map((o) => ({ value: o, label: callOutcomeLabel(o) }))]}
      />
      <label className="block min-w-0">
        <span className="mb-1 block font-mono text-[11px] uppercase tracking-wide text-cockpit-faint">
          {needsDate(outcome) ? t('Nächster Anruf (Pflicht)') : t('Nächster Anruf (optional)')}
        </span>
        <input type="datetime-local" value={nextAt} onChange={(e) => setNextAt(e.target.value)} className={FIELD} />
      </label>
      <label className="block min-w-0 sm:col-span-2">
        <span className="mb-1 block font-mono text-[11px] uppercase tracking-wide text-cockpit-faint">{t('Notiz')}</span>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className={FIELD} />
      </label>
      <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
        <Button tone="primary" onClick={save} disabled={busy || !canSaveCall(outcome, nextAt)}>
          {t('Anruf speichern')}
        </Button>
        <Button tone="ghost" onClick={onCancel} disabled={busy}>
          {t('Abbrechen')}
        </Button>
        {error && <span className="text-[12px] text-coral-400">{error}</span>}
      </div>
    </div>
  )
}

function MarketRow({ row, onCalled }: { row: CallListRowDTO; onCalled: (art14: boolean) => void }) {
  const [calling, setCalling] = useState(false)
  return (
    <li className="border-b border-cockpit-line/40 py-3 last:border-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[15px] font-medium text-cockpit-text">
          {row.salutation ? `${row.salutation} ` : ''}
          {row.full_name}
        </span>
        {row.role_title && <span className="text-[13px] text-cockpit-dim">{row.role_title}</span>}
        <Chip tone={row.reach === 'named_phone' ? 'mint' : undefined}>
          {row.reach === 'named_phone' ? t('Person + Telefon') : t('Person, ohne Telefon')}
        </Chip>
        <span className="ml-auto font-mono text-[12px] text-cockpit-faint">
          {row.company_name} · {row.open_ads} {row.open_ads === 1 ? t('offene Anzeige') : t('offene Anzeigen')}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
        <PhoneLink phone={row.phone} kind={row.phone_kind} fromAd />
        {row.email && (
          <a href={`mailto:${row.email}`} className="flex items-center gap-1 font-mono text-[12px] text-cockpit-dim hover:text-mint-400">
            <Mail className="h-3.5 w-3.5 text-cockpit-faint" />
            {row.email}
          </a>
        )}
        {!calling && (
          <Button onClick={() => setCalling(true)} className="ml-auto">
            <PhoneCall className="h-4 w-4" />
            {t('Anruf erfassen')}
          </Button>
        )}
      </div>
      <p className="mt-1.5 max-w-3xl text-[12px] leading-relaxed text-cockpit-faint">
        „{row.quote}“ — {row.posting_title}
        {row.source_url && (
          <a href={row.source_url} target="_blank" rel="noreferrer noopener" className="ml-1.5 inline-flex items-center gap-0.5 hover:text-mint-400">
            <ExternalLink className="h-3 w-3" />
            {t('Anzeige')}
          </a>
        )}
      </p>
      {calling && (
        <CallForm
          onCancel={() => setCalling(false)}
          onSave={async (outcome, nextAt, note) => {
            const result = await api.logCall({
              hub_company_id: row.hub_company_id,
              person_key: row.person_key,
              outcome,
              next_action_at: nextAt,
              summary: note || null,
            })
            onCalled(result.art14_outstanding)
          }}
        />
      )}
    </li>
  )
}

function FollowUpRow({ row, onCalled }: { row: FollowUpDTO; onCalled: () => void }) {
  const [calling, setCalling] = useState(false)
  return (
    <li className={cn('border-b border-cockpit-line/40 py-3 last:border-0', row.due && 'bg-gold-500/[0.04]')}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[15px] font-medium text-cockpit-text">{row.full_name}</span>
        {row.role_title && <span className="text-[13px] text-cockpit-dim">{row.role_title}</span>}
        <Chip tone={CALL_OUTCOME_TONE[row.outcome]}>{callOutcomeLabel(row.outcome)}</Chip>
        <span className="ml-auto font-mono text-[12px] text-cockpit-faint">{row.company_name}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[12px] text-cockpit-dim">
        <PhoneLink phone={row.phone} />
        <span>
          {t('Zuletzt')}: {when(row.last_call_at)}
          {row.last_call_by ? ` · ${row.last_call_by}` : ''}
        </span>
        {row.next_action_at && (
          <span className={row.due ? 'text-gold-400' : undefined}>
            {row.due ? t('Fällig seit') : t('Nächster Anruf')}: {when(row.next_action_at)}
          </span>
        )}
        {!calling && (
          <Button onClick={() => setCalling(true)} className="ml-auto">
            <PhoneCall className="h-4 w-4" />
            {t('Anruf erfassen')}
          </Button>
        )}
      </div>
      {row.summary && <p className="mt-1.5 max-w-3xl text-[12px] text-cockpit-faint">{row.summary}</p>}
      {calling && (
        <CallForm
          onCancel={() => setCalling(false)}
          onSave={async (outcome, nextAt, note) => {
            await api.logManagerInteraction(row.manager_id, {
              interaction_type: 'business_call',
              summary: note,
              outcome,
              next_action_at: nextAt,
            })
            setCalling(false)
            onCalled()
          }}
        />
      )}
    </li>
  )
}

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(locale(), { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—'

/** One contact in this workspace — how to reach them, where they came from,
 *  and how the last call went. */
function ContactRow({ row, showCompany, onCalled }: { row: ContactRowDTO; showCompany: boolean; onCalled: () => void }) {
  const [calling, setCalling] = useState(false)
  return (
    <li className={cn('border-b border-cockpit-line/40 py-3 last:border-0', row.due && 'bg-gold-500/[0.04]')}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[15px] font-medium text-cockpit-text">{row.full_name}</span>
        {row.role_title && <span className="text-[13px] text-cockpit-dim">{row.role_title}</span>}
        {row.last_outcome && <Chip tone={CALL_OUTCOME_TONE[row.last_outcome]}>{callOutcomeLabel(row.last_outcome)}</Chip>}
        {row.art14_outstanding && (
          <Chip tone="gold">
            <span title={t('Aus einer öffentlichen Anzeige übernommen — die Information nach Art. 14 DSGVO steht noch aus.')}>
              {t('Art. 14 offen')}
            </span>
          </Chip>
        )}
        <span className="ml-auto font-mono text-[12px] text-cockpit-faint">
          {showCompany && <>{row.company_name} · </>}
          {t('hinzugefügt am {date}', { date: day(row.added_at) })}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[12px] text-cockpit-dim">
        <PhoneLink phone={row.phone} />
        {row.email && (
          <a href={`mailto:${row.email}`} className="flex items-center gap-1 hover:text-mint-400">
            <Mail className="h-3.5 w-3.5 text-cockpit-faint" />
            {row.email}
          </a>
        )}
        {row.linkedin_url && (
          <a href={row.linkedin_url} target="_blank" rel="noreferrer noopener" className="hover:text-mint-400">
            LinkedIn
          </a>
        )}
        {row.source === 'public_web' && row.source_detail?.startsWith('http') && (
          <a href={row.source_detail} target="_blank" rel="noreferrer noopener" className="flex items-center gap-1 hover:text-mint-400">
            <ExternalLink className="h-3 w-3" />
            {t('aus Anzeige')}
          </a>
        )}
        {row.last_call_at && (
          <span>
            {t('Zuletzt')}: {when(row.last_call_at)}
            {row.last_call_by ? ` · ${row.last_call_by}` : ''}
          </span>
        )}
        {row.next_action_at && (
          <span className={row.due ? 'text-gold-400' : undefined}>
            {row.due ? t('Fällig seit') : t('Nächster Anruf')}: {when(row.next_action_at)}
          </span>
        )}
        {!calling && (
          <Button onClick={() => setCalling(true)} className="ml-auto">
            <PhoneCall className="h-4 w-4" />
            {t('Anruf erfassen')}
          </Button>
        )}
      </div>
      {calling && (
        <CallForm
          onCancel={() => setCalling(false)}
          onSave={async (outcome, nextAt, note) => {
            await api.logManagerInteraction(row.manager_id, {
              interaction_type: 'business_call',
              summary: note,
              outcome,
              next_action_at: nextAt,
            })
            setCalling(false)
            onCalled()
          }}
        />
      )}
    </li>
  )
}

/** "Kontakte": everyone in this workspace, newest first — a person adopted on
 *  Markt lands here. Cut by company (filter) or seen per company (grouped):
 *  companies are how this list is sliced, not a screen of their own. */
function ContactsTab({ reloadKey, onCalled }: { reloadKey: number; onCalled: () => void }) {
  const [page, setPage] = useState<ContactPageDTO | null>(null)
  const [companyId, setCompanyId] = useState('')
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [dueOnly, setDueOnly] = useState(false)
  const [grouped, setGrouped] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)
  const [bump, setBump] = useState(0)

  useEffect(() => {
    const mine = ++latest.current
    api
      .callListContacts({ companyId: companyId || undefined, q: query || undefined, dueOnly })
      .then((p) => mine === latest.current && setPage(p))
      .catch((e) => mine === latest.current && setError(e instanceof Error ? e.message.slice(0, 200) : String(e)))
  }, [companyId, query, dueOnly, reloadKey, bump])

  const rows = page?.rows ?? []
  const groups = new Map<string, ContactRowDTO[]>()
  if (grouped) for (const r of rows) groups.set(r.company_name, [...(groups.get(r.company_name) ?? []), r])
  const called = () => {
    setBump((b) => b + 1)
    onCalled()
  }

  return (
    <Panel className="p-4">
      <form
        className="mb-3 flex flex-wrap items-center gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          setQuery(q.trim())
        }}
      >
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-cockpit-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('Name, Rolle oder Unternehmen')} className={cn(FIELD, 'pl-8')} />
        </div>
        <select value={companyId} onChange={(e) => setCompanyId(e.target.value)} className={cn(FIELD, 'w-auto min-w-[200px]')} aria-label={t('Unternehmen')}>
          <option value="">{t('Alle Unternehmen')}</option>
          {(page?.companies ?? []).map((c) => (
            <option key={c.company_id} value={c.company_id}>
              {c.name} ({c.contacts})
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-[13px] text-cockpit-dim">
          <input type="checkbox" checked={dueOnly} onChange={(e) => setDueOnly(e.target.checked)} className="accent-mint-500" />
          {t('nur fällige Rückrufe')}
        </label>
        <label className="flex items-center gap-2 text-[13px] text-cockpit-dim">
          <input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} className="accent-mint-500" />
          {t('nach Unternehmen gruppieren')}
        </label>
        <Button type="submit">{t('Suchen')}</Button>
      </form>
      {error && <p className="text-[13px] text-coral-400">{error}</p>}
      {page && (
        <p className="mb-2 font-mono text-[12px] text-cockpit-faint">
          {page.truncated
            ? t('{n} von {total} Kontakten', { n: String(rows.length), total: String(page.total) })
            : t('{n} Kontakte', { n: String(page.total) })}
        </p>
      )}
      {page && rows.length === 0 ? (
        <p className="text-[13px] text-cockpit-dim">{t('Noch keine Kontakte — im Markt eine Person übernehmen oder im Tab „Aus Anzeigen“ anrufen.')}</p>
      ) : grouped ? (
        [...groups.entries()].map(([name, people]) => (
          <div key={name} className="mb-3">
            <h3 className="flex items-center gap-2 border-b border-cockpit-line/60 pb-1 text-[14px] font-medium text-cockpit-text">
              <Building2 className="h-4 w-4 text-cockpit-faint" />
              {name}
              <span className="font-mono text-[12px] text-cockpit-faint">{people.length}</span>
            </h3>
            <ul>
              {people.map((r) => (
                <ContactRow key={r.manager_id} row={r} showCompany={false} onCalled={called} />
              ))}
            </ul>
          </div>
        ))
      ) : (
        <ul>
          {rows.map((r) => (
            <ContactRow key={r.manager_id} row={r} showCompany onCalled={called} />
          ))}
        </ul>
      )}
    </Panel>
  )
}

export function ContactListScreen() {
  const [tab, setTab] = useState<Tab>('contacts')
  const [contactsReload, setContactsReload] = useState(0)
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [phoneOnly, setPhoneOnly] = useState(true)
  const [rows, setRows] = useState<CallListRowDTO[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [nextOffset, setNextOffset] = useState(0)
  // Only the newest request may write the list: a "Mehr laden" still in
  // flight when the filter changes must not append the old search's rows.
  const latest = useRef(0)
  const [followUps, setFollowUps] = useState<FollowUpDTO[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [art14, setArt14] = useState(false)

  const loadMarket = useCallback(
    async (offset: number) => {
      const mine = ++latest.current
      setLoading(true)
      setError(null)
      try {
        const page = await api.callListMarket({ q: query, phoneOnly, offset, limit: 50 })
        if (mine !== latest.current) return
        setRows((prev) => (offset === 0 ? page.rows : [...prev, ...page.rows]))
        setHasMore(page.has_more)
        setNextOffset(page.next_offset)
      } catch (e) {
        if (mine === latest.current) setError(e instanceof Error ? e.message.slice(0, 200) : String(e))
      } finally {
        if (mine === latest.current) setLoading(false)
      }
    },
    [query, phoneOnly],
  )

  const loadFollowUps = useCallback(async () => {
    try {
      setFollowUps(await api.callListFollowUps())
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : String(e))
    }
  }, [])

  useEffect(() => {
    void loadMarket(0)
  }, [loadMarket])
  useEffect(() => {
    void loadFollowUps()
  }, [loadFollowUps])

  const due = followUps.filter((f) => f.due).length

  return (
    <div className="space-y-5">
      <SectionHeader
        title={t('Kontaktliste')}
        hint={t('Ihre Kontakte, wer in offenen Anzeigen als Ansprechpartner genannt ist — und was beim letzten Anruf herauskam.')}
        icon={<Users className="h-4 w-4" />}
      />

      <SegmentedControl<Tab>
        value={tab}
        onChange={setTab}
        options={[
          { key: 'contacts', label: t('Kontakte') },
          { key: 'market', label: t('Aus Anzeigen') },
          { key: 'follow_ups', label: due ? t('Wiedervorlage ({n} fällig)', { n: String(due) }) : t('Wiedervorlage') },
        ]}
      />

      {art14 && (
        <p className="text-[12px] leading-relaxed text-gold-400">
          {t('Kontakt übernommen. Er stammt aus einer öffentlichen Anzeige — eine Information nach Art. 14 DSGVO ist fällig und unter „Manager“ vorgemerkt.')}
        </p>
      )}
      {error && <p className="text-[13px] text-coral-400">{error}</p>}

      {tab === 'contacts' ? (
        <ContactsTab reloadKey={contactsReload} onCalled={() => void loadFollowUps()} />
      ) : tab === 'market' ? (
        <Panel className="p-4">
          <form
            className="mb-3 flex flex-wrap items-center gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              setQuery(q.trim())
            }}
          >
            <div className="relative min-w-[220px] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-cockpit-faint" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={t('Unternehmen oder Name')}
                className={cn(FIELD, 'pl-8')}
              />
            </div>
            <label className="flex items-center gap-2 text-[13px] text-cockpit-dim">
              <input type="checkbox" checked={phoneOnly} onChange={(e) => setPhoneOnly(e.target.checked)} className="accent-mint-500" />
              {t('nur mit Telefonnummer')}
            </label>
            <Button type="submit">{t('Suchen')}</Button>
          </form>
          {rows.length === 0 && !loading ? (
            <p className="text-[13px] text-cockpit-dim">{t('Niemand auf der Liste — oder alle schon angerufen.')}</p>
          ) : (
            <ul>
              {rows.map((row) => (
                <MarketRow
                  key={`${row.hub_company_id}:${row.person_key}`}
                  row={row}
                  onCalled={(owes) => {
                    setRows((prev) => prev.filter((r) => r !== row))
                    if (owes) setArt14(true)
                    void loadFollowUps()
                    // The person is a contact now: the Kontakte tab re-reads.
                    setContactsReload((k) => k + 1)
                  }}
                />
              ))}
            </ul>
          )}
          {hasMore && (
            <div className="mt-3">
              <Button onClick={() => loadMarket(nextOffset)} disabled={loading}>
                {t('Mehr laden')}
              </Button>
            </div>
          )}
          {loading && <p className="mt-2 font-mono text-[12px] text-cockpit-faint">{t('lädt…')}</p>}
        </Panel>
      ) : (
        <Panel className="p-4">
          {followUps.length === 0 ? (
            <p className="text-[13px] text-cockpit-dim">{t('Noch keine Anrufe erfasst.')}</p>
          ) : (
            <ul>
              {followUps.map((row) => (
                <FollowUpRow key={row.manager_id} row={row} onCalled={() => void loadFollowUps()} />
              ))}
            </ul>
          )}
        </Panel>
      )}
    </div>
  )
}
