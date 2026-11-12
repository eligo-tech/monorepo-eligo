// "Leads" (ELI-23, ELI-29): NEW contacts taken from Markt — people a public
// job ad names — not yet vetted managers, newest first. "Zu Managern" moves
// the person to the Manager screen (same record, nothing copied). Per company
// they are on the company page in Unternehmen (`CompanyScreen`, ELI-33).


import { t } from '@/i18n'
import { locale } from '@/i18n/format'

import { useEffect, useRef, useState } from 'react'
import { ExternalLink, Mail, Phone, PhoneCall, Search, UserCheck, Users } from 'lucide-react'
import { ApiError, api } from '@/api/client'
import type { ContactPageDTO, ContactRowDTO, SwitchboardDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Button, FIELD, SelectInput } from '../ui/forms'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import {
  CALL_OUTCOMES,
  CALL_OUTCOME_TONE,
  callOutcomeLabel,
  canSaveCall,
  needsDate,
} from '../ui/callOutcomes'
import { networkLinks } from '../ui/contactReach'
import { leadPhone } from '../ui/switchboard'
import { ImpressumBadge } from '../ui/SwitchboardLine'
import { NetworkLink } from './ContactsPanel'

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

function PhoneLink({ phone, kind }: { phone: string | null; kind?: string | null }) {
  if (!phone) return <span className="text-cockpit-faint">{t('keine Nummer')}</span>
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

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(locale(), { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—'

/** One contact in this workspace — how to reach them, where they came from,
 *  and how the last call went. */
function ContactRow({
  row,
  showCompany,
  onCalled,
  switchboard,
}: {
  row: ContactRowDTO
  showCompany: boolean
  onCalled: () => void
  /** ELI-30: the company's Impressum switchboard, dialled when the lead has no number. */
  switchboard?: SwitchboardDTO | null
}) {
  const reach = leadPhone(row.phone, switchboard)
  const [calling, setCalling] = useState(false)
  const [moving, setMoving] = useState(false)
  const [moveFailed, setMoveFailed] = useState(false)
  // GDPR Art. 14: the notice is owed from adoption, not from vetting — so it
  // is recorded here, before the person ever reaches Managers.
  const markNotified = async () => {
    setMoving(true)
    setMoveFailed(false)
    try {
      await api.markManagerArt14Notified(row.manager_id)
      onCalled()
    } catch {
      setMoveFailed(true)
    } finally {
      setMoving(false)
    }
  }
  const links = networkLinks(row)
  const promote = async () => {
    setMoving(true)
    setMoveFailed(false)
    try {
      await api.promoteManager(row.manager_id)
      onCalled() // re-read: the person now lives under Manager
    } catch {
      setMoveFailed(true)
    } finally {
      setMoving(false)
    }
  }
  return (
    <li className={cn('border-b border-cockpit-line/40 py-3 last:border-0', row.due && 'bg-gold-500/[0.04]')}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[15px] font-medium text-cockpit-text">{row.full_name}</span>
        {row.role_title && <span className="text-[13px] text-cockpit-dim">{row.role_title}</span>}
        {row.last_outcome && <Chip tone={CALL_OUTCOME_TONE[row.last_outcome]}>{callOutcomeLabel(row.last_outcome)}</Chip>}
        {row.art14_outstanding && (
          <>
            <Chip tone="gold">
              <span title={t('Aus einer öffentlichen Anzeige übernommen — die Information nach Art. 14 DSGVO steht noch aus.')}>
                {t('Art. 14 offen')}
              </span>
            </Chip>
            <button
              type="button"
              onClick={markNotified}
              disabled={moving}
              className="font-mono text-[11px] text-cockpit-faint underline hover:text-mint-400"
            >
              {t('Als informiert markieren')}
            </button>
          </>
        )}
        <span className="ml-auto font-mono text-[12px] text-cockpit-faint">
          {showCompany && (
            <>
              <a href={`#companies/${row.company_id}`} className="hover:text-mint-400" title={t('Zur Firmenseite')}>
                {row.company_name}
              </a>{' '}
              ·{' '}
            </>
          )}
          {t('übernommen am {date}', { date: day(row.added_at) })}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[12px] text-cockpit-dim">
        <span className="flex items-center gap-2">
          <PhoneLink phone={reach.phone} />
          {reach.fromImpressum && <ImpressumBadge />}
        </span>
        {row.email && (
          <a href={`mailto:${row.email}`} className="flex items-center gap-1 hover:text-mint-400">
            <Mail className="h-3.5 w-3.5 text-cockpit-faint" />
            {row.email}
          </a>
        )}
        <NetworkLink href={links.linkedin.href} profile={links.linkedin.profile} label="LinkedIn" className="bg-[#0a66c2]" />
        <NetworkLink href={links.xing.href} profile={links.xing.profile} label="XING" className="bg-[#006567]" />
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
          <span className="ml-auto flex items-center gap-2">
            {moveFailed && <span className="text-coral-400">{t('Speichern fehlgeschlagen.')}</span>}
            <span title={t('Erstkontakt erledigt — als Manager übernehmen.')}>
              <Button onClick={promote} disabled={moving}>
                <UserCheck className="h-4 w-4" />
                {t('Zu Managern')}
              </Button>
            </span>
            <Button onClick={() => setCalling(true)}>
              <PhoneCall className="h-4 w-4" />
              {t('Anruf erfassen')}
            </Button>
          </span>
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

/** Everyone adopted from Markt in this workspace, newest first. */
function ContactsTab() {
  const [page, setPage] = useState<ContactPageDTO | null>(null)
  const [companyId, setCompanyId] = useState('')
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [dueOnly, setDueOnly] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)
  const [bump, setBump] = useState(0)

  useEffect(() => {
    const mine = ++latest.current
    api
      .callListContacts({ companyId: companyId || undefined, q: query || undefined, dueOnly })
      .then((p) => {
        if (mine !== latest.current) return
        setPage(p)
        setError(null)
      })
      .catch((e) => mine === latest.current && setError(e instanceof Error ? e.message.slice(0, 200) : String(e)))
  }, [companyId, query, dueOnly, bump])

  const rows = page?.rows ?? []
  const boards = new Map((page?.companies ?? []).map((c) => [c.company_id, c.switchboard ?? null]))
  const filtering = Boolean(companyId || query || dueOnly)
  const called = () => setBump((b) => b + 1)

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
        <p className="text-[13px] text-cockpit-dim">
          {filtering
            ? t('Keine Kontakte für diese Auswahl.')
            : t('Noch keine Kontakte — im Markt bei einem Unternehmen „Ansprechpartner“ öffnen und eine Person übernehmen.')}
        </p>
      ) : (
        <ul>
          {rows.map((r) => (
            <ContactRow key={r.manager_id} row={r} showCompany onCalled={called} switchboard={boards.get(r.company_id)} />
          ))}
        </ul>
      )}
    </Panel>
  )
}

export function ContactListScreen() {
  return (
    <div className="space-y-5">
      <SectionHeader
        title={t('Leads')}
        hint={t('Neue Kontakte aus dem Markt — noch keine geprüften Manager. Nach dem Erstkontakt „Zu Managern“.')}
        icon={<Users className="h-4 w-4" />}
      />
      <ContactsTab />
    </div>
  )
}
