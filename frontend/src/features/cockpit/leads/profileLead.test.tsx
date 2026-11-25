import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { ApiError } from '@/api/client'
import { t } from '@/i18n'

import { EMPTY_LEAD_FORM, existingLead, leadPayload, withProfile } from './manualLead'
import { NewLead } from './NewLead'

// ELI-77: "+ Lead" from a pasted LinkedIn/XING profile link. The name is
// prefilled from the link alone (nothing is fetched), stays editable, and the
// profile goes out in one spelling so the server can spot it held already.

const filled = { ...EMPTY_LEAD_FORM, jobTitle: 'Controller', companyName: 'Ott KG' }

describe('the profile link on the + Lead form (ELI-77)', () => {
  it('prefills an empty name from the link', () => {
    const next = withProfile(filled, 'https://de.linkedin.com/in/anna-berg-1a2b3c?trk=x', '')
    expect(next.form.fullName).toBe('Anna Berg')
    expect(next.prefilled).toBe('Anna Berg')
  })

  it('never overwrites a name the recruiter typed', () => {
    const next = withProfile({ ...filled, fullName: 'Dr. Anna Berg-Schulz' }, 'https://www.xing.com/profile/Anna_Berg', '')
    expect(next.form.fullName).toBe('Dr. Anna Berg-Schulz')
  })

  it('replaces its own earlier prefill when the link changes', () => {
    const first = withProfile(filled, 'https://www.linkedin.com/in/anna-berg', '')
    const second = withProfile(first.form, 'https://www.linkedin.com/in/ben-ott', first.prefilled)
    expect(second.form.fullName).toBe('Ben Ott')
  })

  it('leaves the name alone when the link does not say it plainly', () => {
    expect(withProfile(filled, 'https://www.linkedin.com/in/annaberg', '').form.fullName).toBe('')
  })

  it('sends the profile in its one spelling', () => {
    expect(
      leadPayload({ ...filled, fullName: 'Anna Berg', profileUrl: 'de.linkedin.com/in/anna-berg-1a2b3c/?trk=x' }),
    ).toMatchObject({ profile_url: 'https://www.linkedin.com/in/anna-berg-1a2b3c' })
    expect(leadPayload({ ...filled, fullName: 'Anna Berg' })).toMatchObject({ profile_url: null })
  })

  it('a link that is not a person profile cannot be saved', () => {
    expect(leadPayload({ ...filled, fullName: 'Anna Berg', profileUrl: 'https://www.linkedin.com/company/ott' })).toBeNull()
  })

  it('the profile field comes first on the form', () => {
    const html = renderToStaticMarkup(<NewLead onCancel={() => {}} onSaved={() => {}} />)
    const profile = html.indexOf(t('LinkedIn-/XING-Profil'))
    expect(profile).toBeGreaterThan(-1)
    expect(profile).toBeLessThan(html.indexOf(t('Job *')))
  })

  it('a 409 says when the same profile is held already', () => {
    const e = new ApiError(
      409,
      JSON.stringify({ detail: { code: 'lead_exists', manager_id: 'm9', stage: 'manager', full_name: 'Anna Berg', match: 'profile' } }),
    )
    expect(existingLead(e)).toEqual({ managerId: 'm9', stage: 'manager', fullName: 'Anna Berg', byProfile: true })
  })
})
