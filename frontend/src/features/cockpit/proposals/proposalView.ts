// What a proposal changes, as before → after lines. Pure, so tested without a DOM.

import type { ProposalDTO } from '@/api/types'

export interface ChangeLine {
  /** The backend field name: scheduled_at · done_at · outcome · text */
  field: string
  before: string | null
  after: string
}

const STEP_FIELDS = ['scheduled_at', 'done_at', 'outcome'] as const

const asText = (v: unknown): string | null =>
  v === null || v === undefined || v === '' ? null : String(v)

export function changeLines(p: ProposalDTO): ChangeLine[] {
  if (p.kind === 'candidate_note') {
    const text = asText(p.after.text)
    return text ? [{ field: 'text', before: null, after: text }] : []
  }
  const step = (p.before.step ?? null) as Record<string, unknown> | null
  const lines: ChangeLine[] = []
  for (const field of STEP_FIELDS) {
    const after = asText(p.after[field])
    if (after === null) continue // not part of this proposal
    lines.push({ field, before: step ? asText(step[field]) : null, after })
  }
  return lines
}

export const isOpen = (p: ProposalDTO): boolean => p.status === 'pending'
