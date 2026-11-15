// "Bewertungs-Prompt kopieren" (ELI-41) — on a candidate's card in the mandate.
//
// The recruiters evaluate a candidate by pasting the job, the briefing, the
// CV and the transcript into Claude by hand, against a fixed schema. Eligo
// holds all of it, so the backend assembles the prompt (no model call) and
// this copies it. Claude's answer comes back through "Nach dem Gespräch
// erfassen", whose parser reads the same schema — the recruiter saves.
//
// When the browser refuses the clipboard (an insecure origin, a denied
// permission), the prompt is shown in a field to copy by hand rather than
// the button failing silently.

import { t } from '@/i18n'
import { num } from '@/i18n/format'

import { useState } from 'react'
import { ClipboardCopy } from 'lucide-react'

import { api } from '@/api/client'
import type { EvaluationPromptDTO } from '@/api/types'

export function BewertungPrompt({ applicationId }: { applicationId: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<EvaluationPromptDTO | null>(null)
  const [copied, setCopied] = useState(false)

  async function copy() {
    if (busy) return
    setBusy(true)
    setError(null)
    setCopied(false)
    try {
      const body = await api.evaluationPrompt(applicationId)
      setResult(body)
      try {
        await navigator.clipboard.writeText(body.prompt)
        setCopied(true)
      } catch {
        setCopied(false) // the field below is the fallback
      }
    } catch {
      setError(t('Prompt konnte nicht erstellt werden — bitte erneut versuchen.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 space-y-2">
      <button
        type="button"
        onClick={() => void copy()}
        disabled={busy}
        title={t('Stellt Suchprofil, Briefing, Profil, Notizen und Dokumente zu einem Prompt für Claude zusammen — ohne KI-Aufruf.')}
        className="inline-flex items-center gap-1.5 rounded-lg border border-cockpit-line px-2.5 py-1 font-mono text-[12px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-lav-400disabled:opacity-50"
      >
        <ClipboardCopy className="h-3.5 w-3.5" />
        {busy ? t('Stellt zusammen…') : t('Bewertungs-Prompt kopieren')}
      </button>

      {error && <p className="text-[12px] text-coral-400">{error}</p>}

      {result && (
        <div className="space-y-2">
          <p className="font-mono text-[12px] text-cockpit-faint">
            {copied
              ? t('Kopiert · {chars} Zeichen — in Claude einfügen, die Antwort unter „Nach dem Gespräch erfassen“ zurückkopieren.', {
                  chars: num(result.chars),
                })
              : t('Zwischenablage nicht verfügbar — bitte aus dem Feld kopieren.')}
          </p>
          <p className="font-mono text-[11px] text-cockpit-faint">
            {t('Enthält: {sources}', { sources: result.sources.join(' · ') })}
          </p>
          {!copied && (
            <textarea
              readOnly
              value={result.prompt}
              rows={8}
              onFocus={(e) => e.currentTarget.select()}
              className="w-full rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 font-mono text-[12px] leading-relaxed text-cockpit-dim focus:border-cockpit-edge focus:outline-none"
            />
          )}
        </div>
      )}
    </div>
  )
}
