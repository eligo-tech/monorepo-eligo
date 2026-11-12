// ELI-30: an employer's switchboard as its own Impressum publishes it — the
// last way to reach a company when no ad names a person. Shown only when the
// Impressum names the employer as operator (checked server-side).

import type { SwitchboardDTO } from '@/api/types'

export const telHref = (phone: string) => `tel:${phone.replace(/[^\d+]/g, '')}`

/** "HRB 28871 · Essen", "FN 56945v · Innsbruck" — or null without a register. */
export const registerLine = (board: Pick<SwitchboardDTO, 'register' | 'register_court'>) =>
  board.register ? [board.register, board.register_court].filter(Boolean).join(' · ') : null

/** A lead's own number first; without one, the company's switchboard. */
export const leadPhone = (own: string | null, board: SwitchboardDTO | null | undefined) =>
  own ? { phone: own, fromImpressum: false } : board?.phone ? { phone: board.phone, fromImpressum: true } : { phone: null, fromImpressum: false }
