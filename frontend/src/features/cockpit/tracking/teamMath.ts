// The arithmetic and naming of the Team-Übersicht (ELI-74). Kept apart from
// the component for the same reason as `trackingMath`: a goal of 0 divides,
// and a member named by a raw account id reads as a bug.

import { t } from '@/i18n'
import { num } from '@/i18n/format'
import type { MeDTO, TeamRowDTO } from '@/api/types'
import { actorLabel } from '@/auth/memberNames'

/** "75 %" of the goal reached; null when there is no goal (nothing to say);
 *  "—" when it cannot be computed — never a made-up 0 %. */
export function goalShare(ist: number | null, ziel: number | null): string | null {
  if (ziel === null) return null
  if (ist === null || ziel <= 0) return '—'
  return `${num(Math.round((ist / ziel) * 100))} %`
}

/** Who a row is: the member's account name, else the recorded name — never a
 *  raw id. A group by its label, else its people's names. */
export function teamRowName(row: TeamRowDTO, names: ReadonlyMap<string, string>): string {
  if (row.kind === 'unassigned') return t('Nicht zugeordnet')
  if (row.kind === 'group') {
    if (row.name) return row.name
    return row.members.map((m) => names.get(m) ?? actorLabel(m, names) ?? t('Unbekanntes Mitglied')).join(' & ')
  }
  const id = row.actor_user_id ?? ''
  return names.get(id) ?? actorLabel(row.name, names) ?? t('Unbekanntes Mitglied')
}

const RANK: Record<TeamRowDTO['kind'], number> = { person: 0, unassigned: 1, group: 2 }

/** People by name, then the unassigned bucket, then the groups. */
export function orderTeamRows(rows: TeamRowDTO[], names: ReadonlyMap<string, string>): TeamRowDTO[] {
  return [...rows].sort(
    (a, b) => RANK[a.kind] - RANK[b.kind] || teamRowName(a, names).localeCompare(teamRowName(b, names)),
  )
}

/** The ids the overview asks for: every workspace member and the admin. */
export function teamMemberIds(names: ReadonlyMap<string, string>, me: MeDTO | null): string[] {
  const ids = new Set(names.keys())
  if (me?.user_id) ids.add(me.user_id)
  return [...ids].sort()
}

/** The per-person switch, plus whoever was opened from the overview when the
 *  switch (people with activity) does not list them yet. */
export function withChosen<T extends { key: string; label: string }>(options: T[], who: string, label: string): T[] {
  if (options.some((o) => o.key === who)) return options
  return [...options, { key: who, label } as T]
}
