// Aktivität & Performance — what each consultant did, against what they were
// asked to do (ELI-15).
//
// The rule the process document sets, and the one that decides this screen:
// **every figure comes from an event the system records anyway.** Nothing
// here asks anybody to count their week. A note saved against a manager is a
// Business Call; a process step reaching "Vorgestellt" is a presentation.
//
// The second rule is this file's own: **a KPI nothing measures shows no
// number.** Two of the four in the design cannot be counted today — there is
// no Contract entity and no LinkedIn connection — and a confident 0 beside a
// target of 100 is not an empty state, it is an accusation. Those two render
// the reason instead.

import { t } from '@/i18n'
import { num } from '@/i18n/format'

import { useCallback, useEffect, useState } from 'react'
import { Target as TargetIcon } from 'lucide-react'

import { api } from '@/api/client'
import type { ConsultantDTO, KpiDTO, MeDTO, TrackingDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { isAdmin } from '../useMe'
import { Button } from '../ui/forms'
import { Label, Panel, SectionHeader, SegmentedControl } from '../ui/primitives'

type Period = 'woche' | 'monat' | 'quartal'

const PERIODS: { key: Period; label: string }[] = [
  { key: 'woche', label: t('Woche') },
  { key: 'monat', label: t('Monat') },
  { key: 'quartal', label: t('Quartal') },
]

/** Where a figure sits against its goal, as a share of the bar.
 *
 *  Exported because it is the one piece of arithmetic on this screen that
 *  can be wrong in a way nobody notices: a target of 0 divides, and a
 *  consultant at 150% must not render a bar wider than its track. */
export function progress(ist: number | null, ziel: number | null): number {
  if (ist === null || ziel === null || ziel <= 0) return 0
  return Math.max(0, Math.min(1, ist / ziel))
}

/** The tone of a number against its goal.
 *
 *  Three bands rather than a gradient, and the thresholds live here so the
 *  bar and the figure cannot disagree. Below 60% of the way is coral: with
 *  a week left that is not a nudge, it is a problem. */
export function paceTone(share: number): 'mint' | 'gold' | 'coral' {
  if (share >= 0.9) return 'mint'
  if (share >= 0.6) return 'gold'
  return 'coral'
}

const BAR: Record<ReturnType<typeof paceTone>, string> = {
  mint: 'bg-mint-500',
  gold: 'bg-gold-500',
  coral: 'bg-coral-500',
}
const TEXT: Record<ReturnType<typeof paceTone>, string> = {
  mint: 'text-mint-300',
  gold: 'text-gold-300',
  coral: 'text-coral-300',
}

function Gauge({
  kpi,
  canEdit,
  onSetTarget,
}: {
  kpi: KpiDTO
  canEdit: boolean
  onSetTarget: (value: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(kpi.ziel ?? ''))

  if (!kpi.available) {
    return (
      <Panel className="p-5">
        <p className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
          {t(kpi.label)}
        </p>
        {/* No number at all. See the file header: a plausible zero here is
            something a person gets measured against. */}
        <p className="mt-3 text-[28px] font-semibold leading-none text-cockpit-faint">—</p>
        <p className="mt-3 text-[12px] leading-relaxed text-cockpit-dim">
          {t(kpi.unavailable_because)}
        </p>
      </Panel>
    )
  }

  const share = progress(kpi.ist, kpi.ziel)
  const tone = paceTone(share)

  return (
    <Panel className="p-5">
      <p className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
        {t(kpi.label)}
      </p>

      <div className="mt-3 flex items-baseline gap-2">
        <span className={cn('text-[28px] font-semibold leading-none tabular-nums', kpi.ziel !== null && TEXT[tone])}>
          {num(kpi.ist ?? 0)}
        </span>
        {kpi.ziel !== null && (
          <span className="font-mono text-[13px] text-cockpit-faint">
            / {num(kpi.ziel)}
          </span>
        )}
      </div>

      {kpi.ziel !== null ? (
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-cockpit-inset">
          <div
            className={cn('h-full rounded-full transition-[width] duration-500', BAR[tone])}
            style={{ width: `${share * 100}%` }}
          />
        </div>
      ) : (
        // "No target" and "a target of zero" are different statements, so an
        // unset goal says so rather than drawing an empty bar at 0 %.
        <p className="mt-3 text-[12px] text-cockpit-faint">{t('Kein Ziel hinterlegt')}</p>
      )}

      <p className="mt-3 font-mono text-[11px] text-cockpit-faint">
        {t('Quelle')}: {t(kpi.source)}
      </p>

      {canEdit && (
        <div className="mt-3 border-t border-cockpit-line pt-3">
          {editing ? (
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                value={draft}
                autoFocus
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    onSetTarget(Number(draft) || 0)
                    setEditing(false)
                  }
                  if (e.key === 'Escape') setEditing(false)
                }}
                className="w-24 rounded-lg border border-cockpit-line bg-cockpit-bg px-2 py-1 font-mono text-[13px] text-cockpit-text focus:border-cockpit-edge focus:outline-none"
              />
              <Button
                tone="primary"
                onClick={() => {
                  onSetTarget(Number(draft) || 0)
                  setEditing(false)
                }}
              >
                {t('Ziel setzen')}
              </Button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => {
                setDraft(String(kpi.ziel ?? ''))
                setEditing(true)
              }}
              className="flex items-center gap-1.5 font-mono text-[12px] text-cockpit-faint transition-colors hover:text-mint-300"
            >
              <TargetIcon className="h-3.5 w-3.5" />
              {kpi.ziel === null ? t('Ziel festlegen') : t('Ziel ändern')}
            </button>
          )}
        </div>
      )}
    </Panel>
  )
}

export function TrackingScreen({ me }: { me: MeDTO | null }) {
  const [period, setPeriod] = useState<Period>('monat')
  const [who, setWho] = useState('team')
  const [data, setData] = useState<TrackingDTO | null>(null)
  const [people, setPeople] = useState<ConsultantDTO[]>([])
  const [error, setError] = useState<string | null>(null)
  const admin = isAdmin(me)

  const load = useCallback(async () => {
    try {
      const [panel, consultants] = await Promise.all([
        api.tracking(period, who),
        api.consultants(),
      ])
      setData(panel)
      setPeople(consultants)
      setError(null)
    } catch {
      // A failed call says so and shows nothing. Never a mock row: a figure
      // somebody steers by must not be invented when the server is down.
      setData(null)
      setError(t('Die Zahlen konnten nicht geladen werden.'))
    }
  }, [period, who])

  useEffect(() => {
    void load()
  }, [load])

  const setTarget = async (kpi: string, value: number) => {
    try {
      await api.setTarget({
        kpi,
        period,
        value,
        // A target set while looking at one consultant is THEIR target; the
        // team view sets the default everybody else inherits.
        actor_user_id: who === 'team' ? null : who,
      })
      await load()
    } catch {
      setError(t('Das Ziel konnte nicht gespeichert werden.'))
    }
  }

  return (
    <div className="space-y-8">
      <header id="section-tracking" className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          {t('Tracking')}
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          {t('Aktivität und Zielerreichung je Consultant. Jede Zahl entsteht aus einem Ereignis, das ohnehin erfasst wird — es gibt nichts zusätzlich abzuhaken.')}
        </p>
      </header>

      <section className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <SectionHeader id="section-kpis" index="01" title={t('Aktivität & Performance')} />
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl options={PERIODS} value={period} onChange={setPeriod} size="sm" />
            <SegmentedControl
              size="sm"
              value={who}
              onChange={setWho}
              options={[
                { key: 'team', label: t('Team') },
                ...people.map((p) => ({
                  key: p.actor_user_id ?? 'unassigned',
                  // The bucket's name is copy, not a person's name: the
                  // backend has nobody to name for imported history.
                  label: p.actor_user_id === null ? t('Nicht zugeordnet') : p.name,
                })),
              ]}
            />
          </div>
        </div>

        {error && <p className="text-[13px] text-coral-400">{error}</p>}

        {data && (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {data.kpis.map((kpi) => (
                <Gauge
                  key={kpi.key}
                  kpi={kpi}
                  canEdit={admin && kpi.available}
                  onSetTarget={(value) => void setTarget(kpi.key, value)}
                />
              ))}
            </div>
            <p className="font-mono text-[11px] text-cockpit-faint">
              {t('Zeitraum')}: {new Date(data.period_start).toLocaleDateString()} –{' '}
              {new Date(data.period_end).toLocaleDateString()}
              {!admin && ` · ${t('Ziele setzen können nur Administratoren')}`}
            </p>
          </>
        )}
      </section>

      <section className="space-y-3">
        <Label>{t('Noch nicht enthalten')}</Label>
        <Panel className="p-5">
          <p className="text-[13px] leading-relaxed text-cockpit-dim">
            {t('Der Prozess-Funnel mit Quoten, Durchlaufzeiten und Absagegründen ist beschrieben, aber noch nicht gebaut — dafür fehlen dem Prozess die Stufe „2. Interview“ und ein Pflichtfeld für den Absagegrund.')}
          </p>
        </Panel>
      </section>
    </div>
  )
}
