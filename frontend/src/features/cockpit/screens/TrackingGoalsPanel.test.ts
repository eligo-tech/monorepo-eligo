import { describe, expect, it } from 'vitest'

import type { ConsultantDTO, MeDTO } from '@/api/types'
import { goalPeople } from './TrackingGoalsPanel'

const me: MeDTO = { tenant_id: 't', user_id: 'user_me', name: 'Ich', role: 'admin', role_known: true }

describe('goalPeople', () => {
  it('offers every workspace member, even one with no activity yet', () => {
    const active: ConsultantDTO[] = [{ actor_user_id: 'user_jonas', name: 'Jonas', events: 12 }]
    const members = new Map([
      ['user_jonas', 'Jonas Albrecht'],
      ['user_xaver', 'Xaver Huber'],
    ])
    const ids = goalPeople(active, me, members).map((p) => p.actor_user_id)
    expect(ids).toContain('user_xaver')
    expect(ids).toContain('user_jonas')
    expect(ids).toContain('user_me')
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('names a member by their account name rather than a raw id', () => {
    const active: ConsultantDTO[] = [{ actor_user_id: 'user_abc', name: 'user_abc', events: 3 }]
    const people = goalPeople(active, null, new Map([['user_abc', 'Anna Berg']]))
    expect(people.find((p) => p.actor_user_id === 'user_abc')?.name).toBe('Anna Berg')
  })

  it('keeps the unattributed bucket out and works without a member list', () => {
    const active: ConsultantDTO[] = [
      { actor_user_id: null, name: '', events: 40 },
      { actor_user_id: 'user_jonas', name: 'Jonas', events: 2 },
    ]
    expect(goalPeople(active, me, new Map()).map((p) => p.actor_user_id)).toEqual(['user_jonas', 'user_me'])
  })
})
