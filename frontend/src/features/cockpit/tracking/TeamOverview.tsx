// Team-Übersicht (ELI-74): every member side by side, against their goals.
// "Ich als Admin muss das Tracking der einzelnen Mitarbeiter überwachen
// können." Presentational — the Tracking screen fetches and passes the data.
//
// Every cell is counted by the backend from the same rows as the tiles above
// it. A figure nothing measures is "—"; a percentage shows only where that
// person has a goal, and a goal of 0 has no percentage at all.

import { t } from '@/i18n'
import { num } from '@/i18n/format'

import type { TeamCellDTO, TeamDTO, TeamRowDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Panel } from '../ui/primitives'
import { formatValue, paceTone, progress } from './trackingMath'
import { goalShare, orderTeamRows, teamRowName } from './teamMath'

const TONE: Record<ReturnType<typeof paceTone>, string> = {
  mint: 'text-mint-300',
  gold: 'text-gold-300',
  coral: 'text-coral-300',
}

function Cell({ cell, unit }: { cell: TeamCellDTO | undefined; unit: 'count' | 'eur' }) {
  if (!cell || cell.ist === null) {
    return <span className="text-cockpit-faint">—</span>
  }
  const share = goalShare(cell.ist, cell.ziel)
  return (
    <div className="space-y-0.5">
      <div className="font-mono text-[14px] tabular-nums text-cockpit-text">{formatValue(cell.ist, unit)}</div>
      {share !== null && cell.ziel !== null && (
        <div
          className={cn(
            'font-mono text-[11px] tabular-nums',
            share === '—' ? 'text-cockpit-faint' : TONE[paceTone(progress(cell.ist, cell.ziel))],
          )}
          title={
            cell.ziel_from === 'team'
              ? t('Team-Standard')
              : cell.ziel_from === 'shared'
                ? t('gemeinsames Ziel')
                : t('Eigenes Ziel')
          }
        >
          {share} · {t('Ziel')} {formatValue(cell.ziel, unit)}
          {cell.ziel_from === 'team' && <span className="text-cockpit-faint"> · {t('Team-Standard')}</span>}
        </div>
      )}
      {cell.missing > 0 && (
        <div className="font-mono text-[11px] text-gold-300">
          {cell.missing === 1 ? t('1 Deal ohne Honorar') : t('{n} Deals ohne Honorar', { n: num(cell.missing) })}
        </div>
      )}
    </div>
  )
}

function rowKey(row: TeamRowDTO): string {
  return `${row.kind}:${row.actor_user_id ?? row.members.join(',')}`
}

export function TeamOverview({
  data,
  names,
  onOpen,
}: {
  data: TeamDTO
  names: ReadonlyMap<string, string>
  /** Opens one person's detailed view: their id, or 'unassigned'. */
  onOpen: (who: string, label: string) => void
}) {
  const rows = orderTeamRows(data.rows, names)
  return (
    <Panel className="p-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left">
          <thead>
            <tr className="border-b border-cockpit-line">
              <th className="px-4 py-3 font-mono text-[11px] font-medium uppercase tracking-wide text-cockpit-faint">
                {t('Mitarbeiter')}
              </th>
              {data.kpis.map((kpi) => (
                <th
                  key={kpi.key}
                  className="px-4 py-3 font-mono text-[11px] font-medium uppercase tracking-wide text-cockpit-faint"
                  title={t(kpi.source)}
                >
                  {t(kpi.label)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const name = teamRowName(row, names)
              const who = row.kind === 'unassigned' ? 'unassigned' : row.actor_user_id
              const byKey = new Map(row.cells.map((c) => [c.key, c]))
              return (
                <tr
                  key={rowKey(row)}
                  className={cn(
                    'border-b border-cockpit-line align-top last:border-0',
                    who && 'cursor-pointer hover:bg-cockpit-raised',
                  )}
                  onClick={who ? () => onOpen(who, name) : undefined}
                >
                  <td className="px-4 py-3">
                    {who ? (
                      <button
                        type="button"
                        className="text-left text-[14px] font-medium text-cockpit-text hover:underline"
                        onClick={(e) => {
                          e.stopPropagation()
                          onOpen(who, name)
                        }}
                      >
                        {name}
                      </button>
                    ) : (
                      <span className="text-[14px] font-medium text-cockpit-text">{name}</span>
                    )}
                    {row.kind === 'group' && (
                      <div className="font-mono text-[11px] uppercase tracking-wide text-cockpit-faint">
                        {t('gemeinsames Ziel')}
                      </div>
                    )}
                  </td>
                  {data.kpis.map((kpi) => (
                    <td key={kpi.key} className="px-4 py-3">
                      <Cell cell={byKey.get(kpi.key)} unit={kpi.unit} />
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-cockpit-line px-4 py-3 text-[12px] leading-relaxed text-cockpit-dim">
        {t('Prozent = Anteil am Ziel der Person (eigenes Ziel, sonst Team-Standard); ohne Ziel steht nur die Zahl. Gemeinsame Ziele stehen als eigene Zeile und zählen nicht in die Quote einer einzelnen Person. Eine Zeile öffnet die Einzelansicht.')}
      </p>
    </Panel>
  )
}
