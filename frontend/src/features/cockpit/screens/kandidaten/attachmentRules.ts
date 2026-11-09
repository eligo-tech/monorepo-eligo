// Which attachments the server can read for proposals, and when an upload is
// read straight away. Kept pure so the rule is tested, not eyeballed.

import type { DocumentKind } from '@/api/types'

/** The kinds `POST /documents/{id}/read` accepts. */
export type ReadableKind = 'zeugnis' | 'zertifikat'

export function isReadable(kind: DocumentKind): kind is ReadableKind {
  return kind === 'zeugnis' || kind === 'zertifikat'
}

/** A Zeugnis or Zertifikat is read right after it is uploaded — unless it is
 *  a photo: there is no text layer, the server would refuse it, and the
 *  recruiter is better served by "stored, enter by hand" than by an error. */
export function readsAfterUpload(kind: DocumentKind, contentType: string): boolean {
  return isReadable(kind) && !contentType.startsWith('image/')
}
