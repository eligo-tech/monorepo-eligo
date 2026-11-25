// "Leads" (ELI-23, ELI-29): NEW contacts taken from Markt — people a public
// job ad names — or entered by hand with "+ Lead" (ELI-65, marked "manuell");
// not yet vetted managers; open call-backs first (ELI-38), then
// newest first. "Zu Managern" moves the person to the Manager screen (same
// record, nothing copied). Per company
// they are on the company page in Unternehmen (`CompanyScreen`, ELI-33).


import { t } from '@/i18n'
import { locale } from '@/i18n/format'

import { useEffect, useRef, useState } from 'react'
import { BellPlus, Briefcase, ExternalLink, Mail, Phone, PhoneCall, Plus, Search, UserCheck, Users } from 'lucide-react'
import { ApiError, api } from '@/api/client'
import { useActorLabel, useCreatorLabel } from '@/auth/memberNames'
import type { ContactPageDTO, ContactRowDTO, NoteCountsDTO, SwitchboardDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Button, FIELD, SelectInput } from '../ui/forms'
import { Chip, Panel, SectionHeader } from '../ui/primitives'
import {
  CALL_OUTCOMES,
  CALL_OUTCOME_TONE,
  callOutcomeLabel,
  canSaveCall,
  needsDate,
  nextCallInstant,
} from '../ui/callOutcomes'
import { networkLinks } from '../ui/contactReach'
import { leadJobLine, mandateHref } from '../ui/leadJobs'
import { leadPhone } from '../ui/switchboard'
import { ImpressumBadge } from '../ui/SwitchboardLine'
import { NetworkLink } from './ContactsPanel'
import { DoNotContactChip } from '../erasure/DoNotContact'
import { NoInterestChip, RemoveLeadButton, ReviveLeadButton } from '../leads/NoInterest'
import { ManualLeadChip, NewLead } from '../leads/NewLead'
import { AddPhoneButton, AddPhoneForm } from '../leads/AddLeadPhone'
import { phoneKindLabel } from '../ui/phoneList'
import { FollowUpForm } from '../ui/FollowUpForm'
import { CreatedByChip, CreatedByFilter, sortByCreator } from '../ui/createdBy'
import { useCreators } from '../data/useCreators'
import { DateField } from '../ui/DateField'
import { announceFollowUpsChanged, followUpWhen, localIsoDate } from '../ui/followUps'
import { NoteFollowUpOffer, type SavedNote } from '../followups/NoteFollowUpOffer'
import { readDateFromText, useOpenFollowUps } from '../followups/useFollowUps'
import type { FollowUpDTO } from '@/api/types'

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

/** Outcome, optional next day, optional note — then save. "Nicht erreicht"
 *  needs nothing else (ELI-35). */
function CallForm({
  onSave,
  onCancel,
}: {
  onSave: (outcome: string, nextAt: string | null, note: string, doNotContact: boolean) => Promise<void>
  onCancel: () => void
}) {
  const [outcome, setOutcome] = useState<string>('')
  // ELI-32: the person asked not to be called again.
  const [doNotContact, setDoNotContact] = useState(false)
  const [nextAt, setNextAt] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await onSave(outcome, nextCallInstant(nextAt), note.trim(), doNotContact)
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
        {/* ELI-35: a day — "Uhrzeit ist nicht relevant". */}
        <DateField value={nextAt} onChange={setNextAt} className={FIELD} />
      </label>
      <label className="block min-w-0 sm:col-span-2">
        <span className="mb-1 block font-mono text-[11px] uppercase tracking-wide text-cockpit-faint">{t('Notiz (optional)')}</span>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className={FIELD} />
      </label>
      <label className="flex items-start gap-2 text-[13px] text-cockpit-dim sm:col-span-2">
        <input
          type="checkbox"
          checked={doNotContact}
          onChange={(e) => setDoNotContact(e.target.checked)}
          className="mt-1"
        />
        <span>
          <span className="text-coral-300">{t('Nicht mehr kontaktieren')}</span>
          {' — '}
          {t('die Person möchte keinen Kontakt mehr. Löschen (DSGVO) auf der Manager-Seite.')}
        </span>
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
export function ContactRow({
  row,
  showCompany,
  onCalled,
  switchboard,
  followUp,
  offer,
  onOffer,
  onOfferClose,
}: {
  row: ContactRowDTO
  showCompany: boolean
  onCalled: () => void
  /** ELI-44: this lead's next open Wiedervorlage, if any. */
  followUp?: FollowUpDTO | null
  /** ELI-44: the note of the call just logged, while its date is on offer.
   *  Held by the list, not the row: the refetch after a call can take the
   *  row off a filtered list, and the offer must outlive it. */
  offer?: SavedNote | null
  onOffer?: (note: SavedNote) => void
  onOfferClose?: () => void
  /** ELI-30: the company's Impressum switchboard, dialled when the lead has no number. */
  switchboard?: SwitchboardDTO | null
}) {
  const reach = leadPhone(row.phone, switchboard)
  const callerName = useActorLabel()(row.last_call_by)
  const [calling, setCalling] = useState(false)
  // ELI-76: "+ Nummer" — a number found while calling, saved on the row.
  const [addingPhone, setAddingPhone] = useState(false)
  const morePhones = (row.phones ?? []).filter((p) => !p.is_primary)
  // ELI-44: a follow-up by hand, and the offer read from a call's note.
  const [planning, setPlanning] = useState(false)
  const today = localIsoDate()
  const [moving, setMoving] = useState(false)
  const [moveFailed, setMoveFailed] = useState(false)
  // GDPR Art. 14 (ELI-49): the notice is still owed from adoption, but it is
  // shown and recorded on the Manager page, not on this calling list.
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
        {/* ELI-66: the lead's page — every field is edited there. */}
        <a
          href={`#managers/${row.manager_id}`}
          className="text-[15px] font-medium text-cockpit-text hover:text-mint-400"
          title={t('Lead öffnen — Daten bearbeiten')}
        >
          {row.full_name}
        </a>
        {row.role_title && <span className="text-[13px] text-cockpit-dim">{row.role_title}</span>}
        {/* ELI-65: entered by hand with "+ Lead", not taken from Markt. */}
        {row.manual && <ManualLeadChip source={row.source_detail} />}
        {/* ELI-69: who added this lead — nothing when unknown. */}
        <CreatedByChip userId={row.created_by_user_id} name={row.created_by_name} />
        {row.do_not_contact_at && <DoNotContactChip since={row.do_not_contact_at} />}
        {row.no_interest_at && <NoInterestChip since={row.no_interest_at} reason={row.removed_reason} />}
        {row.last_outcome && <Chip tone={CALL_OUTCOME_TONE[row.last_outcome]}>{callOutcomeLabel(row.last_outcome)}</Chip>}
        {/* ELI-38: the open next call is the lead's status — on the name
            line, and kept by the backend until a call reaches the person. */}
        {row.next_action_at && (
          <Chip tone={row.due ? 'gold' : undefined}>
            {row.due ? t('Fällig seit') : t('Nächster Anruf')}: {day(row.next_action_at)}
          </Chip>
        )}
        {followUp && (
          <Chip tone={followUp.due_date < today ? 'coral' : followUp.due_date === today ? 'gold' : undefined}>
            <span title={followUp.text}>
              {t('Wiedervorlage')}: {(({ date, time }) => [date, time].filter(Boolean).join(' '))(followUpWhen(followUp))}
            </span>
          </Chip>
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
          {row.manual
            ? t('angelegt am {date}', { date: day(row.added_at) })
            : t('übernommen am {date}', { date: day(row.added_at) })}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[12px] text-cockpit-dim">
        <span className="flex items-center gap-2">
          <PhoneLink phone={reach.phone} />
          {reach.fromImpressum && <ImpressumBadge />}
        </span>
        {/* ELI-76: the further numbers, so one just added shows here. */}
        {morePhones.map((p) => (
          <span key={p.number} className="flex items-center gap-1.5">
            <a href={`tel:${p.number.replace(/[^\d+]/g, '')}`} className="flex items-center gap-1 text-cockpit-text hover:text-mint-400">
              <Phone className="h-3.5 w-3.5 text-cockpit-faint" />
              {p.number}
            </a>
            <span className="text-[11px] text-cockpit-faint">{phoneKindLabel(p.kind)}</span>
          </span>
        ))}
        {!addingPhone && <AddPhoneButton onClick={() => setAddingPhone(true)} />}
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
        {/* ELI-65: the link it came from — unless the job already links to it. */}
        {row.manual && row.source_detail?.startsWith('http') && !row.jobs?.some((j) => j.url === row.source_detail) && (
          <a href={row.source_detail} target="_blank" rel="noreferrer noopener" className="flex items-center gap-1 hover:text-mint-400">
            <ExternalLink className="h-3 w-3" />
            {t('Quelle')}
          </a>
        )}
        {row.last_call_at && (
          <span>
            {t('Zuletzt')}: {when(row.last_call_at)}
            {callerName ? ` · ${callerName}` : ''}
          </span>
        )}
        {/* ELI-62: how much has happened with the lead. */}
        {row.last_note_at ? (
          <span>
            {t('Letzte Notiz')}: {day(row.last_note_at)} ·{' '}
            {row.note_count === 1 ? t('1 Notiz') : t('{n} Notizen', { n: String(row.note_count ?? 0) })}
          </span>
        ) : (
          // Only the free-text note — why the lead is under "Mit Notizen".
          row.has_notes && <span>{t('Notiz vorhanden')}</span>
        )}
        {!calling && (
          <span className="ml-auto flex items-center gap-2">
            {moveFailed && <span className="text-coral-400">{t('Speichern fehlgeschlagen.')}</span>}
            {/* ELI-60: back on the list first — then everything else. */}
            {row.no_interest_at ? (
              <ReviveLeadButton managerId={row.manager_id} onRevived={onCalled} />
            ) : (
              <>
                <span title={t('Erstkontakt erledigt — als Manager übernehmen.')}>
                  <Button onClick={promote} disabled={moving}>
                    <UserCheck className="h-4 w-4" />
                    {t('Zu Managern')}
                  </Button>
                </span>
                {/* ELI-66: hidden with a reason, never deleted. */}
                <RemoveLeadButton managerId={row.manager_id} onRemoved={onCalled} />
              </>
            )}
            <Button onClick={() => setPlanning((p) => !p)}>
              <BellPlus className="h-4 w-4" />
              {t('Wiedervorlage')}
            </Button>
            <Button onClick={() => setCalling(true)}>
              <PhoneCall className="h-4 w-4" />
              {t('Anruf erfassen')}
            </Button>
          </span>
        )}
      </div>
      {row.jobs && row.jobs.length > 0 && (
        // ELI-37: which job the lead is about — the ads naming them, and the
        // workspace's own job taken from one or owned by them.
        <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[12px] text-cockpit-dim">
          {row.jobs.map((job) => {
            const own = mandateHref(job)
            return (
              <li key={job.posting_id ?? job.job_id ?? job.title} className="flex items-center gap-1.5">
                <Briefcase className="h-3.5 w-3.5 text-cockpit-faint" />
                {job.url ? (
                  <a href={job.url} target="_blank" rel="noreferrer noopener" className="hover:text-mint-400" title={t('Anzeige öffnen')}>
                    {leadJobLine(job)}
                  </a>
                ) : (
                  <span>{leadJobLine(job)}</span>
                )}
                {own && (
                  <a href={own} title={t('Unter Mandate öffnen')}>
                    <Chip tone="mint">{t('Mandat')}</Chip>
                  </a>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {addingPhone && (
        <AddPhoneForm
          managerId={row.manager_id}
          onCancel={() => setAddingPhone(false)}
          onSaved={() => {
            setAddingPhone(false)
            onCalled() // re-read: the number shows on the row
          }}
        />
      )}
      {calling && (
        <CallForm
          onCancel={() => setCalling(false)}
          onSave={async (outcome, nextAt, note, doNotContact) => {
            const logged = await api.logManagerInteraction(row.manager_id, {
              interaction_type: 'business_call',
              summary: note,
              outcome,
              next_action_at: nextAt,
              do_not_contact: doNotContact,
            })
            setCalling(false)
            // ELI-44/48: offer a Wiedervorlage after every call — the date the
            // note names ("Anfang Februar"), else a week out, editable.
            // ELI-32: not to someone who asked not to be contacted again.
            if (!doNotContact) onOffer?.(logged)
            onCalled()
          }}
        />
      )}
      {planning && (
        <div className="mt-2">
          <FollowUpForm
            defaultDate={today}
            readDate={readDateFromText}
            onCancel={() => setPlanning(false)}
            onSave={async (f) => {
              await api.createFollowUp({ manager_id: row.manager_id, ...f, origin: 'manual' })
              setPlanning(false)
              announceFollowUpsChanged()
            }}
          />
        </div>
      )}
      {offer && (
        <div className="mt-2">
          <NoteFollowUpOffer subject={{ managerId: row.manager_id }} note={offer} onClose={() => onOfferClose?.()} />
        </div>
      )}
    </li>
  )
}

export type NotesChoice = '' | 'none' | 'with'

/** ELI-62: Alle · Noch keine Notiz · Mit Notizen — each with how many leads
 *  it would list under the other filters (counted by the backend). */
export function NotesFilter({
  value,
  counts,
  onChange,
}: {
  value: NotesChoice
  counts: NoteCountsDTO | null
  onChange: (value: NotesChoice) => void
}) {
  const options: { value: NotesChoice; label: string; n?: number }[] = [
    { value: '', label: t('Alle'), n: counts?.all },
    { value: 'none', label: t('Noch keine Notiz'), n: counts?.none },
    { value: 'with', label: t('Mit Notizen'), n: counts?.with },
  ]
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('Notizen')}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          aria-pressed={value === o.value}
          title={o.value === 'with' ? t('Neueste Notiz zuerst') : undefined}
          className={cn(
            'rounded-lg border px-2.5 py-1.5 font-mono text-[12px] transition-colors',
            value === o.value
              ? 'border-cockpit-edge bg-white/[0.06] text-cockpit-text'
              : 'border-cockpit-line text-cockpit-faint hover:text-cockpit-dim',
          )}
        >
          {o.label}
          {o.n !== undefined && (
            <>
              {' '}
              <span className="text-cockpit-dim">{o.n}</span>
            </>
          )}
        </button>
      ))}
    </div>
  )
}

/** Everyone adopted from Markt in this workspace, and the leads entered by
 *  hand (ELI-65) — open call-backs first, then newest. */
function ContactsTab() {
  const [page, setPage] = useState<ContactPageDTO | null>(null)
  const [companyId, setCompanyId] = useState('')
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [dueOnly, setDueOnly] = useState(false)
  const [notes, setNotes] = useState<NotesChoice>('')
  // ELI-60: "Kein Interesse" leads are hidden unless this chip is on.
  const [noInterest, setNoInterest] = useState(false)
  // ELI-69: "Angelegt von" — '' Alle, 'me' Ich, else an account id.
  const [createdBy, setCreatedBy] = useState('')
  // ELI-70: the server's order (open call-backs, then newest), or grouped
  // by who added the lead — by the e-mail shown on the chip.
  const [sort, setSort] = useState<'' | 'creator'>('')
  const creatorLabel = useCreatorLabel()
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)
  const [bump, setBump] = useState(0)
  const creators = useCreators('leads', bump)
  // ELI-65: "+ Lead" — a lead entered by hand.
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    const mine = ++latest.current
    api
      .callListContacts({
        companyId: companyId || undefined,
        q: query || undefined,
        dueOnly,
        notes: notes || undefined,
        noInterest,
        createdBy: createdBy || undefined,
      })
      .then((p) => {
        if (mine !== latest.current) return
        setPage(p)
        setError(null)
      })
      .catch((e) => mine === latest.current && setError(e instanceof Error ? e.message.slice(0, 200) : String(e)))
  }, [companyId, query, dueOnly, notes, noInterest, createdBy, bump])

  const loaded = page?.rows ?? []
  const rows = sort === 'creator' ? sortByCreator(loaded, creatorLabel) : loaded
  // ELI-44: each lead's next open Wiedervorlage — one call for the page.
  const { rows: followUps } = useOpenFollowUps()
  const nextFollowUp = new Map<string, FollowUpDTO>()
  for (const f of followUps ?? []) {
    if (f.manager_id && !nextFollowUp.has(f.manager_id)) nextFollowUp.set(f.manager_id, f)
  }
  const [offers, setOffers] = useState<Map<string, { note: SavedNote; name: string }>>(new Map())
  const closeOffer = (managerId: string) =>
    setOffers((prev) => {
      const next = new Map(prev)
      next.delete(managerId)
      return next
    })
  const shown = new Set(rows.map((r) => r.manager_id))
  const boards = new Map((page?.companies ?? []).map((c) => [c.company_id, c.switchboard ?? null]))
  const filtering = Boolean(companyId || query || dueOnly || notes || noInterest || createdBy)
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
        <CreatedByFilter
          value={createdBy}
          onChange={(v) => {
            // The company list is cut by the creator too: a chosen company may not be in it.
            setCompanyId('')
            setCreatedBy(v)
          }}
          creators={creators}
        />
        <label className="flex items-center gap-2 font-mono text-[12px] text-cockpit-faint">
          {t('Sortieren')}
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value === 'creator' ? 'creator' : '')}
            className={cn(FIELD, 'w-auto min-w-[140px]')}
            aria-label={t('Sortieren')}
          >
            <option value="">{t('Rückrufe, dann neueste')}</option>
            <option value="creator">{t('Angelegt von')}</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-[13px] text-cockpit-dim">
          <input type="checkbox" checked={dueOnly} onChange={(e) => setDueOnly(e.target.checked)} className="accent-mint-500" />
          {t('nur fällige Rückrufe')}
        </label>
        <button
          type="button"
          aria-pressed={noInterest}
          onClick={() => setNoInterest((v) => !v)}
          title={t('Entfernte Leads und Leads mit „Kein Interesse“ — ausgeblendet, aber gespeichert.')}
          className={cn(
            'rounded-md border px-2 py-0.5 font-mono text-[12px] transition-colors',
            noInterest
              ? 'border-mint-500 text-mint-400'
              : 'border-cockpit-line text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text',
          )}
        >
          {t('Ausgeblendet')}
          {page?.no_interest_total ? ` (${page.no_interest_total})` : ''}
        </button>
        <Button type="submit">{t('Suchen')}</Button>
        <Button tone="primary" onClick={() => setAdding((a) => !a)}>
          <Plus className="h-4 w-4" />
          {t('Lead')}
        </Button>
      </form>
      {adding && (
        <div className="mb-3">
          <NewLead
            onCancel={() => setAdding(false)}
            onSaved={() => {
              setAdding(false)
              called()
            }}
          />
        </div>
      )}
      <div className="mb-3">
        <NotesFilter value={notes} counts={page?.note_counts ?? null} onChange={setNotes} />
      </div>
      {error && <p className="text-[13px] text-coral-400">{error}</p>}
      {[...offers].filter(([id]) => !shown.has(id)).map(([id, { note, name }]) => (
        <div key={id} className="mb-3 space-y-1">
          <p className="font-mono text-[11px] text-cockpit-faint">{name}</p>
          <NoteFollowUpOffer subject={{ managerId: id }} note={note} onClose={() => closeOffer(id)} />
        </div>
      ))}
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
            : t('Noch keine Kontakte — im Markt bei einem Unternehmen „Ansprechpartner“ öffnen und eine Person übernehmen, oder mit „+ Lead“ von Hand anlegen.')}
        </p>
      ) : (
        <ul>
          {rows.map((r) => (
            <ContactRow
              key={r.manager_id}
              row={r}
              showCompany
              onCalled={called}
              switchboard={boards.get(r.company_id)}
              followUp={nextFollowUp.get(r.manager_id)}
              offer={offers.get(r.manager_id)?.note ?? null}
              onOffer={(note) => setOffers((prev) => new Map(prev).set(r.manager_id, { note, name: r.full_name }))}
              onOfferClose={() => closeOffer(r.manager_id)}
            />
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
        hint={t('Neue Kontakte aus dem Markt oder von Hand angelegt — noch keine geprüften Manager. Nach dem Erstkontakt „Zu Managern“.')}
        icon={<Users className="h-4 w-4" />}
      />
      <ContactsTab />
    </div>
  )
}
