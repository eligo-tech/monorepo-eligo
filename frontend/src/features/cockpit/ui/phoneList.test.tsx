import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { ManagerPhoneDTO, SwitchboardDTO } from '@/api/types'
import { t } from '@/i18n'

import { PhoneList, PhoneListEditor, cleanPhones, companySwitchboard, phonesOf, phonesPatch } from './phoneList'

// ELI-46: a manager card holds several numbers, each with its kind, one
// primary; the company's Impressum switchboard is shown, never stored.

const board = (phone: string | null): SwitchboardDTO => ({
  phone,
  vat_id: null,
  register: null,
  register_court: null,
  impressum_url: null,
  domain: 'firma.de',
  checked_at: '2026-11-01T00:00:00Z',
})

const two: ManagerPhoneDTO[] = [
  { number: '+49 171 1', kind: 'mobile', is_primary: true },
  { number: '+49 30 12345-67', kind: 'direct', is_primary: false },
]

describe('phonesOf', () => {
  it('reads an older answer without `phones` as its one number', () => {
    expect(phonesOf({ phone: '+49 30 1', phones: undefined })).toEqual([
      { number: '+49 30 1', kind: 'other', is_primary: true },
    ])
    expect(phonesOf({ phone: null, phones: undefined })).toEqual([])
  })
})

describe('cleanPhones / phonesPatch', () => {
  it('drops blank rows and keeps exactly one primary', () => {
    expect(
      cleanPhones([
        { number: '  ', kind: 'mobile', is_primary: true },
        { number: ' +49 30 2 ', kind: 'direct', is_primary: false },
      ]),
    ).toEqual([{ number: '+49 30 2', kind: 'direct', is_primary: true }])
  })

  it('sends nothing when the list did not change', () => {
    expect(phonesPatch({ phone: '+49 171 1', phones: two }, two)).toBeUndefined()
  })

  it('sends the whole list when the primary moves', () => {
    const moved = two.map((p) => ({ ...p, is_primary: !p.is_primary }))
    expect(phonesPatch({ phone: '+49 171 1', phones: two }, moved)).toEqual(moved)
  })
})

describe('the company switchboard', () => {
  it('shows as "Zentrale (Firma)" when the contact does not have it', () => {
    const html = renderToStaticMarkup(<PhoneList phones={two} board={board('+49 30 999')} />)
    expect(html).toContain(t('Zentrale (Firma)'))
    expect(html).toContain('href="tel:+4930999"')
    expect(html).toContain(t('Mobil'))
    expect(html).toContain(t('Durchwahl'))
    expect(html).toContain(t('Hauptnummer'))
  })

  it('is left out when it is already one of the numbers (digits compared)', () => {
    expect(companySwitchboard(two, board('+49 (30) 1234567'))).toBeNull()
    expect(companySwitchboard(two, board(null))).toBeNull()
  })
})

// ELI-75: `FIELD` carries `w-full`, and `cn` does not merge Tailwind
// classes — so a width added next to it loses to `w-full` (later in the
// stylesheet). The type select then took the whole row and squeezed the
// number to a sliver. Pin the classes that give the number the room.
describe('the phone editor row (ELI-75)', () => {
  const html = renderToStaticMarkup(<PhoneListEditor value={two} onChange={() => {}} />)
  const classOf = (tag: string, label: string) => {
    const m = html.match(new RegExp(`<${tag}[^>]*aria-label="${label}"[^>]*>`))
    expect(m, `${tag} ${label}`).not.toBeNull()
    return (m![0].match(/class="([^"]*)"/)?.[1] ?? '').split(/\s+/)
  }

  it('keeps the type select compact — no w-full fighting its width', () => {
    const cls = classOf('select', t('Art der Nummer'))
    expect(cls).not.toContain('w-full')
    expect(cls).toContain('shrink-0')
    expect(cls.some((c) => /^w-\[/.test(c))).toBe(true)
  })

  it('gives the number the rest of the row, with a readable minimum', () => {
    const cls = classOf('input', t('Telefon'))
    expect(cls).toContain('flex-1')
    expect(cls).not.toContain('min-w-0')
    expect(cls.some((c) => /^min-w-\[/.test(c))).toBe(true)
  })

  it('wraps the row on a phone instead of squeezing it', () => {
    expect(html).toMatch(/<div class="[^"]*\bflex-wrap\b[^"]*"[^>]*><button[^>]*aria-pressed/)
  })
})
