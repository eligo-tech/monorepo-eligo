import { describe, expect, it } from 'vitest'

import { isReadable, readsAfterUpload } from './attachmentRules'

describe('readsAfterUpload', () => {
  it('reads a Zeugnis or Zertifikat with a text layer right after the upload', () => {
    expect(readsAfterUpload('zeugnis', 'application/pdf')).toBe(true)
    expect(readsAfterUpload('zertifikat', 'text/plain')).toBe(true)
  })

  it('does not spend a model call on a photo — it has no text to read', () => {
    expect(readsAfterUpload('zeugnis', 'image/jpeg')).toBe(false)
    expect(readsAfterUpload('zertifikat', 'image/png')).toBe(false)
  })

  it('only stores every other kind', () => {
    for (const kind of ['cv', 'sonstiges', 'transkript'] as const) {
      expect(readsAfterUpload(kind, 'application/pdf')).toBe(false)
    }
  })

  it('isReadable decides which rows offer "Read"', () => {
    expect(isReadable('zeugnis')).toBe(true)
    expect(isReadable('cv')).toBe(false)
  })
})
