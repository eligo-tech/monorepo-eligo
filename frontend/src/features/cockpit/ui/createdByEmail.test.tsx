import { describe, expect, it } from 'vitest'

import type { ContactRowDTO } from '@/api/types'
import { t } from '@/i18n'
import { EN } from '@/i18n/en'
import { creatorLabel, memberEmailMap } from '@/auth/memberNames'

import { creatorOptions, sortByCreator } from './createdBy'

// ELI-70: "Angelegt von" names the account by its e-mail address, never by
// the Clerk id, and the Leads list can be sorted by who added each lead.

const emails = memberEmailMap([
  { userId: 'user_3LBqs20OyUuhMTOpMhrlD7byYfK', identifier: 'jonas@panam.example' },
  { userId: 'user_xaver', identifier: 'xaver@panam.example', firstName: 'Xaver', lastName: 'Huber' },
  { userId: 'user_noemail', identifier: 'just-a-username' },
])

describe('creator label (ELI-70)', () => {
  it('shows the e-mail of the account, not its id', () => {
    expect(creatorLabel('user_3LBqs20OyUuhMTOpMhrlD7byYfK', 'user_3LBqs20OyUuhMTOpMhrlD7byYfK', emails)).toBe(
      'jonas@panam.example',
    )
  })

  it('prefers the e-mail over a recorded display name', () => {
    expect(creatorLabel('user_xaver', 'Xaver', emails)).toBe('xaver@panam.example')
  })

  it('falls back to a recorded name, never to a raw id', () => {
    expect(creatorLabel('user_gone', 'Jonas', emails)).toBe('Jonas')
    expect(creatorLabel('user_gone', 'user_gone', emails)).toBeNull()
    expect(creatorLabel(null, null, emails)).toBeNull()
  })

  it('ignores an identifier that is not an e-mail address', () => {
    expect(emails.has('user_noemail')).toBe(false)
  })

  it('labels the filter choices by e-mail', () => {
    const options = creatorOptions(
      [
        { user_id: 'user_3LBqs20OyUuhMTOpMhrlD7byYfK', name: 'user_3LBqs20OyUuhMTOpMhrlD7byYfK' },
        { user_id: 'user_xaver', name: 'Xaver' },
      ],
      (id, name) => creatorLabel(id, name, emails),
    )
    expect(options.slice(2)).toEqual([
      { value: 'user_3LBqs20OyUuhMTOpMhrlD7byYfK', label: 'jonas@panam.example' },
      { value: 'user_xaver', label: 'xaver@panam.example' },
    ])
  })
})

describe('sort Leads by who added them (ELI-70)', () => {
  const row = (id: string, by: string | null) =>
    ({ manager_id: id, created_by_user_id: by, created_by_name: by }) as ContactRowDTO
  const label = (id?: string | null, name?: string | null) => creatorLabel(id, name, emails)

  it('groups by e-mail alphabetically, unknown last, keeping the list order within a person', () => {
    const rows = [row('1', 'user_xaver'), row('2', null), row('3', 'user_3LBqs20OyUuhMTOpMhrlD7byYfK'), row('4', 'user_xaver')]
    expect(sortByCreator(rows, label).map((r) => r.manager_id)).toEqual(['3', '1', '4', '2'])
  })

  it('does not reorder the list it was given', () => {
    const rows = [row('1', 'user_xaver'), row('2', 'user_3LBqs20OyUuhMTOpMhrlD7byYfK')]
    sortByCreator(rows, label)
    expect(rows.map((r) => r.manager_id)).toEqual(['1', '2'])
  })

  it('has English copy for the sort', () => {
    expect(EN['Sortieren']).toBe('Sort')
    expect(EN['Rückrufe, dann neueste']).toBe('Call-backs, then newest')
    expect(t('Angelegt von')).toBeTruthy()
  })
})
