// The tracking tiles on the Cockpit start page (ELI-64).
//
// *"Welche im Cockpit auf der Startseite angezeigt werden, soll jeder selbst
// konfigurieren können."* The choice is stored per person on the server
// (`/activity/preferences`), so it follows them to another browser; until
// they choose, the default set shows (Umsatz, Business Calls, Leads).
// The numbers are this month's, for the whole team — the Tracking page has
// the switches.

import { t } from '@/i18n'

import { useCallback, useEffect, useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'

import { api } from '@/api/client'
import type { ConsultantDTO, KpiDTO, TrackingDTO } from '@/api/types'
import { Button } from '../ui/forms'
import { Panel, SectionHeader } from '../ui/primitives'
import { FunnelPanel, GoalsList, KpiTile } from './TrackingParts'
import { PROCESS_TILE } from './trackingMath'

/** The tiles a person can pick from, in the Tracking page's order. */
export function tileChoices(kpis: KpiDTO[]): { key: string; label: string }[] {
  return [
    ...kpis.map((k) => ({ key: k.key, label: t(k.label) })),
    { key: PROCESS_TILE, label: t('Prozess: Verhältnis und Zeit je Schritt') },
  ]
}

/** Toggle one tile, keeping the chosen order. */
export function toggleTile(tiles: string[], key: string): string[] {
  return tiles.includes(key) ? tiles.filter((k) => k !== key) : [...tiles, key]
}

export function CockpitTracking({ onOpenTracking }: { onOpenTracking?: () => void }) {
  const [data, setData] = useState<TrackingDTO | null>(null)
  const [people, setPeople] = useState<ConsultantDTO[]>([])
  const [tiles, setTiles] = useState<string[] | null>(null)
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    Promise.all([api.tracking('monat'), api.trackingTiles(), api.consultants().catch(() => [])])
      .then(([panel, chosen, consultants]) => {
        if (!live) return
        setData(panel)
        setTiles(chosen.tiles)
        setPeople(consultants)
      })
      .catch(() => live && setError(t('Die Zahlen konnten nicht geladen werden.')))
    return () => {
      live = false
    }
  }, [])

  const save = useCallback(async (next: string[]) => {
    setTiles(next)
    try {
      await api.setTrackingTiles(next)
      setError(null)
    } catch {
      setError(t('Auswahl nicht gespeichert — bitte erneut versuchen.'))
    }
  }, [])

  if (error && !data) {
    return <p className="text-[13px] text-coral-400">{error}</p>
  }
  if (!data || tiles === null) return null

  const byKey = new Map(data.kpis.map((k) => [k.key, k]))

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <SectionHeader id="section-cockpit-tracking" title={t('Tracking')} hint={t('Dieser Monat · Team')} />
        <div className="flex items-center gap-2">
          <Button onClick={() => setEditing((e) => !e)}>
            <SlidersHorizontal className="h-4 w-4" />
            {editing ? t('Fertig') : t('Kacheln wählen')}
          </Button>
          {onOpenTracking && <Button onClick={onOpenTracking}>{t('Alle Zahlen')}</Button>}
        </div>
      </div>

      {editing && (
        <Panel className="p-4">
          <p className="mb-3 text-[13px] text-cockpit-dim">
            {t('Welche Zahlen sollen hier stehen? Die Auswahl gilt nur für Sie.')}
          </p>
          <div className="flex flex-wrap gap-2">
            {tileChoices(data.kpis).map((choice) => {
              const on = tiles.includes(choice.key)
              return (
                <label
                  key={choice.key}
                  className="flex cursor-pointer items-center gap-2 rounded-lg border border-cockpit-line px-3 py-1.5 text-[13px] text-cockpit-text"
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => void save(toggleTile(tiles, choice.key))}
                  />
                  {choice.label}
                </label>
              )
            })}
          </div>
        </Panel>
      )}
      {error && <p className="text-[13px] text-coral-400">{error}</p>}

      {tiles.length === 0 ? (
        <p className="text-[13px] text-cockpit-faint">
          {t('Keine Kacheln gewählt — über „Kacheln wählen“ wieder einblenden.')}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {tiles.map((key) => {
            if (key === PROCESS_TILE) {
              return (
                <div key={key} className="sm:col-span-2 xl:col-span-3">
                  <FunnelPanel funnel={data.funnel} />
                </div>
              )
            }
            const kpi = byKey.get(key)
            if (!kpi) return null
            return (
              <div key={key} className="space-y-2">
                <KpiTile kpi={kpi} compact />
                {key === 'revenue' && <GoalsList goals={data.goals} kpi={kpi} people={people} />}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
