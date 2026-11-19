// ELI-32: "Nicht mehr kontaktieren" on a person's card — the red mark with
// its date, "Wieder kontaktierbar" to undo it, and "Bestätigung senden" for
// the person who asked for it in writing. Every button is a click by a named
// person; nothing here is sent or changed on its own.

import { useEffect, useState } from 'react'
import { Ban, Mail, RotateCcw } from 'lucide-react'

import { api } from '@/api/client'
import { t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'

import { describeConfirmationError } from './erasureView'

type Subject = 'candidate' | 'manager'

/** The red chip, for a card or a list row. */
export function DoNotContactChip({ since }: { since: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-coral-600 bg-coral-800 px-2 py-0.5 font-mono text-[12px] leading-5 text-coral-300"
      title={t('Diese Person möchte nicht mehr kontaktiert werden.')}
    >
      <Ban className="h-3 w-3" />
      {t('Nicht kontaktieren · seit {date}', { date: fmtDate(since) })}
    </span>
  )
}

export function DoNotContactBanner({
  subject,
  id,
  since,
  email,
  onLifted,
}: {
  subject: Subject
  id: string
  since: string
  email: string | null | undefined
  /** The mark was undone: the page drops the banner. */
  onLifted: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [canMail, setCanMail] = useState<boolean | null>(null)

  useEffect(() => {
    if (!email) return
    let alive = true
    api
      .noticeCapability()
      .then((c) => alive && setCanMail(c.configured))
      .catch(() => alive && setCanMail(false))
    return () => {
      alive = false
    }
  }, [email])

  const lift = async () => {
    setBusy(true)
    setMessage(null)
    try {
      await api.liftDoNotContact(subject, id)
      onLifted()
    } catch {
      setMessage({ ok: false, text: t('Fehlgeschlagen — nichts geändert.') })
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    setBusy(true)
    setMessage(null)
    try {
      await api.sendDoNotContactConfirmation(subject, id)
      setMessage({ ok: true, text: t('Bestätigung an {email} gesendet.', { email: email ?? '' }) })
    } catch (e) {
      setMessage({ ok: false, text: describeConfirmationError(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-coral-600 bg-coral-800/40 px-3 py-2">
      <DoNotContactChip since={since} />
      <span className="text-[13px] text-coral-300">
        {t('Erscheint nicht mehr in Anruf- und Wiedervorlagelisten.')}
      </span>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {email && canMail === true && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void confirm()}
            className="flex items-center gap-1.5 rounded-md border border-cockpit-line px-2.5 py-1 font-mono text-[12px] text-cockpit-text hover:border-cockpit-edge disabled:opacity-40"
          >
            <Mail className="h-3.5 w-3.5" />
            {t('Bestätigung senden')}
          </button>
        )}
        {email && canMail === false && (
          <span className="font-mono text-[11px] text-cockpit-faint">
            {t('Bestätigung per E-Mail: Versand nicht eingerichtet')}
          </span>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => void lift()}
          className="flex items-center gap-1.5 rounded-md border border-cockpit-line px-2.5 py-1 font-mono text-[12px] text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text disabled:opacity-40"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          {t('Wieder kontaktierbar')}
        </button>
      </div>
      {message && (
        <p role="status" className={`w-full text-[12.5px] ${message.ok ? 'text-mint-400' : 'text-coral-300'}`}>
          {message.text}
        </p>
      )}
    </div>
  )
}
