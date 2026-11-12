import { describe, expect, it } from 'vitest'
import { leadPhone, registerLine, telHref } from './switchboard'

// ELI-30: the employer's own Impressum is the last way to reach a company.
describe('switchboard from the Impressum', () => {
  const board = {
    phone: '+43 (0)2249 / 2241',
    vat_id: 'ATU31821909',
    register: 'FN 56945v',
    register_court: 'Innsbruck',
    impressum_url: 'https://alois-mayr.at/impressum/',
    domain: 'alois-mayr.at',
    checked_at: '2026-11-11T15:23:00Z',
  }

  it('dials only the digits and the leading plus', () => {
    expect(telHref('+43 (0)2249 / 2241')).toBe('tel:+43022492241')
    expect(telHref('0731 100-0')).toBe('tel:07311000')
  })

  it('names the register with its court', () => {
    expect(registerLine(board)).toBe('FN 56945v · Innsbruck')
    expect(registerLine({ ...board, register_court: null })).toBe('FN 56945v')
    expect(registerLine({ ...board, register: null })).toBeNull()
  })

  it('a lead without a direct number falls back to the switchboard, marked as such', () => {
    expect(leadPhone(null, board)).toEqual({ phone: '+43 (0)2249 / 2241', fromImpressum: true })
    expect(leadPhone('+49 5491 666-123', board)).toEqual({ phone: '+49 5491 666-123', fromImpressum: false })
    expect(leadPhone(null, null)).toEqual({ phone: null, fromImpressum: false })
    expect(leadPhone(null, { ...board, phone: null })).toEqual({ phone: null, fromImpressum: false })
  })
})
