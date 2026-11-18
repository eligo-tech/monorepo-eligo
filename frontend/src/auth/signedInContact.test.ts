import { describe, expect, it } from 'vitest'

import { contactFromUser } from './signedInContact'

describe('contactFromUser (ELI-20)', () => {
  it('takes the full name and the primary address', () => {
    expect(
      contactFromUser({ fullName: 'Dima Fadeev', primaryEmailAddress: { emailAddress: 'd@example.invalid' } }),
    ).toEqual({ name: 'Dima Fadeev', email: 'd@example.invalid' })
  })

  it('builds the name from its parts', () => {
    expect(contactFromUser({ firstName: 'Ina', lastName: 'Berg' }).name).toBe('Ina Berg')
  })

  it('is empty without a user', () => {
    expect(contactFromUser(null)).toEqual({ name: '', email: '' })
  })
})
