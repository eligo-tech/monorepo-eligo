import { describe, expect, it } from 'vitest'

import { actorLabel, memberNameMap } from './memberNames'

describe('actorLabel (ELI-50)', () => {
  const names = memberNameMap([
    { userId: 'user_3LC4zJ88lXZQ3nkU7HHtROiru6X', firstName: 'Dima', lastName: 'Fadeev' },
    { userId: 'user_onlyEmail', identifier: 'ina@example.invalid' },
    { userId: 'user_nothing' },
  ])

  it('names a known member', () => {
    expect(actorLabel('user_3LC4zJ88lXZQ3nkU7HHtROiru6X', names)).toBe('Dima Fadeev')
  })

  it('falls back to the sign-in identifier', () => {
    expect(actorLabel('user_onlyEmail', names)).toBe('ina@example.invalid')
  })

  it('never returns a raw id it cannot name', () => {
    expect(actorLabel('user_nothing', names)).toBeNull()
    expect(actorLabel('user_unknown123', new Map())).toBeNull()
  })

  it('passes a recorded name through', () => {
    expect(actorLabel('Dima', names)).toBe('Dima')
    expect(actorLabel('candidate (opt-in link)', names)).toBe('candidate (opt-in link)')
  })

  it('is empty for nothing', () => {
    expect(actorLabel(null, names)).toBeNull()
    expect(actorLabel('  ', names)).toBeNull()
  })
})
