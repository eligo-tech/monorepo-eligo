// The one dialog behind `withReaddConfirm`. Mounted once in the cockpit shell.

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ShieldAlert } from 'lucide-react'

import { date } from '@/i18n/format'
import { t } from '@/i18n'

import { registerReaddAsker } from './readd'

export function ReaddHost() {
  const [asking, setAsking] = useState<string | null>(null)
  const answer = useRef<((yes: boolean) => void) | null>(null)

  useEffect(
    () =>
      registerReaddAsker(
        (requestedOn) =>
          new Promise<boolean>((resolve) => {
            answer.current = resolve
            setAsking(requestedOn)
          }),
      ),
    [],
  )

  const close = (yes: boolean) => {
    answer.current?.(yes)
    answer.current = null
    setAsking(null)
  }

  useEffect(() => {
    if (!asking) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [asking])

  if (!asking) return null
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 px-4" onClick={() => close(false)}>
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="readd-title"
        className="w-full max-w-md rounded-lg border border-gold-600 bg-cockpit-bg p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <p id="readd-title" className="flex items-center gap-2 text-[15px] text-gold-300">
          <ShieldAlert className="h-5 w-5" />
          {t('Diese Person hat die Löschung ihrer Daten verlangt')}
        </p>
        <p className="mt-3 text-[13.5px] leading-relaxed text-cockpit-dim">
          {t('Am {date} wurde sie auf eigenen Wunsch aus diesem Workspace gelöscht. Lege sie nur wieder an, wenn sie sich seitdem selbst wieder gemeldet hat — zum Beispiel mit einer neuen Bewerbung.', { date: date(asking, { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' }) })}
        </p>
        <p className="mt-2 text-[12.5px] text-cockpit-faint">
          {t('Der alte Datensatz aus dem ATS bleibt gesperrt. Die Freigabe wird mit deinem Namen protokolliert.')}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            autoFocus
            onClick={() => close(false)}
            className="rounded-md border border-cockpit-line px-3 py-1.5 text-[13px] text-cockpit-text hover:bg-cockpit-surface"
          >
            {t('Nicht anlegen')}
          </button>
          <button
            type="button"
            onClick={() => close(true)}
            className="rounded-md border border-gold-600 bg-gold-800 px-3 py-1.5 text-[13px] text-gold-300 hover:bg-gold-600/40"
          >
            {t('Sie hat sich wieder gemeldet — anlegen')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
