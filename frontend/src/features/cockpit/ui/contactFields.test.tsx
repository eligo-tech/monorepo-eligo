import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { ManagerDTO } from '@/api/types'
import { t } from '@/i18n'

import {
  ContactFields,
  EMPTY_CONTACT,
  contactDraftOf,
  contactPatch,
  contactPayload,
} from './contactFields'

// ELI-45: "Hier kann man nur die E-Mail hinzufügen." A contact created with a
// mandate got a name, a role and an e-mail — no phone — and the Manager page
// could not add one afterwards either. One set of fields now serves all three
// places, so they cannot drift apart again.

const manager = (over: Partial<ManagerDTO> = {}): ManagerDTO =>
  ({
    id: 'm1',
    company_id: 'c1',
    full_name: 'Jana Ruf',
    first_name: null,
    last_name: null,
    role_title: 'Head of IT',
    department: null,
    email: 'jana@ruf.de',
    phone: null,
    linkedin_url: null,
    ...over,
  }) as ManagerDTO

describe('ContactFields (ELI-45)', () => {
  it('offers phone, department and LinkedIn next to role and e-mail', () => {
    const html = renderToStaticMarkup(<ContactFields value={EMPTY_CONTACT} onChange={() => {}} />)
    for (const label of [t('Rolle'), t('Abteilung'), t('E-Mail'), t('Telefon'), t('LinkedIn-Profil')]) {
      expect(html).toContain(label)
    }
  })
})

describe('contactPayload', () => {
  it('trims what was typed and sends blanks as null', () => {
    expect(
      contactPayload({ ...EMPTY_CONTACT, phone: '  +49 30 123  ', email: ' ', role_title: 'CTO' }),
    ).toEqual({
      role_title: 'CTO',
      department: null,
      email: null,
      phone: '+49 30 123',
      linkedin_url: null,
    })
  })
})

describe('contactPatch', () => {
  it('sends only what changed, so an untouched address is not re-checked', () => {
    const m = manager()
    const draft = { ...contactDraftOf(m), phone: '+49 171 1' }
    expect(contactPatch(m, draft)).toEqual({ phone: '+49 171 1' })
  })

  it('clears a field the recruiter emptied', () => {
    const m = manager()
    expect(contactPatch(m, { ...contactDraftOf(m), role_title: '' })).toEqual({ role_title: null })
  })

  it('is empty when nothing changed', () => {
    const m = manager({ phone: '+49 30 1' })
    expect(contactPatch(m, contactDraftOf(m))).toEqual({})
  })
})

describe('every place that adds or edits a contact uses the same fields', () => {
  const src = (p: string) => readFileSync(resolve(__dirname, p), 'utf8')
  it.each([
    '../screens/NewMandate.tsx',
    '../screens/mandate/SetContact.tsx',
    '../screens/ManagerProfile.tsx',
  ])('%s', (file) => {
    expect(src(file)).toContain('<ContactFields')
  })
})
