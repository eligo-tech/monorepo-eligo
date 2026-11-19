// The "Neue Version verfügbar" notice — see `lib/version.ts` for why.
// Mounted once, beside the app (main.tsx), so it shows on every screen and on
// the landing page. Inert in `vite dev`: there is no version.json there and
// HMR already keeps the tab current.

import { useEffect, useState } from 'react'
import { RotateCw, X } from 'lucide-react'

import { t } from '@/i18n'
import {
  createVersionWatcher,
  fetchLatestVersionId,
  shouldShowNotice,
} from '@/lib/version'

const CURRENT = __BUILD_ID__

export function NewVersionNotice() {
  const [latest, setLatest] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)

  useEffect(() => {
    if (import.meta.env.DEV) return
    const watcher = createVersionWatcher({
      current: CURRENT,
      fetchLatest: fetchLatestVersionId,
      onNewVersion: setLatest,
      isVisible: () => document.visibilityState === 'visible',
    })
    const onReturn = () => void watcher.onReturn()
    document.addEventListener('visibilitychange', onReturn)
    window.addEventListener('focus', onReturn)
    watcher.start()
    return () => {
      watcher.stop()
      document.removeEventListener('visibilitychange', onReturn)
      window.removeEventListener('focus', onReturn)
    }
  }, [])

  if (!shouldShowNotice(CURRENT, latest, dismissed)) return null

  return (
    <div
      role="status"
      className="fixed bottom-4 right-4 z-[100] flex items-center gap-3 rounded-md border border-cockpit-edge bg-cockpit-raised px-4 py-2.5 font-sans text-sm text-cockpit-text shadow-panel"
    >
      <span>{t('Neue Version verfügbar')}</span>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="inline-flex items-center gap-1.5 rounded border border-mint-500/40 px-2.5 py-1 font-mono text-xs text-mint-300 hover:bg-mint-500/10"
      >
        <RotateCw size={13} aria-hidden />
        {t('Neu laden')}
      </button>
      <button
        type="button"
        onClick={() => setDismissed(latest)}
        aria-label={t('Schließen')}
        title={t('Schließen')}
        className="text-cockpit-faint hover:text-cockpit-text"
      >
        <X size={14} aria-hidden />
      </button>
    </div>
  )
}
