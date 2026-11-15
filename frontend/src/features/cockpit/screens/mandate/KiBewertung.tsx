// "Bewertung erstellen" (ELI-42) — the AI evaluation of one candidate on one
// mandate, as a PROPOSAL the recruiter accepts or discards.
//
// The backend sends the ELI-41 prompt to the configured model, checks the
// answer in code (score 0–10, technologies grounded in the candidate's own
// material, no salary or health data in the client text, failed hard filters
// repeated) and stores it as a pending proposal. Nothing reaches the
// Kandidatenauswertung until "Übernehmen" — and what is taken over is the
// checked version, not the raw answer. Every flag is shown next to it.
//
// With no model configured the button is not offered; the copy-prompt
// (ELI-41) below stays, so the recruiter can still take it to Claude.

import { t } from '@/i18n'
import { dateTime } from '@/i18n/format'

import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Sparkles } from 'lucide-react'

import { api } from '@/api/client'
import type { EvaluationDTO, EvaluationProviderDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { Button } from '../../ui/forms'
import { BewertungPrompt } from './BewertungPrompt'

/** One request per page, not per card: the answer is the same for all. */
let providerOnce: Promise<EvaluationProviderDTO> | null = null
const provider = () =>
  (providerOnce ??= api
    .evaluationProvider()
    .catch(() => ({ available: false, model: null })))

export function KiBewertung({
  applicationId,
  onChanged,
}: {
  applicationId: string
  /** The assessment changed — reload the process. */
  onChanged?: () => void
}) {
  const [key, setKey] = useState(0)
  const [busy, setBusy] = useState<'create' | 'confirm' | 'decline' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showText, setShowText] = useState(false)

  const { data: llm } = useAsync(provider, [])
  const { data: pending } = useAsync<EvaluationDTO | null>(
    () => api.evaluation(applicationId).catch(() => null),
    [applicationId, key],
  )

  async function run(action: 'create' | 'confirm' | 'decline') {
    if (busy) return
    setBusy(action)
    setError(null)
    try {
      if (action === 'create') {
        await api.evaluate(applicationId)
      } else if (pending) {
        await (action === 'confirm'
          ? api.confirmProposal(pending.id)
          : api.declineProposal(pending.id))
        if (action === 'confirm') onChanged?.()
      }
      setKey((k) => k + 1)
    } catch (exc) {
      const status = (exc as { status?: number }).status
      setError(
        action === 'create'
          ? status === 409
            ? t('Kein KI-Modell konfiguriert — bitte den Prompt kopieren.')
            : status === 429
              ? t('Zu viele KI-Aufrufe — bitte kurz warten.')
              : t('Bewertung fehlgeschlagen — nichts gespeichert.')
          : status === 409
            ? t('Die Auswertung wurde inzwischen geändert — nichts übernommen.')
            : t('Nicht gespeichert — bitte erneut versuchen.'),
      )
      setKey((k) => k + 1)
    } finally {
      setBusy(null)
    }
  }

  const a = pending?.assessment

  return (
    <div className="mt-4 space-y-3">
      {pending && a && (
        <div className="rounded-xl border border-lav-600/50 bg-lav-800/20 p-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="rounded-md border border-lav-600 px-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-lav-400">
              {t('KI')}
            </span>
            <span className="text-[14px] text-cockpit-text">
              {t('Vorschlag zur Kandidatenauswertung')}
            </span>
            <span className="font-mono text-[12px] text-cockpit-faint">
              {pending.model} · {dateTime(pending.generated_at ?? pending.created_at)}
            </span>
            {a.fit_score !== null && (
              <span className="ml-auto font-mono text-[14px] text-cockpit-text">
                {a.fit_score} / 10
              </span>
            )}
          </div>

          {a.verdict && (
            <p className="mt-3 text-[14px] leading-relaxed text-cockpit-dim">
              {a.verdict.split('\n\n')[0]}
            </p>
          )}

          {pending.flags.length > 0 && (
            <ul className="mt-3 space-y-1">
              {pending.flags.map((flag, i) => (
                <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-gold-300">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0">{flag}</span>
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            onClick={() => setShowText((open) => !open)}
            className="mt-3 flex items-center gap-1.5 font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint transition-colors hover:text-cockpit-text"
          >
            {showText ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            {t('Vollständige Antwort des Modells')}
          </button>
          {showText && pending.text && (
            <pre className="mt-2 max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-lg border border-cockpit-line bg-cockpit-inset p-3 font-sans text-[13px] leading-relaxed text-cockpit-dim">
              {pending.text}
            </pre>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button tone="primary" onClick={() => void run('confirm')} disabled={busy !== null}>
              {busy === 'confirm' ? t('Übernimmt…') : t('Übernehmen')}
            </Button>
            <Button onClick={() => void run('decline')} disabled={busy !== null}>
              {t('Verwerfen')}
            </Button>
            <span className="font-mono text-[11px] text-cockpit-faint">
              {t('Übernommen wird die geprüfte Fassung; danach unter „Auswertung bearbeiten“ änderbar.')}
            </span>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-start gap-3">
        {llm?.available && (
          <button
            type="button"
            onClick={() => void run('create')}
            disabled={busy !== null}
            title={t('Schickt den Bewertungs-Prompt an {model}. Das Ergebnis ist ein Vorschlag — gespeichert wird erst, was Sie übernehmen.', {
              model: llm.model ?? '',
            })}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-lav-600/60 px-2.5 py-1 font-mono text-[12px] text-lav-400 transition-colors hover:border-lav-400 disabled:opacity-50"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {busy === 'create'
              ? t('KI bewertet…')
              : pending
                ? t('Neu bewerten')
                : t('Bewertung erstellen')}
          </button>
        )}
        <BewertungPrompt applicationId={applicationId} />
      </div>
      {error && <p className="text-[12px] text-coral-400">{error}</p>}
    </div>
  )
}
