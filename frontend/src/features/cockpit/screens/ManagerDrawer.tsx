// One manager's profile — the person behind a mandate.
//
// The layout follows what a recruiter reaches for in order: how to contact them,
// what they are open to, and what was said last time. The conversation history
// is the bottom half and the largest part of the panel on purpose — a company
// can be re-crawled and a mandate re-entered, but "Budgets gerade low, nochmal
// im November" exists only because someone wrote it down after a call. It is
// the one thing in this system that cannot be reconstructed from anywhere else.

import { useEffect, useState } from 'react'
import {
  Building2,
  Hash,
  Mail,
  MapPin,
  Phone,
  ShieldAlert,
  Tag,
  X,
} from 'lucide-react'
import { api } from '@/api/client'
import type { ManagerDTO, ManagerInteractionDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Chip, Panel } from '../ui/primitives'
import { Button } from '../ui/forms'

const dateDe = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      })
    : '—'

/** Label/value row. Renders nothing at all when there is no value — an empty
 *  field reads as "we checked and there is none", which is a different claim. */
function Detail({
  icon,
  label,
  children,
}: {
  icon?: React.ReactNode
  label: string
  children: React.ReactNode
}) {
  if (children === null || children === undefined || children === '') return null
  return (
    <div className="flex gap-3 py-1.5">
      <span className="flex w-36 shrink-0 items-center gap-1.5 font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
        {icon}
        {label}
      </span>
      <span className="min-w-0 flex-1 text-[14px] text-cockpit-text">{children}</span>
    </div>
  )
}

export function ManagerDrawer({
  manager,
  companyName,
  onClose,
  onNotified,
}: {
  manager: ManagerDTO
  companyName: string
  onClose: () => void
  onNotified: (updated: ManagerDTO) => void
}) {
  const [history, setHistory] = useState<ManagerInteractionDTO[] | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    setHistory(null)
    api
      .managerInteractions(manager.id)
      .then((rows) => alive && setHistory(rows))
      .catch(() => alive && setHistory([]))
    return () => {
      alive = false
    }
  }, [manager.id])

  // Escape closes: a drawer that traps you is worse than no drawer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const address = [manager.street, [manager.postal_code, manager.city].filter(Boolean).join(' '), manager.country]
    .filter(Boolean)
    .join(', ')

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <aside
        className="h-full w-full max-w-2xl overflow-y-auto bg-cockpit-bg p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[28px] font-semibold leading-tight text-cockpit-text">
              {manager.full_name}
            </h2>
            <p className="mt-1 text-[15px] text-cockpit-dim">
              {[manager.role_title, companyName].filter(Boolean).join(' · ') || '—'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-cockpit-faint transition-colors hover:text-cockpit-text"
            aria-label="Schließen"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {manager.art14_outstanding && (
          <Panel className="mt-4 flex items-center justify-between gap-4 border-gold-400/40 p-4">
            <p className="text-[13px] leading-relaxed text-gold-400">
              Diese Daten stammen nicht von der betroffenen Person selbst. Eine
              Information nach Art. 14 DSGVO ist fällig.
            </p>
            <Button
              tone="primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                try {
                  onNotified(await api.markManagerArt14Notified(manager.id))
                } finally {
                  setBusy(false)
                }
              }}
            >
              <ShieldAlert className="h-4 w-4" />
              {busy ? 'Speichert…' : 'Erledigt'}
            </Button>
          </Panel>
        )}

        <Panel className="mt-4 p-4">
          <Detail icon={<Hash className="h-3.5 w-3.5" />} label="Referenz">
            {manager.external_code}
          </Detail>
          <Detail icon={<Building2 className="h-3.5 w-3.5" />} label="Firma">
            {companyName}
          </Detail>
          <Detail icon={<Phone className="h-3.5 w-3.5" />} label="Telefon">
            {manager.phone && (
              <a href={`tel:${manager.phone}`} className="hover:text-mint-400">
                {manager.phone}
              </a>
            )}
          </Detail>
          <Detail icon={<Mail className="h-3.5 w-3.5" />} label="E-Mail">
            {manager.email && (
              <a href={`mailto:${manager.email}`} className="hover:text-mint-400">
                {manager.email}
              </a>
            )}
          </Detail>
          <Detail icon={<MapPin className="h-3.5 w-3.5" />} label="Adresse">
            {address || null}
          </Detail>
          <Detail label="Sucht">{manager.looks_for}</Detail>
          <Detail label="Abteilung">{manager.department}</Detail>
          <Detail label="Letzter Kontakt">
            {manager.last_contact_at ? dateDe(manager.last_contact_at) : null}
          </Detail>
          <Detail label="Herkunft">
            {manager.source_detail ?? manager.source}
          </Detail>
        </Panel>

        {(manager.skills?.length || manager.tags?.length) && (
          <Panel className="mt-4 space-y-3 p-4">
            {manager.skills?.length ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
                  Skills
                </span>
                {manager.skills.map((s) => (
                  <Chip key={s}>{s}</Chip>
                ))}
              </div>
            ) : null}
            {manager.tags?.length ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 flex items-center gap-1 font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
                  <Tag className="h-3.5 w-3.5" />
                  Tags
                </span>
                {manager.tags.map((t) => (
                  <Chip key={t} tone="lav">
                    {t}
                  </Chip>
                ))}
              </div>
            ) : null}
          </Panel>
        )}

        <section className="mt-6">
          <h3 className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
            Kontaktverlauf
            {history && history.length > 0 && (
              <span className="ml-2 text-cockpit-dim">{history.length}</span>
            )}
          </h3>

          {history === null && (
            <p className="mt-3 font-mono text-[13px] text-cockpit-faint">lädt…</p>
          )}
          {history?.length === 0 && (
            <p className="mt-3 text-[14px] text-cockpit-dim">
              Noch kein Verlauf. Anrufe, Mails und Termine erscheinen hier, sobald
              sie erfasst werden.
            </p>
          )}
          {history && history.length > 0 && (
            <ul className="mt-3 space-y-3">
              {history.map((entry) => (
                <li key={entry.id}>
                  <Panel className="p-4">
                    <div className="flex items-baseline gap-3">
                      {/* The source's own category ("BD Call", "Meeting Notes")
                          kept verbatim — the recruiter's word for it is the
                          useful one. */}
                      <Chip tone="mint">{entry.interaction_type}</Chip>
                      <span className="font-mono text-[12px] text-cockpit-faint">
                        {dateDe(entry.occurred_at)}
                      </span>
                    </div>
                    {entry.summary && (
                      <p
                        className={cn(
                          'mt-2 whitespace-pre-wrap text-[14px] leading-relaxed',
                          'text-cockpit-dim',
                        )}
                      >
                        {entry.summary}
                      </p>
                    )}
                  </Panel>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  )
}
