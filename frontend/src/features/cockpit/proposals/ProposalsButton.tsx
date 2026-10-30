// "Vorschläge": what an AI client (Claude) proposed, waiting for a person.
//
// The chip appears only while something waits. It refreshes when you come
// back to the tab — the moment after you asked Claude for a change is exactly
// when you return here. Confirming runs the same write a click in the tracker
// runs, as you; the server refuses it if the record changed in the meantime.
//
// This is the ONLY place a proposal can be applied. The AI client has no tool
// for it and its token is refused by this API (ADR 0003 §3.7).

import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, Sparkles, X } from 'lucide-react'

import { t } from '@/i18n'
import { dateTime } from '@/i18n/format'
import { ApiError, api } from '@/api/client'
import type { ProposalDTO } from '@/api/types'
import { useRefreshOnFocus } from '@/hooks/useRefreshOnFocus'
import { Button } from '../ui/forms'
import { changeLines, isOpen } from './proposalView'

const FIELD_LABEL: Record<string, () => string> = {
  scheduled_at: () => t('Termin'),
  done_at: () => t('Erledigt am'),
  outcome: () => t('Ergebnis'),
  text: () => t('Notiz'),
}

const OUTCOME_LABEL: Record<string, () => string> = {
  open: () => t('offen'),
  pass: () => t('positiv'),
}

function shown(field: string, value: string | null): string {
  if (value === null) return '—'
  if (field === 'outcome') return OUTCOME_LABEL[value]?.() ?? value
  if (field.endsWith('_at')) return dateTime(value)
  return value
}

/** The server's refusal code (`detail.code`): stale · closed · unapplicable · not_found. */
function refusalCode(e: ApiError): string | null {
  try {
    const body = JSON.parse(e.message) as { detail?: { code?: string } }
    return body.detail?.code ?? null
  } catch {
    return null
  }
}

function describe(e: unknown): string {
  if (!(e instanceof ApiError)) return t('Fehlgeschlagen — keine Antwort vom Server.')
  switch (refusalCode(e)) {
    case 'stale':
      return t('Der Datensatz wurde inzwischen geändert — nichts übernommen.')
    case 'closed':
      return t('Dieser Vorschlag ist bereits entschieden oder abgelaufen.')
    case 'unapplicable':
      return t('Der Vorschlag ließ sich nicht anwenden — nichts übernommen.')
    case 'not_found':
      return t('Diesen Vorschlag gibt es in diesem Workspace nicht.')
    default:
      return t('Fehlgeschlagen (HTTP {status}).', { status: String(e.status) })
  }
}

function ProposalCard({ p, onDone }: { p: ProposalDTO; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const decide = async (call: () => Promise<ProposalDTO>) => {
    setBusy(true)
    setError(null)
    try {
      await call()
      onDone()
    } catch (e) {
      setError(describe(e))
      // A stale or already-decided proposal is closed on the server; reload
      // so it leaves the list instead of failing on every click.
      if (e instanceof ApiError && e.status === 409) onDone()
    }
    setBusy(false)
  }

  return (
    <li className="rounded-xl border border-cockpit-line bg-cockpit-surface px-4 py-3">
      <p className="text-[14px] font-semibold text-cockpit-text">{p.title}</p>
      <p className="mt-0.5 font-mono text-[11.5px] text-cockpit-faint">
        {t('Vorgeschlagen vom KI-Assistenten für {name} · {date}', {
          name: p.asked_by_name ?? '—',
          date: dateTime(p.created_at),
        })}
      </p>

      <dl className="mt-3 space-y-1.5 text-[13px]">
        {changeLines(p).map((line) => (
          <div key={line.field} className="grid grid-cols-[7rem_1fr] gap-2">
            <dt className="text-cockpit-dim">{FIELD_LABEL[line.field]?.() ?? line.field}</dt>
            <dd className="whitespace-pre-line text-cockpit-text">
              {line.field !== 'text' && (
                <>
                  <span className="text-cockpit-faint line-through">{shown(line.field, line.before)}</span>
                  {' → '}
                </>
              )}
              <span className="text-mint-300">{shown(line.field, line.after)}</span>
            </dd>
          </div>
        ))}
      </dl>

      {p.reason && (
        <p className="mt-2 text-[12.5px] italic text-cockpit-dim">
          {t('Begründung: {reason}', { reason: p.reason })}
        </p>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Button tone="primary" disabled={busy} onClick={() => void decide(() => api.confirmProposal(p.id))}>
          <Check className="h-4 w-4" /> {t('Bestätigen')}
        </Button>
        <Button disabled={busy} onClick={() => void decide(() => api.declineProposal(p.id))}>
          <X className="h-4 w-4" /> {t('Ablehnen')}
        </Button>
      </div>
      {error && <p className="mt-2 text-[12.5px] text-coral-400">{error}</p>}
    </li>
  )
}

export function ProposalsButton() {
  const [items, setItems] = useState<ProposalDTO[]>([])
  const [open, setOpen] = useState(false)

  const reload = useCallback(async () => {
    try {
      setItems((await api.proposals(true)).filter(isOpen))
    } catch {
      // No proposals API (older backend) or no session: show nothing rather
      // than a chip that cannot be acted on.
      setItems([])
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])
  useRefreshOnFocus(() => void reload())

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  if (items.length === 0 && !open) return null

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-xl border border-lav-600/50 bg-lav-800/25 px-3 py-1.5 text-[13px] text-lav-400 hover:border-lav-400"
      >
        <Sparkles className="h-[14px] w-[14px]" />
        {t('Vorschläge · {n}', { n: items.length })}
      </button>

      {/* Portalled to <body>: the command bar's backdrop-blur makes it the
          containing block for `fixed` children, which squeezed the drawer
          into the bar's own height. */}
      {open && createPortal(
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={() => setOpen(false)}>
          <aside
            role="dialog"
            aria-modal="true"
            aria-label={t('Vorschläge vom KI-Assistenten')}
            className="h-full w-full max-w-[34rem] overflow-y-auto border-l border-cockpit-line bg-cockpit-bg px-5 py-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-[20px] font-semibold text-cockpit-text">{t('Vorschläge vom KI-Assistenten')}</h2>
                <p className="mt-1 text-[13px] leading-relaxed text-cockpit-dim">
                  {t('Nichts davon ist übernommen. Erst Ihr Klick ändert den Datensatz — und wird mit Ihrem Namen protokolliert.')}
                </p>
              </div>
              <button
                type="button"
                aria-label={t('Schließen')}
                onClick={() => setOpen(false)}
                className="rounded-md p-1 text-cockpit-faint hover:text-cockpit-text"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {items.length === 0 ? (
              <p className="mt-6 text-[13px] text-cockpit-dim">{t('Keine offenen Vorschläge.')}</p>
            ) : (
              <ul className="mt-5 space-y-3">
                {items.map((p) => (
                  <ProposalCard key={p.id} p={p} onDone={() => void reload()} />
                ))}
              </ul>
            )}
          </aside>
        </div>,
        document.body,
      )}
    </>
  )
}
