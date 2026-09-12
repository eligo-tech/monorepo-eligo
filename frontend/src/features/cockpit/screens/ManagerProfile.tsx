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

import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  Building2,
  ExternalLink,
  Mail,
  MapPin,
  Phone,
  ShieldAlert,
} from 'lucide-react'
import { api } from '@/api/client'
import type { ManagerDTO, ManagerInteractionDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Chip } from '../ui/primitives'

const dateDe = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      })
    : '—'

const timeDe = (iso: string) =>
  new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })

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
      <span className="w-[4.5rem] shrink-0 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
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
        {/* The source's own category, kept verbatim — "BD Call" is the
            recruiter's word for it and carries more than "call" would. */}
        <Chip>{entry.interaction_type}</Chip>
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
            {open ? 'weniger' : 'mehr'}
          </button>
        )}
      </div>
    </li>
  )
}

type TabKey = 'notes' | 'jobs' | 'meetings' | 'deals' | 'files' | 'history'

export function ManagerProfile({
  manager: initial,
  companyName,
  onClose,
  onNotified,
}: {
  manager: ManagerDTO
  companyName: string
  onClose: () => void
  onNotified: (updated: ManagerDTO) => void
}) {
  const [manager, setManager] = useState(initial)
  const [history, setHistory] = useState<ManagerInteractionDTO[] | null>(null)
  const [tab, setTab] = useState<TabKey>('notes')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    setManager(initial)
    setHistory(null)
    setTab('notes')
    api.manager(initial.id).then((m) => alive && setManager(m)).catch(() => {})
    api
      .managerInteractions(initial.id)
      .then((rows) => alive && setHistory(rows))
      .catch(() => alive && setHistory([]))
    return () => {
      alive = false
    }
  }, [initial])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
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
        { key: 'notes' as const, label: 'Notizen', count: noteCount },
        { key: 'jobs' as const, label: 'Mandate', count: manager.job_count ?? 0 },
        { key: 'meetings' as const, label: 'Termine', count: 0 },
        { key: 'deals' as const, label: 'Deals', count: 0 },
        { key: 'files' as const, label: 'Anhänge', count: 0 },
        { key: 'history' as const, label: 'Verlauf', count: 0 },
      ],
    [noteCount, manager.job_count],
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
                Manager
              </button>
              {manager.art14_outstanding && (
                <>
                  <span>/</span>
                  <span className="text-gold-400">Art. 14 offen</span>
                </>
              )}
            </div>

            <h1 className="mt-2 truncate text-[44px] font-semibold leading-none tracking-tight text-cockpit-text">
              {manager.full_name}
            </h1>
            <p className="mt-2 flex flex-wrap items-center gap-x-1.5 text-[15px] text-cockpit-dim">
              {manager.role_title && <span>{manager.role_title}</span>}
              {companyName && companyName !== '—' && (
                <>
                  <span className="text-cockpit-faint">bei</span>
                  <span className="text-mint-400">{companyName}</span>
                </>
              )}
              {place && <span className="text-cockpit-faint">· {place}</span>}
            </p>
          </div>

          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {manager.email && (
              <a
                href={`mailto:${manager.email}`}
                className="flex items-center gap-1.5 rounded-lg border border-cockpit-line px-3 py-2 font-mono text-[12px] uppercase tracking-wide text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
              >
                <Mail className="h-3.5 w-3.5" />
                E-Mail
              </a>
            )}
            {manager.phone && (
              <a
                href={`tel:${manager.phone}`}
                className="flex items-center gap-1.5 rounded-lg border border-cockpit-line px-3 py-2 font-mono text-[12px] uppercase tracking-wide text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
              >
                <Phone className="h-3.5 w-3.5" />
                Anrufen
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
                {busy ? 'Speichert…' : 'Art. 14 erledigt'}
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="flex border-b border-cockpit-line bg-cockpit-inset">
        <Stat
          label="Letzter Kontakt"
          value={dateDe(manager.last_contact_at)}
          detail={
            since === null
              ? 'kein Kontakt erfasst'
              : `vor ${since} Tagen${overdue ? ' — überfällig' : ''}`
          }
          tone={overdue ? 'coral' : undefined}
        />
        <Stat
          label="Mandate"
          value={String(manager.open_job_count ?? 0)}
          detail={
            (manager.job_count ?? 0) > (manager.open_job_count ?? 0)
              ? `${manager.job_count} insgesamt`
              : 'offen'
          }
        />
        <Stat label="Sucht" value={manager.looks_for || '—'} detail={manager.department} />
        <Stat label="Notizen" value={String(noteCount)} />
      </div>

      {/* --- tabs: one place that says what exists on this record ---------- */}
      <nav className="flex gap-1 overflow-x-auto border-b border-cockpit-line px-6">
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
      </nav>

      <div className="flex flex-col lg:flex-row">
        <div className="min-w-0 flex-1 border-r border-cockpit-line">
          {tab === 'notes' && (
            <>
              {history === null && (
                <p className="px-6 py-6 font-mono text-[13px] text-cockpit-faint">
                  lädt…
                </p>
              )}
              {history?.length === 0 && (
                <p className="px-6 py-6 text-[14px] text-cockpit-dim">
                  Noch kein Verlauf. Anrufe, Mails und Termine erscheinen hier,
                  sobald sie erfasst werden.
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
                    {history.length} Notizen · neueste zuerst
                  </p>
                </>
              )}
            </>
          )}

          {/* The other tabs are named because the record has those dimensions,
              and empty because nothing has been imported into them yet. Saying
              so beats a tab that silently shows nothing. */}
          {tab !== 'notes' && (
            <p className="px-6 py-6 text-[14px] leading-relaxed text-cockpit-dim">
              {tab === 'jobs'
                ? 'Mandate dieser Person erscheinen hier, sobald sie einem Job zugeordnet sind.'
                : 'Für diesen Bereich liegen noch keine Daten vor — er wird beim Import noch nicht befüllt.'}
            </p>
          )}
        </div>

        <aside className="w-full shrink-0 lg:w-[22rem]">
          <RailSection title="Erreichbar">
            <Line label="Mail">
              {manager.email && (
                <a
                  href={`mailto:${manager.email}`}
                  className="text-mint-400 hover:underline"
                >
                  {manager.email}
                </a>
              )}
            </Line>
            <Line label="Telefon">
              {manager.phone && (
                <a href={`tel:${manager.phone}`} className="text-mint-400 hover:underline">
                  {manager.phone}
                </a>
              )}
            </Line>
            <Line label="Adresse">
              {address ? (
                <span className="flex gap-1.5">
                  <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
                  {address}
                </span>
              ) : null}
            </Line>
            <Line label="Profile">
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
            <RailSection title="Profil">
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

          {companyName && companyName !== '—' && (
            <RailSection title="Firma">
              <p className="flex items-center gap-1.5 text-[17px] font-semibold text-cockpit-text">
                <Building2 className="h-4 w-4 shrink-0 text-cockpit-faint" />
                {companyName}
              </p>
            </RailSection>
          )}

          <RailSection title="Datensatz">
            <Line label="Angelegt">{dateDe(manager.created_at)}</Line>
            <Line label="Art. 14">
              {manager.art14_outstanding ? (
                <span className="text-gold-400">offen</span>
              ) : manager.art14_notified_at ? (
                `informiert am ${dateDe(manager.art14_notified_at)}`
              ) : (
                <span className="text-cockpit-faint">nicht erforderlich</span>
              )}
            </Line>
            {/* The id of the system this was imported FROM. Useful when someone
                is looking at both, meaningless on its own — so it lives here
                rather than next to the person's name. */}
            <Line label="Quelle">
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
