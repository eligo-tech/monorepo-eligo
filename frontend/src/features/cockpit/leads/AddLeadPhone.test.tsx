import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { ContactRowDTO, ManagerDTO, ManagerPhoneDTO } from '@/api/types'
import { t } from '@/i18n'

import { ContactRow } from '../screens/ContactListScreen'
import { appendPhone } from '../ui/phoneList'
import { AddPhoneForm, saveAddedPhone } from './AddLeadPhone'

// ELI-76: a recruiter calling leads finds a number and saves it on the
// Leads row — without opening the lead's page.

const row = (over: Partial<ContactRowDTO> = {}): ContactRowDTO =>
  ({
    manager_id: 'm1', company_id: 'c1', company_name: 'Telis Finanz AG', full_name: 'Ina Dorsch',
    role_title: null, phone: null, email: null, linkedin_url: null, xing_url: null,
    added_at: '2026-11-10T09:00:00Z', source: 'public_web', source_detail: null, art14_outstanding: false,
    last_outcome: null, last_call_at: null, last_call_by: null, next_action_at: null, due: false,
    ...over,
  }) as ContactRowDTO

const markup = (r: ContactRowDTO) => renderToStaticMarkup(<ContactRow row={r} showCompany onCalled={() => {}} />)

const held: ManagerPhoneDTO[] = [
  { number: '+49 30 1', kind: 'direct', is_primary: true },
  { number: '+49 171 2', kind: 'mobile', is_primary: false },
]

describe('"+ Nummer" on the Leads row (ELI-76)', () => {
  it('a row without a number offers it', () => {
    const html = markup(row())
    expect(html).toContain(t('keine Nummer'))
    expect(html).toContain('data-action="add-phone"')
  })

  it('a row with numbers offers it too, and lists every number', () => {
    const html = markup(row({ phone: '+49 30 1', phones: held }))
    expect(html).toContain('data-action="add-phone"')
    expect(html).toContain('+49 30 1')
    expect(html).toContain('+49 171 2')
  })

  it('the form asks for number and type, with Speichern / Abbrechen', () => {
    const html = renderToStaticMarkup(<AddPhoneForm managerId="m1" onSaved={() => {}} onCancel={() => {}} />)
    expect(html).toContain(`aria-label="${t('Art der Nummer')}"`)
    expect(html).toContain(`aria-label="${t('Telefon')}"`)
    expect(html).toContain(t('Durchwahl'))
    expect(html).toContain(t('Speichern'))
    expect(html).toContain(t('Abbrechen'))
  })
})

describe('appendPhone', () => {
  it('adds after the numbers held, the primary kept', () => {
    expect(appendPhone(held, { number: ' +49 89 3 ', kind: 'mobile' })).toEqual([
      ...held,
      { number: '+49 89 3', kind: 'mobile', is_primary: false },
    ])
  })

  it('the first number becomes the primary', () => {
    expect(appendPhone([], { number: '+49 89 3', kind: 'direct' })).toEqual([
      { number: '+49 89 3', kind: 'direct', is_primary: true },
    ])
  })

  it('refuses a blank number and one already held (digits compared)', () => {
    expect(appendPhone(held, { number: '  ', kind: 'mobile' })).toBeNull()
    expect(appendPhone(held, { number: '+49 (30) 1', kind: 'mobile' })).toBeNull()
  })
})

describe('saveAddedPhone', () => {
  const manager = { id: 'm1', phone: '+49 30 1', phones: held } as unknown as ManagerDTO

  it('reads the lead fresh and sends every number it holds plus the new one', async () => {
    const read = vi.fn(async () => manager)
    const update = vi.fn(async () => manager)
    const result = await saveAddedPhone('m1', { number: '+49 89 3', kind: 'mobile' }, { read, update })
    expect(result).toBe('saved')
    expect(read).toHaveBeenCalledWith('m1')
    expect(update).toHaveBeenCalledWith('m1', {
      phones: [...held, { number: '+49 89 3', kind: 'mobile', is_primary: false }],
      override_suppression: undefined,
    })
  })

  it('sends nothing for a number the lead already has', async () => {
    const update = vi.fn(async () => manager)
    const result = await saveAddedPhone('m1', { number: '+49 171 2', kind: 'mobile' }, { read: async () => manager, update })
    expect(result).toBe('duplicate')
    expect(update).not.toHaveBeenCalled()
  })
})
