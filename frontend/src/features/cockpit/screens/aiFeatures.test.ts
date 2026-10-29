import { describe, expect, it } from 'vitest'

import type { FeatureStatusDTO } from '@/api/types'
import { featureAction } from './aiFeatures'

const base: FeatureStatusDTO = {
  key: 'mcp',
  label: 'KI-Zugriff (MCP)',
  available: true,
  enabled: false,
  reason: 'Ein Administrator muss den Bedingungen zustimmen.',
  terms_version: '2026-10-29',
  terms: 'Bedingungen',
  accepted_by: null,
  accepted_at: null,
  connect_url: 'https://x.example/mcp',
}

describe('what a feature row offers', () => {
  it('an admin can accept an available feature', () => {
    expect(featureAction(base, true)).toBe('accept')
  })
  it('a recruiter sees it but cannot accept', () => {
    expect(featureAction(base, false)).toBe('wait-for-admin')
  })
  it('an admin can withdraw an enabled feature; a recruiter cannot', () => {
    const on = { ...base, enabled: true, reason: null }
    expect(featureAction(on, true)).toBe('revoke')
    expect(featureAction(on, false)).toBe('none')
  })
  it('a feature the operator has not released is not shown at all', () => {
    expect(featureAction({ ...base, available: false }, true)).toBe('hidden')
  })
})
