// "Rahmenvertrag abgeschlossen am …" on the company page (ELI-64).
//
// There is no contract entity; the tracking KPI "Rahmenvertrag
// abgeschlossen" counts this date, set by a person, in the period it falls
// in. Taking it back ("entfernen") removes it from the count.

import { t } from '@/i18n'
import { date } from '@/i18n/format'

import { useState } from 'react'
import { FileSignature } from 'lucide-react'

import { api } from '@/api/client'
import { Button, FIELD } from '../ui/forms'

/** Today as YYYY-MM-DD in the viewer's own calendar, not UTC's. */
export function todayIso(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function FrameworkContractLine({
  companyId,
  signedOn,
  byName,
  onDone,
}: {
  companyId: string
  signedOn: string | null
  byName: string | null
  onDone: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(signedOn ?? todayIso())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const write = async (value: string | null) => {
    setBusy(true)
    setError(null)
    try {
      await api.setFrameworkContract(companyId, value)
      setEditing(false)
      onDone()
    } catch {
      setError(t('Nicht gespeichert — bitte erneut versuchen.'))
    }
    setBusy(false)
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px]">
      <FileSignature className="h-3.5 w-3.5 text-cockpit-faint" />
      <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
        {t('Rahmenvertrag')}
      </span>
      {editing ? (
        <>
          <input
            type="date"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className={`${FIELD} w-auto`}
          />
          <Button tone="primary" disabled={busy || !draft} onClick={() => void write(draft)}>
            {t('Speichern')}
          </Button>
          <Button onClick={() => setEditing(false)}>{t('Abbrechen')}</Button>
        </>
      ) : signedOn ? (
        <>
          <span className="text-mint-300">
            {t('abgeschlossen am {date}', { date: date(signedOn) })}
          </span>
          {byName && <span className="text-cockpit-faint">· {byName}</span>}
          <button
            type="button"
            onClick={() => {
              setDraft(signedOn)
              setEditing(true)
            }}
            className="text-cockpit-faint underline-offset-2 hover:text-cockpit-text hover:underline"
          >
            {t('ändern')}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void write(null)}
            className="text-cockpit-faint underline-offset-2 hover:text-coral-400 hover:underline"
          >
            {t('entfernen')}
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={() => {
            setDraft(todayIso())
            setEditing(true)
          }}
          className="text-cockpit-dim underline-offset-2 hover:text-mint-300 hover:underline"
        >
          {t('Rahmenvertrag abgeschlossen …')}
        </button>
      )}
      {error && <span className="text-coral-400">{error}</span>}
    </div>
  )
}
