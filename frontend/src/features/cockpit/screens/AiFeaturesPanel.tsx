// "KI-Funktionen" on the settings screen: switch on an AI feature by
// accepting its terms, see who did and when, switch it off again.
//
// Until this panel, accepting the AI-access terms meant pasting a fetch() into
// the browser console. The server side already existed (`/features`, versioned
// terms, a receipt per acceptance); this is only the button.
//
// The terms are shown in German in both languages on purpose: that is the
// text the server versions and the admin accepts. A translation would be a
// second text nobody accepted.

import { useCallback, useEffect, useState } from 'react'
import { Check, Copy, Sparkles } from 'lucide-react'

import { t } from '@/i18n'
import { locale } from '@/i18n/format'
import { ApiError, api } from '@/api/client'
import type { FeatureStatusDTO } from '@/api/types'
import { Button } from '../ui/forms'
import { Chip, Panel } from '../ui/primitives'
import { featureAction } from './aiFeatures'

const when = (iso: string) =>
  new Date(iso).toLocaleString(locale(), {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Berlin',
  })

function describe(e: unknown): string {
  if (!(e instanceof ApiError)) return t('Fehlgeschlagen — keine Antwort vom Server.')
  if (e.status === 403) return t('Nur Administratoren können KI-Funktionen ein- oder ausschalten.')
  if (e.status === 409) return t('Die Bedingungen wurden inzwischen geändert. Bitte die neue Fassung lesen.')
  return t('Fehlgeschlagen (HTTP {status}).', { status: String(e.status) })
}

function ConnectAddress({ url }: { url: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard blocked: the address is selectable text right beside it.
    }
  }
  return (
    <div className="mt-4 rounded-xl border border-mint-600/40 bg-mint-800/10 px-4 py-3">
      <p className="text-[13px] text-cockpit-dim">
        {t('In Claude unter Einstellungen → Konnektoren einen eigenen Konnektor mit dieser Adresse hinzufügen — genau so, ohne Schrägstrich am Ende:')}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <code className="select-all break-all rounded-md bg-cockpit-inset px-2 py-1 font-mono text-[13px] text-cockpit-text">
          {url}
        </code>
        <Button onClick={() => void copy()}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied ? t('Kopiert') : t('Kopieren')}
        </Button>
      </div>
    </div>
  )
}

function FeatureRow({
  feature,
  admin,
  onChange,
  onStale,
}: {
  feature: FeatureStatusDTO
  admin: boolean
  onChange: (next: FeatureStatusDTO) => void
  /** The terms changed under us (409): fetch the new text to read. */
  onStale: () => void
}) {
  const action = featureAction(feature, admin)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showTerms, setShowTerms] = useState(!feature.enabled)

  const run = async (call: () => Promise<FeatureStatusDTO>) => {
    setBusy(true)
    setError(null)
    try {
      const next = await call()
      onChange(next)
      setShowTerms(!next.enabled)
    } catch (e) {
      setError(describe(e))
      if (e instanceof ApiError && e.status === 409) {
        setShowTerms(true)
        onStale()
      }
    }
    setBusy(false)
  }

  return (
    <Panel className="px-6 py-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
          <Sparkles className="h-5 w-5" />
        </span>
        <h3 className="text-[16px] font-semibold text-cockpit-text">{t(feature.label)}</h3>
        <Chip tone={feature.enabled ? 'mint' : 'gold'} className="ml-auto">
          {feature.enabled ? t('aktiv') : t('aus')}
        </Chip>
      </div>

      {feature.enabled && feature.accepted_by && feature.accepted_at && (
        <p className="mt-3 text-[13px] text-cockpit-dim">
          {t('Aktiviert von {name} am {date}.', {
            name: feature.accepted_by,
            date: when(feature.accepted_at),
          })}
        </p>
      )}
      {!feature.enabled && feature.reason && (
        <p className="mt-3 text-[13px] text-cockpit-dim">{t(feature.reason)}</p>
      )}

      {feature.enabled && feature.connect_url && <ConnectAddress url={feature.connect_url} />}

      {showTerms ? (
        <div className="mt-4">
          <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-cockpit-faint">
            {t('Bedingungen · Fassung {version}', { version: feature.terms_version })}
          </span>
          <div className="mt-2 max-h-80 overflow-y-auto whitespace-pre-line rounded-xl border border-cockpit-line bg-cockpit-inset px-4 py-3 text-[13px] leading-relaxed text-cockpit-text">
            {feature.terms}
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setShowTerms(true)}
          className="mt-3 text-[13px] text-lav-300 underline-offset-2 hover:underline"
        >
          {t('Bedingungen anzeigen')}
        </button>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {action === 'accept' && (
          <Button
            tone="primary"
            disabled={busy}
            onClick={() => void run(() => api.acceptFeature(feature.key, feature.terms_version))}
          >
            {t('Bedingungen akzeptieren und aktivieren')}
          </Button>
        )}
        {action === 'revoke' && (
          <Button disabled={busy} onClick={() => void run(() => api.revokeFeature(feature.key))}>
            {t('Deaktivieren')}
          </Button>
        )}
        {action === 'wait-for-admin' && (
          <p className="text-[13px] text-cockpit-dim">
            {t('Ein Administrator dieses Workspace kann die Funktion hier aktivieren.')}
          </p>
        )}
      </div>

      {error && <p className="mt-3 text-[13px] text-coral-400">{error}</p>}
    </Panel>
  )
}

export function AiFeaturesPanel({ admin }: { admin: boolean }) {
  const [features, setFeatures] = useState<FeatureStatusDTO[] | null>(null)

  const reload = useCallback(async () => {
    try {
      setFeatures(await api.features())
    } catch {
      setFeatures([])
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const shown = (features ?? []).filter((f) => featureAction(f, admin) !== 'hidden')
  if (features === null) return null
  if (shown.length === 0) {
    return (
      <Panel className="px-6 py-5 text-[13px] text-cockpit-dim">
        {t('Für diesen Workspace ist noch keine KI-Funktion freigegeben.')}
      </Panel>
    )
  }
  return (
    <div className="space-y-4">
      {shown.map((f) => (
        <FeatureRow
          key={f.key}
          feature={f}
          admin={admin}
          onStale={() => void reload()}
          onChange={(next) =>
            setFeatures((all) => (all ?? []).map((x) => (x.key === next.key ? next : x)))
          }
        />
      ))}
    </div>
  )
}
