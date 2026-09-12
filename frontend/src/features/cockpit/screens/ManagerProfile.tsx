// One manager's profile — layout after Design.pdf, palette from the cockpit.
//
// The design's ordering is the argument: identity, then the four numbers that
// decide whether to call, then what was said. A recruiter opening this record
// is about to pick up the phone, so everything above the fold answers "should
// I, and what do I already know?".
//
// Two departures from the mock, both because the data is not there and
// inventing it would be worse than an honest gap:
//
//   * "NEXT MOVE — Budget call, November 2026" does not exist in the source.
//     It reads as a plan someone entered; in the API there is no such field,
//     and deriving it from the note text would be a guess presented as a fact.
//     Replaced with MANDATE — how many open roles this person owns, which is
//     real and varies per contact.
//   * The pinned "sticky note" is not exposed by the API either (probed; the
//     Manager type has no such field). The banner instead carries the LATEST
//     CONTACT NOTE, which is the thing actually worth reading before a call,
//     and is labelled as what it is rather than as a pinned message.

import { useEffect, useState } from 'react'
import { ArrowLeft, Mail, Phone, ShieldAlert } from 'lucide-react'
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

/** Days since a date, or null when there is no date to count from. */
function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  return ms < 0 ? 0 : Math.floor(ms / 86_400_000)
}

/** One cell of the stat strip. */
function Stat({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: string
  detail?: string | null
  tone?: 'coral' | 'gold'
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
            tone === 'coral'
              ? 'text-coral-400'
              : tone === 'gold'
                ? 'text-gold-400'
                : 'text-cockpit-faint',
          )}
        >
          {detail}
        </p>
      )}
    </div>
  )
}

/** Right-rail label/value line. Renders nothing without a value — an empty
 *  field reads as "we checked and there is none", a different claim. */
function Line({ label, children }: { label: string; children: React.ReactNode }) {
  if (children === null || children === undefined || children === '') return null
  return (
    <div className="flex gap-3 py-1">
      <span className="w-20 shrink-0 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
        {label}
      </span>
      <span className="min-w-0 flex-1 text-[13px] leading-relaxed text-cockpit-text">
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
  const [busy, setBusy] = useState(false)

  // The list row carries no counts — the single read does, so the profile
  // re-fetches rather than rendering zeros it would have to correct.
  useEffect(() => {
    let alive = true
    setManager(initial)
    setHistory(null)
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
  const latest = history?.[0]

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-cockpit-bg">
      {/* --- identity ---------------------------------------------------- */}
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
              {manager.external_code && (
                <>
                  <span>/</span>
                  <span>{manager.external_code}</span>
                </>
              )}
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
            <p className="mt-2 text-[15px] text-cockpit-dim">
              {manager.role_title && <span>{manager.role_title} </span>}
              {companyName && companyName !== '—' && (
                <>
                  <span className="text-cockpit-faint">at </span>
                  <span className="text-mint-400">{companyName}</span>
                </>
              )}
              {place && <span className="text-cockpit-faint"> · {place}</span>}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
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

      {/* --- the four numbers that decide whether to call ----------------- */}
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
        <Stat
          label="Notizen"
          value={String(manager.note_count ?? history?.length ?? 0)}
          detail={latest ? `zuletzt ${dateDe(latest.occurred_at)}` : null}
        />
      </div>

      <div className="flex flex-col lg:flex-row">
        <div className="min-w-0 flex-1 border-r border-cockpit-line">
          {/* --- read before you call --------------------------------------
              The mock pins a sticky note; the API has none, so this carries the
              most recent note — the thing actually worth reading first — and
              says so instead of claiming to be pinned. */}
          {latest && (
            <div className="border-b border-cockpit-line bg-mint-400/10 px-6 py-5">
              <div className="flex items-baseline justify-between gap-4">
                <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-mint-400">
                  Zuletzt besprochen — {latest.interaction_type} ·{' '}
                  {dateDe(latest.occurred_at)}
                </p>
              </div>
              <p className="mt-2 max-w-3xl whitespace-pre-wrap text-[19px] font-medium leading-snug text-cockpit-text">
                {latest.summary}
              </p>
            </div>
          )}

          {/* --- the conversation ------------------------------------------ */}
          <div className="flex items-baseline gap-4 border-b border-cockpit-line px-6 py-3">
            <span className="font-mono text-[13px] text-cockpit-text">
              Notizen
              <sup className="ml-0.5 text-cockpit-faint">
                {manager.note_count ?? history?.length ?? 0}
              </sup>
            </span>
            <span className="font-mono text-[13px] text-cockpit-faint">
              Mandate<sup className="ml-0.5">{manager.job_count ?? 0}</sup>
            </span>
          </div>

          {history === null && (
            <p className="px-6 py-6 font-mono text-[13px] text-cockpit-faint">lädt…</p>
          )}
          {history?.length === 0 && (
            <p className="px-6 py-6 text-[14px] text-cockpit-dim">
              Noch kein Verlauf. Anrufe, Mails und Termine erscheinen hier, sobald
              sie erfasst werden.
            </p>
          )}
          {history && history.length > 0 && (
            <>
              <ul>
                {history.map((entry) => (
                  <li
                    key={entry.id}
                    className="flex gap-5 border-b border-cockpit-line/60 px-6 py-4"
                  >
                    <div className="w-24 shrink-0">
                      <p className="font-mono text-[13px] text-cockpit-text">
                        {dateDe(entry.occurred_at)}
                      </p>
                      <p className="font-mono text-[11px] text-cockpit-faint">
                        {timeDe(entry.occurred_at)}
                      </p>
                      <div className="mt-1.5">
                        {/* The source's own category, kept verbatim. */}
                        <Chip>{entry.interaction_type}</Chip>
                      </div>
                    </div>
                    <p className="min-w-0 flex-1 whitespace-pre-wrap text-[14px] leading-relaxed text-cockpit-dim">
                      {entry.summary}
                    </p>
                  </li>
                ))}
              </ul>
              <p className="px-6 py-3 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
                {history.length} Notizen · neueste zuerst
              </p>
            </>
          )}
        </div>

        {/* --- right rail --------------------------------------------------- */}
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
            <Line label="Adresse">{address || null}</Line>
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

          <RailSection title="Datensatz">
            <Line label="ID">{manager.external_code}</Line>
            <Line label="Angelegt">{dateDe(manager.created_at)}</Line>
            <Line label="Herkunft">{manager.source_detail ?? manager.source}</Line>
            <Line label="Art. 14">
              {manager.art14_outstanding ? (
                <span className="text-gold-400">offen</span>
              ) : manager.art14_notified_at ? (
                `informiert am ${dateDe(manager.art14_notified_at)}`
              ) : (
                <span className="text-cockpit-faint">nicht erforderlich</span>
              )}
            </Line>
          </RailSection>

          {companyName && companyName !== '—' && (
            <RailSection title="Firma">
              <p className="text-[17px] font-semibold text-cockpit-text">{companyName}</p>
              {address && (
                <p className="mt-1 text-[13px] leading-relaxed text-cockpit-dim">
                  {address}
                </p>
              )}
            </RailSection>
          )}
        </aside>
      </div>
    </div>
  )
}
