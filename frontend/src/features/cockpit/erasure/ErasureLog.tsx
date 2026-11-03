// Einstellungen → Löschanträge. What the workspace has erased, when the
// person asked, who carried it out — and every block lifted since, because
// a lift lets that person be created again. Names nobody.

import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { ErasureRequestDTO } from '@/api/types'
import { date, dateTime } from '@/i18n/format'
import { t } from '@/i18n'

import { Panel } from '../ui/primitives'
import { summary, unprotected } from './erasureView'

const day = (iso: string) =>
  date(iso, { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' })

export function ErasureLog({ admin }: { admin: boolean }) {
  const [rows, setRows] = useState<ErasureRequestDTO[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!admin) return
    let alive = true
    api
      .erasureRequests()
      .then((r) => alive && setRows(r))
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [admin])

  if (!admin) {
    return (
      <Panel className="px-6 py-5 text-[13px] text-cockpit-dim">
        {t('Nur Administratoren sehen und bearbeiten Löschanträge.')}
      </Panel>
    )
  }
  if (failed) {
    return <Panel className="px-6 py-5 text-[13px] text-coral-300">{t('Löschanträge konnten nicht geladen werden.')}</Panel>
  }
  if (rows === null) {
    return <Panel className="px-6 py-5 text-[13px] text-cockpit-faint">{t('Lädt…')}</Panel>
  }
  if (rows.length === 0) {
    return (
      <Panel className="px-6 py-5 text-[13px] text-cockpit-dim">
        {t('Noch keine Löschanträge. Gelöscht wird auf der Seite der Person: Kandidat:in oder Kontakt öffnen, ganz unten „Person löschen“.')}
      </Panel>
    )
  }
  return (
    <Panel className="divide-y divide-cockpit-line">
      {rows.map((r) => (
        <div key={r.id} className="px-6 py-4 text-[13px]">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-cockpit-text">
              {r.subject_type === 'candidate' ? t('Kandidat:in') : t('Kontakt')} ·{' '}
              {r.reason === 'objection' ? t('Widerspruch (Art. 21)') : t('Löschung (Art. 17)')}
            </span>
            <span className="font-mono text-[12px] text-cockpit-faint">
              {t('verlangt {asked} · erledigt {done}', { asked: day(r.requested_on), done: dateTime(r.created_at) })}
            </span>
          </div>
          <p className="mt-1 text-cockpit-dim">
            {summary(r.counts)}
            {r.executed_by_name ? ` · ${t('durch {name}', { name: r.executed_by_name })}` : ''}
          </p>
          {unprotected(r.counts) && (
            <p className="mt-1 text-gold-300">{t('Ohne Sperre: weder E-Mail-Adresse noch Import-ID vorhanden.')}</p>
          )}
          {r.lifted > 0 && r.last_lifted_at && (
            <p className="mt-1 text-gold-300">
              {t('Sperre aufgehoben am {date} durch {name} — die Person hat sich wieder gemeldet.', {
                date: dateTime(r.last_lifted_at),
                name: r.last_lifted_by ?? t('unbekannt'),
              })}
            </p>
          )}
        </div>
      ))}
    </Panel>
  )
}
