import { describe, expect, it } from 'vitest'

import { t } from '@/i18n'
import type { MeDTO, TeamRowDTO } from '@/api/types'
import { goalShare, orderTeamRows, teamMemberIds, teamRowName, withChosen } from './teamMath'

const row = (over: Partial<TeamRowDTO>): TeamRowDTO => ({
  kind: 'person',
  actor_user_id: 'user_a',
  members: ['user_a'],
  name: 'user_a',
  cells: [],
  ...over,
})

describe('goalShare', () => {
  it('is the share of the goal reached, rounded', () => {
    expect(goalShare(3, 4)).toBe('75 %')
    expect(goalShare(12_000, 10_000)).toBe('120 %')
    // Nothing done against a real goal is an honest 0 %.
    expect(goalShare(0, 10)).toBe('0 %')
  })

  it('says nothing without a goal, and "—" when it cannot be computed', () => {
    expect(goalShare(5, null)).toBeNull()
    expect(goalShare(null, 10)).toBe('—')
    // A goal of 0 has no share — never 0 % and never Infinity.
    expect(goalShare(3, 0)).toBe('—')
  })
})

describe('teamRowName', () => {
  const names = new Map([
    ['user_a', 'Anna Berg'],
    ['user_b', 'Ben Kurz'],
  ])

  it('names a member from the member list, never by raw id', () => {
    expect(teamRowName(row({}), names)).toBe('Anna Berg')
    expect(teamRowName(row({ actor_user_id: 'user_zz', name: 'user_zz' }), new Map())).toBe(t('Unbekanntes Mitglied'))
    expect(teamRowName(row({ actor_user_id: 'user_zz', name: 'Zora' }), new Map())).toBe('Zora')
  })

  it('names a group by its label, else its people', () => {
    expect(teamRowName(row({ kind: 'group', actor_user_id: null, members: ['user_a', 'user_b'], name: '' }), names)).toBe(
      'Anna Berg & Ben Kurz',
    )
    expect(teamRowName(row({ kind: 'group', actor_user_id: null, name: 'Duo' }), names)).toBe('Duo')
    expect(teamRowName(row({ kind: 'unassigned', actor_user_id: null, name: '' }), names)).toBe(t('Nicht zugeordnet'))
  })
})

describe('orderTeamRows', () => {
  it('lists people by name, then the unassigned bucket, then groups', () => {
    const rows = [
      row({ kind: 'group', actor_user_id: null, name: 'Duo' }),
      row({ kind: 'unassigned', actor_user_id: null, name: '' }),
      row({ actor_user_id: 'user_b', name: 'Ben' }),
      row({ actor_user_id: 'user_a', name: 'Anna' }),
    ]
    expect(orderTeamRows(rows, new Map()).map((r) => r.name)).toEqual(['Anna', 'Ben', '', 'Duo'])
  })
})

describe('teamMemberIds', () => {
  const me: MeDTO = { tenant_id: 't', user_id: 'user_me', name: 'Ich', role: 'admin', role_known: true }

  it('sends every member and the admin themself, once each, in a stable order', () => {
    expect(teamMemberIds(new Map([['user_b', 'B'], ['user_me', 'Ich'], ['user_a', 'A']]), me)).toEqual([
      'user_a',
      'user_b',
      'user_me',
    ])
    expect(teamMemberIds(new Map(), null)).toEqual([])
  })
})

describe('withChosen', () => {
  it('adds the person opened from the overview when the switch does not list them', () => {
    const base = [{ key: 'team', label: 'Team' }]
    expect(withChosen(base, 'user_x', 'Xaver')).toEqual([...base, { key: 'user_x', label: 'Xaver' }])
    expect(withChosen(base, 'team', 'Team')).toBe(base)
  })
})
