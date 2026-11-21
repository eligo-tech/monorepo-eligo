// Einstellungen › Tracking-Ziele (ELI-64): where admins set the goals.
//
// Three kinds, because the ticket names all three:
//   * Team-Standard — one number every consultant without their own inherits;
//   * one consultant's own goal, optionally from a start date ("Xaver … ab
//     1. Januar");
//   * a goal SHARED by several consultants ("bei Jonas und mir gilt der
//     Umsatz zusammen") — measured on the sum of their deals.
// Goals are never seeded: the workspace enters its own numbers here.

import { t } from '@/i18n'
import { date } from '@/i18n/format'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Trash2 } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import { useMemberNames } from '@/auth/memberNames'
import type { ConsultantDTO, KpiDTO, MeDTO, TargetDTO, TrackingPeriod } from '@/api/types'
import { Button, FIELD, FieldLabel, SelectInput, TextInput } from '../ui/forms'
import { Panel } from '../ui/primitives'
import { formatValue, goalName } from '../tracking/trackingMath'
import { PERIOD_OPTIONS } from './TrackingScreen'

const GROUP = '__group__'
const TEAM = '__team__'

/** The people a goal can name: every member of the workspace (Clerk's member
 *  list — somebody new has nothing in the record yet but still needs a goal),
 *  everyone with activity, and the admin themself. A member's account name
 *  wins over whatever the record holds, which may be a bare user id. */
export function goalPeople(
  people: ConsultantDTO[],
  me: MeDTO | null,
  members: ReadonlyMap<string, string> = new Map(),
): ConsultantDTO[] {
  const named = people
    .filter((p) => p.actor_user_id !== null)
    .map((p) => ({ ...p, name: members.get(p.actor_user_id as string) ?? p.name }))
  const known = new Set(named.map((p) => p.actor_user_id))
  for (const [id, name] of members) {
    if (!known.has(id)) {
      named.push({ actor_user_id: id, name, events: 0 })
      known.add(id)
    }
  }
  if (me?.user_id && !known.has(me.user_id)) {
    named.push({ actor_user_id: me.user_id, name: me.name, events: 0 })
  }
  return named
}

export function TrackingGoalsPanel({ admin, me }: { admin: boolean; me: MeDTO | null }) {
  const [targets, setTargets] = useState<TargetDTO[]>([])
  const [kpis, setKpis] = useState<KpiDTO[]>([])
  const [people, setPeople] = useState<ConsultantDTO[]>([])
  const [error, setError] = useState<string | null>(null)

  const [kpi, setKpi] = useState('revenue')
  const [period, setPeriod] = useState<TrackingPeriod>('monat')
  const [forWhom, setForWhom] = useState(TEAM)
  const [members, setMembers] = useState<string[]>([])
  const [label, setLabel] = useState('')
  const [value, setValue] = useState('')
  const [validFrom, setValidFrom] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [rows, panel, consultants] = await Promise.all([
        api.targets(),
        api.tracking('monat'),
        api.consultants(),
      ])
      setTargets(rows)
      setKpis(panel.kpis.filter((k) => k.available))
      setPeople(consultants)
      setError(null)
    } catch {
      setError(t('Die Ziele konnten nicht geladen werden.'))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const memberNames = useMemberNames()
  const choosable = useMemo(() => goalPeople(people, me, memberNames), [people, me, memberNames])
  const unit = kpis.find((k) => k.key === kpi)?.unit ?? 'count'
  const kpiLabel = (key: string) => t(kpis.find((k) => k.key === key)?.label ?? key)

  const save = async () => {
    const amount = Number(value)
    if (!value.trim() || !Number.isFinite(amount) || amount < 0) {
      setError(t('Bitte einen Zielwert eingeben.'))
      return
    }
    if (forWhom === GROUP && members.length < 2) {
      setError(t('Ein gemeinsames Ziel braucht mindestens zwei Personen.'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.setTarget({
        kpi,
        period,
        value: Math.round(amount),
        actor_user_id: forWhom === TEAM || forWhom === GROUP ? null : forWhom,
        members: forWhom === GROUP ? members : [],
        label: forWhom === GROUP ? label.trim() || null : null,
        valid_from: validFrom || null,
      })
      setValue('')
      setValidFrom('')
      setMembers([])
      setLabel('')
      await load()
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? t('Ziele setzen können nur Administratoren')
          : t('Das Ziel konnte nicht gespeichert werden.'),
      )
    }
    setBusy(false)
  }

  const remove = async (id: string) => {
    try {
      await api.deleteTarget(id)
      await load()
    } catch {
      setError(t('Das Ziel konnte nicht gelöscht werden.'))
    }
  }

  const whom = (row: TargetDTO) =>
    row.members.length > 0
      ? goalName(row, choosable)
      : row.actor_user_id
        ? goalName({ label: null, members: [row.actor_user_id] }, choosable)
        : t('Team-Standard')

  const periodLabel = (p: string) => PERIOD_OPTIONS().find((o) => o.key === p)?.label ?? p

  return (
    <Panel className="space-y-5 px-6 py-5">
      <p className="text-[13px] leading-relaxed text-cockpit-dim">
        {t('Ziele je Kennzahl und Zeitraum: als Standard fürs Team, für eine Person (auch ab einem Startdatum) oder gemeinsam für mehrere Personen. Personen erscheinen hier, sobald sie etwas im System erfasst haben.')}
      </p>

      {targets.length > 0 && (
        <ul className="divide-y divide-cockpit-line rounded-xl border border-cockpit-line">
          {targets.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[13px]">
              <span className="min-w-[160px] text-cockpit-text">{whom(row)}</span>
              <span className="text-cockpit-dim">{kpiLabel(row.kpi)}</span>
              <span className="font-mono tabular-nums text-cockpit-text">
                {formatValue(row.value, kpis.find((k) => k.key === row.kpi)?.unit ?? 'count')} / {periodLabel(row.period)}
              </span>
              {row.valid_from && (
                <span className="font-mono text-[12px] text-cockpit-faint">
                  {t('ab {date}', { date: date(row.valid_from) })}
                </span>
              )}
              {admin && (
                <button
                  type="button"
                  onClick={() => void remove(row.id)}
                  aria-label={t('Ziel löschen')}
                  title={t('Ziel löschen')}
                  className="ml-auto text-cockpit-faint transition-colors hover:text-coral-400"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {admin ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <SelectInput
              label={t('Kennzahl')}
              value={kpi}
              onChange={setKpi}
              options={kpis.map((k) => ({ value: k.key, label: t(k.label) }))}
            />
            <SelectInput
              label={t('Zeitraum')}
              value={period}
              onChange={(v) => setPeriod(v as TrackingPeriod)}
              options={PERIOD_OPTIONS().map((o) => ({ value: o.key, label: o.label }))}
            />
            <SelectInput
              label={t('Für')}
              value={forWhom}
              onChange={setForWhom}
              options={[
                { value: TEAM, label: t('Team-Standard') },
                ...choosable.map((p) => ({ value: p.actor_user_id ?? '', label: p.name })),
                { value: GROUP, label: t('Mehrere Personen gemeinsam') },
              ]}
            />
            <TextInput
              label={unit === 'eur' ? t('Ziel (€)') : t('Ziel')}
              type="number"
              value={value}
              onChange={setValue}
            />
          </div>

          {forWhom === GROUP && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {choosable.map((p) => {
                  const id = p.actor_user_id ?? ''
                  return (
                    <label
                      key={id}
                      className="flex cursor-pointer items-center gap-2 rounded-lg border border-cockpit-line px-3 py-1.5 text-[13px] text-cockpit-text"
                    >
                      <input
                        type="checkbox"
                        checked={members.includes(id)}
                        onChange={() =>
                          setMembers((m) => (m.includes(id) ? m.filter((x) => x !== id) : [...m, id]))
                        }
                      />
                      {p.name}
                    </label>
                  )
                })}
              </div>
              <div className="max-w-sm">
                <TextInput label={t('Bezeichnung (optional)')} value={label} onChange={setLabel} />
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <label className="block">
              <FieldLabel>{t('Gilt ab (optional)')}</FieldLabel>
              <input
                type="date"
                value={validFrom}
                onChange={(e) => setValidFrom(e.target.value)}
                className={FIELD}
              />
            </label>
            <Button tone="primary" onClick={() => void save()} disabled={busy}>
              {busy ? t('Speichert…') : t('Ziel speichern')}
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-[13px] text-cockpit-faint">{t('Ziele setzen können nur Administratoren')}</p>
      )}

      {error && <p className="text-[13px] text-coral-400">{error}</p>}
    </Panel>
  )
}
