// Tracking (ELI-64): everything the ticket asks to be tracked, on one page —
// Business (Umsatz against its goals), Business Development, and the Prozess
// funnel. Which of these show on the Cockpit is each person's own choice
// (`tracking/CockpitTracking.tsx`); this page always shows all of them.
//
// Every figure is counted from a row the system records anyway: a note on a
// manager, a lead, a mandate, a process step, the Honorar on the Vertrag step,
// the "Rahmenvertrag abgeschlossen am" date on a company. Nothing here asks
// anybody to count their week. Goals are set by admins in Einstellungen.

import { t } from '@/i18n'
import { date } from '@/i18n/format'

import { useCallback, useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { ConsultantDTO, MeDTO, TrackingDTO, TrackingPeriod } from '@/api/types'
import { isAdmin } from '../useMe'
import { SectionHeader, SegmentedControl } from '../ui/primitives'
import { FunnelPanel, GoalsList, KpiTile } from '../tracking/TrackingParts'

export const PERIOD_OPTIONS = (): { key: TrackingPeriod; label: string }[] => [
  { key: 'woche', label: t('Woche') },
  { key: 'monat', label: t('Monat') },
  { key: 'quartal', label: t('Quartal') },
]

/** The "Team / one consultant" switch, from who has activity in the record. */
export function whoOptions(people: ConsultantDTO[]): { key: string; label: string }[] {
  return [
    { key: 'team', label: t('Team') },
    ...people.map((p) => ({
      key: p.actor_user_id ?? 'unassigned',
      // Imported history has no author; the bucket's name is copy.
      label: p.actor_user_id === null ? t('Nicht zugeordnet') : p.name,
    })),
  ]
}

export function TrackingScreen({ me }: { me: MeDTO | null }) {
  const [period, setPeriod] = useState<TrackingPeriod>('monat')
  const [who, setWho] = useState('team')
  const [data, setData] = useState<TrackingDTO | null>(null)
  const [people, setPeople] = useState<ConsultantDTO[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [panel, consultants] = await Promise.all([api.tracking(period, who), api.consultants()])
      setData(panel)
      setPeople(consultants)
      setError(null)
    } catch {
      // A failed call says so and shows nothing — never an invented figure.
      setData(null)
      setError(t('Die Zahlen konnten nicht geladen werden.'))
    }
  }, [period, who])

  useEffect(() => {
    void load()
  }, [load])

  const byGroup = (group: string) => (data?.kpis ?? []).filter((k) => k.group === group)
  const revenue = data?.kpis.find((k) => k.key === 'revenue')

  return (
    <div className="space-y-8">
      <header id="section-tracking" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          {t('Tracking')}
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          {t('Umsatz, Business Development und Prozess — je Consultant oder fürs Team. Jede Zahl entsteht aus einem Eintrag, der ohnehin gemacht wird; die Quelle steht darunter.')}
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <SegmentedControl options={PERIOD_OPTIONS()} value={period} onChange={setPeriod} size="sm" />
          <SegmentedControl size="sm" value={who} onChange={setWho} options={whoOptions(people)} />
        </div>
        {data && (
          <p className="mt-2 font-mono text-[11px] text-cockpit-faint">
            {t('Zeitraum')}: {date(data.period_start)} – {date(new Date(new Date(data.period_end).getTime() - 1))}
            {' · '}
            {isAdmin(me)
              ? t('Ziele setzen: Einstellungen › Tracking-Ziele')
              : t('Ziele setzen können nur Administratoren')}
          </p>
        )}
      </header>

      {error && <p className="text-[13px] text-coral-400">{error}</p>}

      {data && (
        <>
          <section className="space-y-4">
            <SectionHeader id="section-tracking-business" index="01" title={t('Business')} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
              {revenue && <KpiTile kpi={revenue} />}
              {revenue && <GoalsList goals={data.goals} kpi={revenue} people={people} />}
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader id="section-tracking-bd" index="02" title={t('Business Development')} tone="gold" />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {byGroup('bd').map((kpi) => (
                <KpiTile key={kpi.key} kpi={kpi} />
              ))}
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              id="section-tracking-prozess"
              index="03"
              title={t('Prozess')}
              hint={t('Verhältnis und Zeit zwischen den Schritten')}
              tone="lav"
            />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <FunnelPanel funnel={data.funnel} />
              {byGroup('prozess').map((kpi) => (
                <KpiTile key={kpi.key} kpi={kpi} />
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
