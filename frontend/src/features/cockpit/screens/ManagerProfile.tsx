// One manager's profile — layout after Design.pdf, palette from the cockpit.
//
// The ordering is the argument. A recruiter opening this record is about to
// pick up the phone, so identity comes first, then the numbers that decide
// whether to call, then the conversation itself.
//
// Three things this deliberately does NOT do:
//
//   * It does not repeat the newest note above the list. An earlier version had
//     a "last discussed" banner carrying the same text that appeared again two
//     inches below — the reader has to check whether they are the same thing,
//     which costs more than the banner saved.
//   * It does not invent "next move". The mock shows one; the API has no such
//     field, and deriving it from note text would be a guess set in 22px type.
//   * It does not headline aiFind's record id. MNGR197 means something in the
//     system this was imported from and nothing here, so it sits in the record
//     panel where a cross-reference belongs, not beside the person's name.

import { locale } from '@/i18n/format'

import { t } from '@/i18n'

import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  Briefcase,
  Building2,
  CalendarDays,
  Check,
  ExternalLink,
  Mail,
  MapPin,
  Pencil,
  Phone,
  Plus,
  ShieldAlert,
  X,
} from 'lucide-react'
import { ApiError, api } from '@/api/client'
import type { CompanyMarketDTO, ManagerDTO, ManagerInteractionDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Chip } from '../ui/primitives'
import { EraseSection } from '../erasure/EraseSection'
import { DoNotContactBanner } from '../erasure/DoNotContact'
import { NoInterestChip, RemoveLeadButton, ReviveLeadButton } from '../leads/NoInterest'
import { ManualLeadChip } from '../leads/NewLead'
import { isAdmin, useMe } from '../useMe'
import { useAsync } from '@/hooks/useAsync'
import { CareersLink, OpenJobs } from '../ui/OpenJobsList'
import { InteractionComposer } from '../ui/InteractionComposer'
import { PersonFollowUps } from '../followups/PersonFollowUps'
import { NoteFollowUpOffer, type SavedNote } from '../followups/NoteFollowUpOffer'
import {
  MANAGER_INTERACTION_KINDS,
  interactionLabel,
  isContact,
} from '../ui/interactionKinds'
import { appointmentIcs, isAppointmentKind, splitAppointments } from '../ui/appointments'
import { announceFollowUpsChanged } from '../ui/followUps'
import { Button, SelectInput, TextInput } from '../ui/forms'
import { CONTACT_KEYS, ContactFields, contactDraftOf, contactPatch } from '../ui/contactFields'
import { PhoneList, PhoneListEditor, phonesOf, phonesPatch } from '../ui/phoneList'
import { ReaddDeclined, withReaddConfirm } from '../erasure/readd'

const dateDe = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString(locale(), {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      })
    : '—'

const timeDe = (iso: string) =>
  new Date(iso).toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' })

function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  return ms < 0 ? 0 : Math.floor(ms / 86_400_000)
}

/** Longer than this and a note is collapsed behind "mehr". The threshold is
 *  roughly one screenful: a meeting write-up should not push the rest of the
 *  history off the page, but nothing is truncated away permanently. */
const LONG_NOTE = 420

function Stat({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: string
  detail?: string | null
  tone?: 'coral'
}) {
  return (
    <div className="min-w-0 flex-1 border-r border-cockpit-line px-5 py-4 last:border-r-0">
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
        {label}
      </p>
      <p
        className={cn(
          'mt-1.5 truncate text-[22px] font-semibold leading-tight',
          tone === 'coral' ? 'text-coral-400' : 'text-cockpit-text',
        )}
      >
        {value}
      </p>
      {detail && (
        <p
          className={cn(
            'mt-0.5 truncate font-mono text-[12px]',
            tone === 'coral' ? 'text-coral-400' : 'text-cockpit-faint',
          )}
        >
          {detail}
        </p>
      )}
    </div>
  )
}

/** Renders nothing without a value: an empty row reads as "we checked and there
 *  is none", which is a different claim from "we never asked". */
function Line({ label, children }: { label: string; children: React.ReactNode }) {
  if (children === null || children === undefined || children === '') return null
  return (
    <div className="flex gap-3 py-1">
      <span className="w-[4rem] shrink-0 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
        {label}
      </span>
      <span className="min-w-0 flex-1 break-words text-[13px] leading-relaxed text-cockpit-text">
        {children}
      </span>
    </div>
  )
}

function RailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-cockpit-line px-5 py-4 last:border-b-0">
      <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
        {title}
      </p>
      {children}
    </section>
  )
}

/** One note. Long ones collapse, because a single meeting write-up otherwise
 *  buries every call around it. */
function Note({ entry }: { entry: ManagerInteractionDTO }) {
  const [open, setOpen] = useState(false)
  const text = entry.summary ?? ''
  const long = text.length > LONG_NOTE

  return (
    <li className="flex gap-5 border-b border-cockpit-line/60 px-6 py-4">
      <div className="w-[5.5rem] shrink-0">
        <p className="font-mono text-[13px] text-cockpit-text">
          {dateDe(entry.occurred_at)}
        </p>
        <p className="font-mono text-[11px] text-cockpit-faint">
          {timeDe(entry.occurred_at)}
        </p>
      </div>
      <div className="min-w-0 flex-1">
        {/* Labelled, not raw. The backend normalises every stored spelling
            onto one vocabulary ("BD Call" → `business_call`), so printing the
            column would now show a machine value where the recruiter's own
            word used to be. A kind nobody mapped still prints itself. */}
        <Chip>{interactionLabel(entry.interaction_type)}</Chip>
        <p
          className={cn(
            'mt-2 whitespace-pre-wrap text-[14px] leading-relaxed text-cockpit-dim',
            long && !open && 'line-clamp-4',
          )}
        >
          {text}
        </p>
        {long && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="mt-1.5 font-mono text-[12px] text-mint-400 transition-colors hover:text-mint-300"
          >
            {open ? t('weniger') : t('mehr')}
          </button>
        )}
      </div>
    </li>
  )
}

// `files` and `history` were here and are gone. Both were declared because
// the record has those dimensions, both rendered "nothing imported yet", and
// neither ever will be filled from this screen: attachments live on the
// candidate, and the history IS the notes list two tabs to the left. A tab
// that only ever says "empty" teaches people the tab bar is decorative.
type TabKey = 'notes' | 'jobs' | 'meetings' | 'deals'

export function ManagerProfile({
  manager: initial,
  companyName,
  onClose,
  onNotified,
  onErased,
}: {
  manager: ManagerDTO
  companyName: string
  onClose: () => void
  onNotified: (updated: ManagerDTO) => void
  /** The contact was erased (GDPR Art. 17): close, reload the list. */
  onErased?: () => void
}) {
  const [manager, setManager] = useState(initial)
  // ELI-66: the company can be changed on the page — its name follows.
  const [shownCompany, setShownCompany] = useState(companyName)
  useEffect(() => setShownCompany(companyName), [companyName])
  const [history, setHistory] = useState<ManagerInteractionDTO[] | null>(null)
  const [appointments, setAppointments] = useState<ManagerInteractionDTO[] | null>(null)
  const [tab, setTab] = useState<TabKey>('notes')
  const [composing, setComposing] = useState(false)
  /** ELI-44: the note just saved, while its follow-up date is on offer. */
  const [offerFor, setOfferFor] = useState<SavedNote | null>(null)
  const [busy, setBusy] = useState(false)
  // ELI-32: "Löschen (DSGVO)" in the composer opens the erase dialog.
  const [eraseOpen, setEraseOpen] = useState(false)
  const me = useMe()
  // One read of the company page for the sidebar: its open jobs (ELI-33) and
  // its Impressum switchboard, shown as "Zentrale (Firma)" (ELI-46).
  const companyPage = useAsync(() => api.companyPage(manager.company_id), [manager.company_id])

  useEffect(() => {
    let alive = true
    setManager(initial)
    setHistory(null)
    setAppointments(null)
    setTab('notes')
    setComposing(false)
    setOfferFor(null)
    setEraseOpen(false)
    api.manager(initial.id).then((m) => alive && setManager(m)).catch(() => {})
    api
      .managerInteractions(initial.id)
      .then((rows) => alive && setHistory(rows))
      .catch(() => alive && setHistory([]))
    api
      .managerAppointments(initial.id)
      .then((rows) => alive && setAppointments(rows))
      .catch(() => alive && setAppointments([]))
    return () => {
      alive = false
    }
  }, [initial])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !e.defaultPrevented && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const since = daysSince(manager.last_contact_at)
  const overdue = since !== null && since > 90
  const address = [
    manager.street,
    [manager.postal_code, manager.city].filter(Boolean).join(' '),
    manager.country,
  ]
    .filter(Boolean)
    .join(', ')
  const place = [manager.city, manager.country === 'Germany' ? 'DE' : manager.country]
    .filter(Boolean)
    .join(', ')

  const noteCount = manager.note_count ?? history?.length ?? 0
  const tabs = useMemo(
    () =>
      [
        { key: 'notes' as const, label: t('Notizen'), count: noteCount },
        { key: 'jobs' as const, label: t('Mandate'), count: manager.job_count ?? 0 },
        { key: 'meetings' as const, label: t('Termine'), count: appointments?.length ?? 0 },
        { key: 'deals' as const, label: 'Deals', count: 0 },
      ],
    [noteCount, manager.job_count, appointments],
  )

  const socials = [
    { label: 'LinkedIn', url: manager.linkedin_url },
    { label: 'Xing', url: manager.xing_url },
    { label: 'Facebook', url: manager.facebook_url },
  ].filter((s) => s.url)

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-cockpit-bg">
      <header className="border-b border-cockpit-line bg-cockpit-surface px-6 pb-5 pt-4">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
              <button
                type="button"
                onClick={onClose}
                className="flex items-center gap-1 transition-colors hover:text-cockpit-text"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                {t('Manager')}
              </button>
              {manager.art14_outstanding && (
                <>
                  <span>/</span>
                  <span className="text-gold-400">{t('Art. 14 offen')}</span>
                </>
              )}
              {(manager.duplicate_count ?? 1) > 1 && (
                <>
                  <span>/</span>
                  <span
                    className="text-gold-400"
                    title={t('Dieselbe E-Mail existiert mehrfach — in der Quelle doppelt angelegt')}
                  >
                    {manager.duplicate_count} {t('Datensätze')}
                  </span>
                </>
              )}
            </div>

            <h1 className="mt-2 truncate text-[44px] font-semibold leading-none tracking-tight text-cockpit-text">
              {manager.full_name}
            </h1>
            <p className="mt-2 flex flex-wrap items-center gap-x-1.5 text-[15px] text-cockpit-dim">
              {manager.role_title && <span>{manager.role_title}</span>}
              {shownCompany && shownCompany !== '—' && (
                <>
                  <span className="text-cockpit-faint">{t('bei')}</span>
                  <a
                    href={`#companies/${manager.company_id}`}
                    className="text-mint-400 underline-offset-4 hover:underline"
                    title={t('Zur Firmenseite')}
                  >
                    {shownCompany}
                  </a>
                </>
              )}
              {place && <span className="text-cockpit-faint">· {place}</span>}
            </p>
            {/* ELI-65: a lead entered by hand — the job it is about, and where it came from. */}
            {(manager.lead_job_title || manager.manual_lead) && (
              <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[12px] text-cockpit-dim">
                {manager.manual_lead && <ManualLeadChip source={manager.source_detail} />}
                {manager.lead_job_title && (
                  <span className="flex items-center gap-1.5">
                    <Briefcase className="h-3.5 w-3.5 text-cockpit-faint" />
                    {t('Job')}: {manager.lead_job_title}
                  </span>
                )}
                {manager.manual_lead && manager.source_detail?.startsWith('http') && (
                  <a
                    href={manager.source_detail}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="flex items-center gap-1 hover:text-mint-400"
                  >
                    <ExternalLink className="h-3 w-3" />
                    {t('Quelle')}
                  </a>
                )}
              </p>
            )}
          </div>

          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {manager.email && (
              <a
                href={`mailto:${manager.email}`}
                className="flex items-center gap-1.5 rounded-lg border border-cockpit-line px-3 py-2 font-mono text-[12px] uppercase tracking-wide text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
              >
                <Mail className="h-3.5 w-3.5" />
                {t('E-Mail')}
              </a>
            )}
            {manager.phone && (
              <a
                href={`tel:${manager.phone}`}
                className="flex items-center gap-1.5 rounded-lg border border-cockpit-line px-3 py-2 font-mono text-[12px] uppercase tracking-wide text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
              >
                <Phone className="h-3.5 w-3.5" />
                {t('Anrufen')}
              </a>
            )}
            {manager.art14_outstanding && (
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true)
                  try {
                    const updated = await api.markManagerArt14Notified(manager.id)
                    setManager(updated)
                    onNotified(updated)
                  } finally {
                    setBusy(false)
                  }
                }}
                className="flex items-center gap-1.5 rounded-lg bg-gold-400/15 px-3 py-2 font-mono text-[12px] uppercase tracking-wide text-gold-400 transition-colors hover:bg-gold-400/25"
              >
                <ShieldAlert className="h-3.5 w-3.5" />
                {busy ? t('Speichert…') : 'Art. 14 erledigt'}
              </button>
            )}
          </div>
        </div>
        {manager.no_interest_at ? (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <NoInterestChip since={manager.no_interest_at} reason={manager.removed_reason} note={manager.removed_note} />
            <ReviveLeadButton
              managerId={manager.id}
              onRevived={() => setManager((m) => ({ ...m, no_interest_at: null, removed_reason: null, removed_note: null }))}
            />
          </div>
        ) : (
          // ELI-66: a lead is removed from the Leads list here too — hidden, never deleted.
          manager.stage === 'bus_dev' && (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <RemoveLeadButton
                managerId={manager.id}
                onRemoved={(m) =>
                  setManager((cur) => ({
                    ...cur,
                    no_interest_at: m.no_interest_at,
                    removed_reason: m.removed_reason,
                    removed_note: m.removed_note,
                  }))
                }
              />
            </div>
          )
        )}
        {manager.do_not_contact_at && (
          <div className="mt-4">
            <DoNotContactBanner
              subject="manager"
              id={manager.id}
              since={manager.do_not_contact_at}
              email={manager.email}
              onLifted={() => setManager((m) => ({ ...m, do_not_contact_at: null, do_not_contact_reason: null }))}
            />
          </div>
        )}
      </header>

      <div className="flex border-b border-cockpit-line bg-cockpit-inset">
        <Stat
          label={t('Letzter Kontakt')}
          value={dateDe(manager.last_contact_at)}
          detail={
            since === null
              ? t('kein Kontakt erfasst')
              : t('vor {n} Tagen', { n: since }) + (overdue ? t(' — überfällig') : '')
          }
          tone={overdue ? 'coral' : undefined}
        />
        <Stat
          label={t('Mandate')}
          value={String(manager.open_job_count ?? 0)}
          detail={
            (manager.job_count ?? 0) > (manager.open_job_count ?? 0)
              ? `${manager.job_count} insgesamt`
              : t('offen')
          }
        />
        <Stat
          label={t('Gesuchte Skills')}
          value={manager.looks_for || '—'}
          detail={manager.department}
        />
        <Stat label={t('Notizen')} value={String(noteCount)} />
      </div>

      {/* ELI-44: open Wiedervorlagen, above the conversation they came from. */}
      <PersonFollowUps subject={{ managerId: manager.id }} />

      {/* --- tabs: one place that says what exists on this record ---------- */}
      <nav className="flex items-center gap-1 overflow-x-auto border-b border-cockpit-line px-6">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              '-mb-px shrink-0 border-b-2 px-3 py-3 font-mono text-[13px] transition-colors',
              tab === t.key
                ? 'border-mint-400 text-cockpit-text'
                : 'border-transparent text-cockpit-faint hover:text-cockpit-dim',
            )}
          >
            {t.label}
            <sup className="ml-0.5 text-[10px] text-cockpit-faint">{t.count}</sup>
          </button>
        ))}

        {/* The bar said what exists and gave no way to add to it. The button
            lives here rather than in the header because this is the strip
            that is about the conversation; the header is about the person. */}
        <button
          type="button"
          onClick={() => {
            // From Termine the composer opens there, on a meeting (ELI-40).
            if (tab !== 'meetings') setTab('notes')
            setComposing((open) => !open)
          }}
          aria-expanded={composing}
          className={cn(
            'ml-auto flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 font-mono text-[12px] uppercase tracking-wide transition-colors',
            composing
              ? 'border-mint-600 bg-mint-800/40 text-mint-300'
              : 'border-cockpit-line text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text',
          )}
        >
          <Plus className="h-3.5 w-3.5" />
          {t('Ereignis')}
        </button>
      </nav>

      <div className="flex flex-col lg:flex-row">
        <div className="min-w-0 flex-1 border-r border-cockpit-line">
          {(tab === 'notes' || tab === 'meetings') && composing && (
            <InteractionComposer
              key={tab}
              kinds={MANAGER_INTERACTION_KINDS}
              defaultKind={tab === 'meetings' ? 'meeting' : undefined}
              onCancel={() => setComposing(false)}
              privacy={{
                canErase: isAdmin(me),
                onErase: () => {
                  setComposing(false)
                  setEraseOpen(true)
                },
              }}
              onSave={async (entry, followUp) => {
                const row = await api.logManagerInteraction(manager.id, entry)
                if (followUp) {
                  // ELI-61: profiles sent — the feedback Wiedervorlage the
                  // composer already asked for, filed against this note. If
                  // it fails the note still stands, so the ordinary offer
                  // appears instead of an error that would invite a second
                  // copy of the note.
                  try {
                    await api.createFollowUp({
                      manager_id: manager.id,
                      due_date: followUp.due_date,
                      due_time: null,
                      text: followUp.text,
                      source_interaction_id: row.id,
                      origin: 'note',
                    })
                    announceFollowUpsChanged()
                  } catch {
                    setOfferFor(row)
                  }
                } else if (!entry.do_not_contact) {
                  // ELI-32: no Wiedervorlage for someone who asked not to be
                  // contacted again.
                  setOfferFor(row)
                }
                // Prepend rather than refetch: the list is sorted by when
                // the event happened, and a note filed for last Tuesday
                // would otherwise appear to vanish.
                setHistory((rows) =>
                  [row, ...(rows ?? [])].sort((a, b) =>
                    b.occurred_at.localeCompare(a.occurred_at),
                  ),
                )
                // ELI-40: a meeting is also a Termin.
                if (isAppointmentKind(row.interaction_type)) {
                  setAppointments((rows) => [row, ...(rows ?? [])])
                }
                setManager((m) => ({
                  ...m,
                  note_count: (m.note_count ?? 0) + 1,
                  do_not_contact_at: entry.do_not_contact
                    ? (m.do_not_contact_at ?? new Date().toISOString())
                    : m.do_not_contact_at,
                  // A meeting booked for later is not contact yet — the
                  // server applies the same rule.
                  last_contact_at:
                    isContact(entry.interaction_type) &&
                    new Date(entry.occurred_at).getTime() <= Date.now() &&
                    (!m.last_contact_at || entry.occurred_at > m.last_contact_at)
                      ? entry.occurred_at
                      : m.last_contact_at,
                }))
                setComposing(false)
              }}
            />
          )}
          {offerFor && (
            <div className="border-b border-cockpit-line px-6 py-3">
              <NoteFollowUpOffer
                subject={{ managerId: manager.id }}
                note={offerFor}
                onClose={() => setOfferFor(null)}
              />
            </div>
          )}
          {tab === 'notes' && (
            <>
              {history === null && (
                <p className="px-6 py-6 font-mono text-[13px] text-cockpit-faint">
                  {t('lädt…')}
                </p>
              )}
              {history?.length === 0 && !composing && (
                <p className="px-6 py-6 text-[14px] text-cockpit-dim">
                  {t('Noch nichts notiert. Importierte Gespräche erscheinen hier — oder legen Sie über „Ereignis“ selbst eines an.')}
                </p>
              )}
              {history && history.length > 0 && (
                <>
                  <ul>
                    {history.map((entry) => (
                      <Note key={entry.id} entry={entry} />
                    ))}
                  </ul>
                  <p className="px-6 py-3 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
                    {history.length} {t('Notizen · neueste zuerst')}
                  </p>
                </>
              )}
            </>
          )}

          {tab === 'meetings' && (
            <Appointments
              rows={appointments}
              composing={composing}
              calendarTitle={`${interactionLabel('meeting')} — ${manager.full_name}`}
            />
          )}

          {/* Deals is named because the record has that dimension and empty
              because nothing fills it yet. Saying so beats a tab that
              silently shows nothing. */}
          {(tab === 'jobs' || tab === 'deals') && (
            <p className="px-6 py-6 text-[14px] leading-relaxed text-cockpit-dim">
              {tab === 'jobs'
                ? t('Mandate dieser Person erscheinen hier, sobald sie einem Job zugeordnet sind.')
                : t('Für diesen Bereich liegen noch keine Daten vor — er wird beim Import noch nicht befüllt.')}
            </p>
          )}
          <div className="px-6 pb-6">
            <EraseSection
              subject="manager"
              id={manager.id}
              name={manager.full_name}
              email={manager.email}
              open={eraseOpen}
              onOpenChange={setEraseOpen}
              onErased={onErased ?? onClose}
            />
          </div>
        </div>

        <aside className="w-full shrink-0 lg:w-[27rem]">
          <RailSection title={t('Erreichbar')}>
            <EditContact
              manager={manager}
              companyName={shownCompany}
              onSaved={(updated, company) => {
                setManager(updated)
                if (company) setShownCompany(company)
                onNotified(updated)
              }}
            />
            <Line label={t('Mail')}>
              {manager.email && (
                <a
                  href={`mailto:${manager.email}`}
                  className="text-mint-400 hover:underline"
                >
                  {manager.email}
                </a>
              )}
            </Line>
            <Line label={t('Telefon')}>
              <PhoneList phones={phonesOf(manager)} board={companyPage.data?.switchboard} />
            </Line>
            <Line label={t('Adresse')}>
              {address ? (
                <span className="flex gap-1.5">
                  <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
                  {address}
                </span>
              ) : null}
            </Line>
            <Line label={t('Profile')}>
              {socials.length ? (
                <span className="flex flex-wrap gap-x-3 gap-y-1">
                  {socials.map((s) => (
                    <a
                      key={s.label}
                      href={s.url ?? undefined}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="flex items-center gap-1 text-mint-400 hover:underline"
                    >
                      {s.label}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  ))}
                </span>
              ) : null}
            </Line>
          </RailSection>

          {(manager.skills?.length || manager.tags?.length) ? (
            <RailSection title={t('Profil')}>
              {manager.skills?.length ? (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {manager.skills.map((s) => (
                    <Chip key={s}>{s}</Chip>
                  ))}
                </div>
              ) : null}
              {manager.tags?.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {manager.tags.map((t) => (
                    <Chip key={t} tone="lav">
                      {t}
                    </Chip>
                  ))}
                </div>
              ) : null}
            </RailSection>
          ) : null}

          {shownCompany && shownCompany !== '—' && (
            <RailSection title={t('Firma')}>
              <a
                href={`#companies/${manager.company_id}`}
                className="flex items-center gap-1.5 text-[17px] font-semibold text-cockpit-text hover:text-mint-400"
                title={t('Zur Firmenseite')}
              >
                <Building2 className="h-4 w-4 shrink-0 text-cockpit-faint" />
                {shownCompany}
              </a>
            </RailSection>
          )}

          <CompanyJobs companyId={manager.company_id} market={companyPage.data?.market} />

          <RailSection title={t('Datensatz')}>
            <Line label={t('Angelegt')}>{dateDe(manager.created_at)}</Line>
            <Line label="Art. 14">
              {manager.art14_outstanding ? (
                <span className="text-gold-400">{t('offen')}</span>
              ) : manager.art14_notified_at ? (
                t('informiert am {when}', { when: dateDe(manager.art14_notified_at) })
              ) : (
                <span className="text-cockpit-faint">{t('nicht erforderlich')}</span>
              )}
            </Line>
            {/* The id of the system this was imported FROM. Useful when someone
                is looking at both, meaningless on its own — so it lives here
                rather than next to the person's name. */}
            <Line label={t('Quelle')}>
              {manager.external_code ? (
                <span className="font-mono text-[12px] text-cockpit-faint">
                  aiFind {manager.external_code}
                </span>
              ) : null}
            </Line>
          </RailSection>
        </aside>
      </div>
    </div>
  )
}


/** ELI-45: correct or add the contact's details here — before, a phone
 *  number could only arrive by import. Sends only what changed, through the
 *  same erasure confirmation as creating a contact. */
function EditContact({
  manager,
  companyName,
  onSaved,
}: {
  manager: ManagerDTO
  companyName: string
  /** `company`: the new company's name when the contact moved. */
  onSaved: (updated: ManagerDTO, company?: string) => void
}) {
  const [draft, setDraft] = useState(() => contactDraftOf(manager))
  const [lead, setLead] = useState(() => leadDraftOf(manager))
  const [companies, setCompanies] = useState<{ id: string; name: string }[] | null>(null)
  const [phones, setPhones] = useState(() => phonesOf(manager))
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setDraft(contactDraftOf(manager))
          setLead(leadDraftOf(manager))
          setPhones(phonesOf(manager))
          // ELI-66: the company is one of the workspace's own.
          // The list endpoint caps at 500; the current company always shows,
          // so the picker never displays a company the contact is not at.
          if (companies === null)
            api
              .companies(500)
              .then((rows) => {
                const list = rows.map((c) => ({ id: c.id, name: c.name })).sort((a, b) => a.name.localeCompare(b.name))
                setCompanies(
                  list.some((c) => c.id === manager.company_id)
                    ? list
                    : [{ id: manager.company_id, name: companyName || '—' }, ...list],
                )
              })
              .catch(() => setCompanies([]))
          setError(null)
          setOpen(true)
        }}
        className="mb-1 flex items-center gap-1.5 font-mono text-[12px] text-mint-400 transition-colors hover:text-mint-300"
      >
        <Pencil className="h-3.5 w-3.5" />
        {t('Kontaktdaten bearbeiten')}
      </button>
    )
  }

  async function save() {
    // ELI-46: numbers go as the whole list (`phones`); the single phone
    // field is not shown here, so `phone` never appears in this patch.
    if (!lead.full_name.trim()) {
      setError(t('Bitte einen Namen angeben.'))
      return
    }
    const patch: Parameters<typeof api.updateManager>[1] = { ...contactPatch(manager, draft), ...leadPatch(manager, lead) }
    const nextPhones = phonesPatch(manager, phones)
    if (nextPhones) patch.phones = nextPhones
    if (Object.keys(patch).length === 0) {
      setOpen(false)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const updated = await withReaddConfirm((override) =>
        api.updateManager(manager.id, { ...patch, override_suppression: override || undefined }),
      )
      // The PATCH answer carries no counts; keep the profile's, take the fields.
      const fields = Object.fromEntries(
        [...CONTACT_KEYS, ...LEAD_KEYS, 'company_id' as const, 'phones' as const].map((k) => [k, updated[k]]),
      )
      const moved = updated.company_id !== manager.company_id
      onSaved({ ...manager, ...fields }, moved ? companies?.find((c) => c.id === updated.company_id)?.name : undefined)
      setOpen(false)
    } catch (e) {
      setError(
        e instanceof ReaddDeclined
          ? e.message
          : e instanceof ApiError && e.status === 422
            ? t('Bitte Eingaben prüfen.')
            : t('Nicht gespeichert — bitte erneut versuchen.'),
      )
    }
    setBusy(false)
  }

  return (
    <div className="mb-3 space-y-3">
      <LeadFields value={lead} onChange={setLead} companies={companies} />
      <ContactFields value={draft} onChange={setDraft} withPhone={false} />
      <PhoneListEditor value={phones} onChange={setPhones} />
      <div className="flex items-center gap-2">
        <Button tone="primary" onClick={() => void save()} disabled={busy}>
          <Check className="h-4 w-4" /> {busy ? t('Speichert…') : t('Speichern')}
        </Button>
        <Button onClick={() => setOpen(false)} disabled={busy}>
          <X className="h-4 w-4" /> {t('Abbrechen')}
        </Button>
      </div>
      {error && <p className="text-[12.5px] text-coral-400">{error}</p>}
    </div>
  )
}

// ELI-66: the rest of a lead's fields — name, company, XING, address — next
// to ELI-45's contact details. Kept here rather than in `ui/contactFields`,
// which also serves the create forms.
const LEAD_KEYS = ['full_name', 'first_name', 'last_name', 'xing_url', 'street', 'postal_code', 'city'] as const
type LeadKey = (typeof LEAD_KEYS)[number]
type LeadDraft = Record<LeadKey, string> & { company_id: string }

function leadDraftOf(m: ManagerDTO): LeadDraft {
  return {
    ...(Object.fromEntries(LEAD_KEYS.map((k) => [k, m[k] ?? ''])) as Record<LeadKey, string>),
    company_id: m.company_id,
  }
}

/** Only what changed; an emptied field is sent as null (the name never is). */
function leadPatch(m: ManagerDTO, d: LeadDraft): Parameters<typeof api.updateManager>[1] {
  const patch: Record<string, string | null> = {}
  for (const k of LEAD_KEYS) {
    const next = d[k].trim() || null
    if (next !== (m[k] ?? null)) patch[k] = next
  }
  if (d.company_id && d.company_id !== m.company_id) patch.company_id = d.company_id
  return patch as Parameters<typeof api.updateManager>[1]
}

function LeadFields({
  value,
  onChange,
  companies,
}: {
  value: LeadDraft
  onChange: (next: LeadDraft) => void
  companies: { id: string; name: string }[] | null
}) {
  const set = (k: keyof LeadDraft) => (v: string) => onChange({ ...value, [k]: v })
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <TextInput label={t('Name')} value={value.full_name} onChange={set('full_name')} />
      </div>
      <TextInput label={t('Vorname')} value={value.first_name} onChange={set('first_name')} placeholder={t('optional')} />
      <TextInput label={t('Nachname')} value={value.last_name} onChange={set('last_name')} placeholder={t('optional')} />
      <div className="sm:col-span-2">
        {companies && companies.length > 0 ? (
          <SelectInput
            label={t('Firma')}
            value={value.company_id}
            onChange={set('company_id')}
            options={companies.map((c) => ({ value: c.id, label: c.name }))}
          />
        ) : (
          <p className="font-mono text-[12px] text-cockpit-faint">{companies ? '' : t('lädt…')}</p>
        )}
      </div>
      <div className="sm:col-span-2">
        <TextInput label={t('XING-Profil')} value={value.xing_url} onChange={set('xing_url')} placeholder="https://www.xing.com/profile/…" />
      </div>
      <div className="sm:col-span-2">
        <TextInput label={t('Straße')} value={value.street} onChange={set('street')} placeholder={t('optional')} />
      </div>
      <TextInput label={t('PLZ')} value={value.postal_code} onChange={set('postal_code')} placeholder={t('optional')} />
      <TextInput label={t('Ort')} value={value.city} onChange={set('city')} placeholder={t('optional')} />
    </div>
  )
}

/** ELI-40: the Termine tab. Booked meetings first, soonest on top, each with a
 *  calendar file; then the meetings that were held. */
function Appointments({
  rows,
  composing,
  calendarTitle,
}: {
  rows: ManagerInteractionDTO[] | null
  composing: boolean
  calendarTitle: string
}) {
  if (rows === null) {
    return <p className="px-6 py-6 font-mono text-[13px] text-cockpit-faint">{t('lädt…')}</p>
  }
  if (rows.length === 0) {
    return composing ? null : (
      <p className="px-6 py-6 text-[14px] text-cockpit-dim">
        {t('Noch keine Termine. Ein Ereignis der Art „Meeting Notes“ erscheint hier — mit Datum und Uhrzeit.')}
      </p>
    )
  }
  const { upcoming, past } = splitAppointments(rows)
  const download = (entry: ManagerInteractionDTO) => {
    const blob = new Blob([appointmentIcs(entry, calendarTitle)], { type: 'text/calendar' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `termin-${entry.occurred_at.slice(0, 10)}.ics`
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <>
      {[
        { title: t('Geplant'), list: upcoming },
        { title: t('Stattgefunden'), list: past },
      ].map(({ title, list }) =>
        list.length === 0 ? null : (
          <section key={title}>
            <p className="px-6 pb-1 pt-4 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
              {title} · {list.length}
            </p>
            <ul>
              {list.map((entry) => (
                <li key={entry.id} className="flex gap-5 border-b border-cockpit-line/60 px-6 py-4">
                  <div className="w-[5.5rem] shrink-0">
                    <p className="font-mono text-[13px] text-cockpit-text">{dateDe(entry.occurred_at)}</p>
                    <p className="font-mono text-[11px] text-cockpit-faint">{timeDe(entry.occurred_at)}</p>
                  </div>
                  <p className="min-w-0 flex-1 whitespace-pre-wrap text-[14px] leading-relaxed text-cockpit-dim line-clamp-4">
                    {entry.summary}
                  </p>
                  {list === upcoming && (
                    <button
                      type="button"
                      onClick={() => download(entry)}
                      title={t('Als .ics in den eigenen Kalender übernehmen')}
                      className="flex shrink-0 items-center gap-1.5 self-start font-mono text-[12px] text-mint-400 transition-colors hover:text-mint-300"
                    >
                      <CalendarDays className="h-3.5 w-3.5" />
                      {t('In Kalender')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ),
      )}
    </>
  )
}

/** ELI-33: what the manager's company is hiring for now, from Markt — so a
 *  call starts from the open roles. The full list is on the company page. */
function CompanyJobs({ companyId, market }: { companyId: string; market: CompanyMarketDTO | undefined }) {
  if (!market) return null
  return (
    <RailSection title={market.linked ? t('Offene Stellen ({n})', { n: String(market.total) }) : t('Offene Stellen')}>
      <div className="space-y-2">
        <CareersLink market={market} />
        <OpenJobs market={market} limit={5} companyHref={`#companies/${companyId}`} />
      </div>
    </RailSection>
  )
}
