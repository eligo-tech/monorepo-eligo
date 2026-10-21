// Art. 14 — telling a candidate we hold their data, and asking whether we may.
//
// This is the first thing the product sends to anyone, so the panel is built
// to make the send deliberate rather than quick: one candidate, one click, a
// confirmation step, and the exact text shown before it goes. There is no
// "send to all" here and none behind it in the API.
//
// The states a recruiter actually needs to tell apart are "nobody has asked
// them", "asked, waiting", "they said yes" and "they said no" — the last of
// which is a wall: the button does not come back, because writing again to
// somebody who asked to be removed is the message they complain about.

import { t } from '@/i18n'
import { dateTime } from '@/i18n/format'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Check, Mail, ShieldCheck, X } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { CandidateNoticeDTO, NoticeCapabilityDTO } from '@/api/types'
import { Button } from '../../ui/forms'
import { Chip } from '../../ui/primitives'

type Tone = 'mint' | 'gold' | 'coral' | 'lav'

/** Status → how it reads and how it looks. Built inside the component that
 *  renders it would be tidier, but this one is also used by the summary line,
 *  so it is a function rather than a constant — a module-level `t()` would
 *  freeze the language the page was loaded in. */
function statusLabel(status: string): { label: string; tone?: Tone } {
  switch (status) {
    case 'opted_in':
      return { label: t('Zugestimmt'), tone: 'mint' }
    case 'opted_out':
      return { label: t('Widersprochen'), tone: 'coral' }
    case 'sent':
      return { label: t('Gesendet — keine Antwort'), tone: 'gold' }
    case 'failed':
      return { label: t('Zustellung fehlgeschlagen'), tone: 'coral' }
    default:
      return { label: t('Nicht angefragt') }
  }
}

export function ConsentPanel({
  candidateId,
  candidateEmail,
}: {
  candidateId: string
  candidateEmail?: string | null
}) {
  const [notices, setNotices] = useState<CandidateNoticeDTO[] | null>(null)
  const [capability, setCapability] = useState<NoticeCapabilityDTO | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [rows, cap] = await Promise.all([
        api.candidateNotices(candidateId),
        api.noticeCapability(),
      ])
      setNotices(rows)
      setCapability(cap)
    } catch {
      // A failed read must not invent "nothing sent yet" — that is the one
      // reading that would make a recruiter send a second letter.
      setNotices(null)
      setError(t('Status konnte nicht geladen werden.'))
    }
  }, [candidateId])

  useEffect(() => {
    setConfirming(false)
    setError(null)
    void load()
  }, [load])

  const latest = notices?.[0]
  const { label, tone } = statusLabel(latest?.status ?? '')
  const settled = latest?.status === 'opted_in' || latest?.status === 'opted_out'
  const outstanding = latest?.status === 'sent'
  const canSend = Boolean(candidateEmail) && capability?.configured && !settled && !outstanding

  async function send() {
    setBusy(true)
    setError(null)
    try {
      const row = await api.sendCandidateNotice(candidateId)
      setNotices((rows) => [row, ...(rows ?? [])])
      setConfirming(false)
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 503
          ? t('Es ist kein E-Mail-Dienst konfiguriert. Bitte zuerst in den Einstellungen hinterlegen.')
          : e instanceof ApiError && e.status === 502
            ? t('Der E-Mail-Dienst hat die Nachricht abgelehnt. Prüfen Sie die Absender-Domain.')
            : e instanceof ApiError && e.status === 409
              ? t('Es kann derzeit keine Anfrage gesendet werden.')
              : t('Konnte nicht gesendet werden.'),
      )
    }
    setBusy(false)
  }

  if (notices === null && error) {
    return <p className="text-[13px] text-coral-400">{error}</p>
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={tone}>{label}</Chip>
        {latest?.responded_at && (
          <span className="font-mono text-[12px] text-cockpit-faint">
            {dateTime(latest.responded_at)}
          </span>
        )}
        {!latest?.responded_at && latest?.sent_at && (
          <span className="font-mono text-[12px] text-cockpit-faint">
            {t('gesendet')} {dateTime(latest.sent_at)}
          </span>
        )}
      </div>

      {latest?.status === 'opted_out' && (
        <p className="flex items-start gap-1.5 text-[13px] leading-relaxed text-coral-400">
          <X className="mt-0.5 h-4 w-4 shrink-0" />
          {t('Diese Person hat der Speicherung widersprochen. Es darf keine weitere Anfrage gesendet werden.')}
        </p>
      )}
      {latest?.status === 'opted_in' && (
        <p className="flex items-start gap-1.5 text-[13px] leading-relaxed text-cockpit-dim">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-mint-400" />
          {t('Die Einwilligung liegt vor und ist mit Beleg protokolliert.')}
        </p>
      )}
      {latest?.status === 'failed' && latest.failure_reason && (
        <p className="text-[12px] leading-relaxed text-coral-400">
          {latest.failure_reason}
        </p>
      )}

      {!settled && !candidateEmail && (
        <p className="text-[13px] text-cockpit-faint">
          {t('Ohne E-Mail-Adresse kann keine Anfrage gesendet werden.')}
        </p>
      )}
      {!settled && candidateEmail && capability && !capability.configured && (
        <p className="text-[13px] text-cockpit-faint">
          {t('Es ist kein E-Mail-Dienst konfiguriert. Bitte zuerst in den Einstellungen hinterlegen.')}
        </p>
      )}

      {confirming ? (
        <div className="space-y-2 rounded-md border border-cockpit-line bg-cockpit-inset p-3">
          <p className="text-[13px] leading-relaxed text-cockpit-dim">
            {t('Diese E-Mail geht an eine echte Person. Bitte prüfen Sie Empfänger und Text.')}
          </p>
          <p className="font-mono text-[12px] text-cockpit-text">{candidateEmail}</p>
          <div className="flex gap-2 pt-1">
            <Button onClick={() => setConfirming(false)}>{t('Abbrechen')}</Button>
            <Button tone="primary" onClick={send} disabled={busy}>
              {busy ? t('Sendet…') : t('Jetzt senden')}
            </Button>
          </div>
        </div>
      ) : (
        canSend && (
          <Button onClick={() => setConfirming(true)}>
            <Mail className="h-4 w-4" /> {t('Einwilligung anfragen')}
          </Button>
        )
      )}

      {error && notices !== null && (
        <p className="flex items-center gap-1.5 text-[13px] text-coral-400">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </p>
      )}

      {latest && (
        <details className="group">
          <summary className="cursor-pointer font-mono text-[12px] uppercase tracking-wide text-cockpit-faint hover:text-cockpit-dim">
            {t('Gesendeten Text anzeigen')}
          </summary>
          <p className="mt-2 whitespace-pre-wrap rounded-md border border-cockpit-line bg-cockpit-inset p-3 text-[12px] leading-relaxed text-cockpit-dim">
            {latest.body}
          </p>
          <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-cockpit-faint">
            <Check className="h-3 w-3" />
            {t('Wortlaut wie versandt. Die Bestätigungslinks sind ausgeblendet — sie gehören der Kandidatin bzw. dem Kandidaten.')}
          </p>
        </details>
      )}
    </div>
  )
}
