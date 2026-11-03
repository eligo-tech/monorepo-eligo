// Pure helpers for the Agenturen screen: what a reason says, which tone a
// verdict wears, and whether this workspace sees the tab at all.
//
// The agency finder is Eligo's own business development — private recruiters
// are competitors to every customer. The backend answers its routes only for
// workspaces on `agency_finder_tenants` and 404s everyone else, so the tab is
// shown exactly when an authenticated probe succeeds. Any other answer, or no
// answer, hides it: a customer's screen must not hint that it exists.

import type { AgencyReasonDTO, AgencyVerdict, ContactCandidateDTO } from '@/api/types'
import { num } from '@/i18n/format'
import { t } from '@/i18n'
import type { Tone } from '../../ui/primitives'

const n = (v: unknown): number => (typeof v === 'number' ? v : 0)
const s = (v: unknown): string => (typeof v === 'string' ? v : '')

const ads = (count: number) =>
  count === 1 ? t('1 Anzeige') : t('{n} Anzeigen', { n: num(count) })

/** One reason as the chip reads it, evidence included. */
export function reasonText(reason: AgencyReasonDTO): string {
  const e = reason.evidence ?? {}
  const pts = reason.points != null ? `+${reason.points} · ` : ''
  switch (reason.code) {
    case 'name':
      return t('Name: {name}', { name: s(e.name) })
    case 'client_phrase':
      return t('»Unser Mandant« o. ä. in {ads}', { ads: ads(n(e.postings)) })
    case 'mail_domain':
      return t('Kontakt-Domain: {domains}', {
        domains: (Array.isArray(e.domains) ? e.domains : []).join(', '),
      })
    case 'field_spread':
      return t('{n} Berufsfelder', { n: num(n(e.fields)) })
    case 'also_employer':
      return t('auch als Arbeitgeber im Korpus')
    case 'public_body':
      return t('öffentliche Stelle: {name}', { name: s(e.name) })
    case 'size':
      return pts + t('{n} offene Anzeigen', { n: num(n(e.open_postings)) })
    case 'sole_trader':
      return pts + t('Einzelunternehmen oder kleine Rechtsform')
    case 'new_7d':
      return pts + t('{ads} in 7 Tagen neu', { ads: ads(n(e.postings)) })
    case 'new_28d':
      return pts + t('{ads} in 28 Tagen neu', { ads: ads(n(e.postings)) })
    case 'hiring_recruiters':
      return pts + t('sucht selbst Recruiter ({n})', { n: num(n(e.postings)) })
    default:
      // A newer backend may send a code this build does not know. Show it
      // rather than hide evidence or crash.
      return reason.code
  }
}

export const VERDICT_LABEL: Record<AgencyVerdict, string> = {
  agency: t('Agentur'),
  unclear: t('Unklar'),
  client: t('Kunde'),
}

export const verdictTone = (verdict: AgencyVerdict): Tone | undefined =>
  verdict === 'agency' ? 'mint' : verdict === 'unclear' ? 'gold' : undefined

/** True only when the server answers the probe with 200. */
export async function probeAgencyFinder(probe: () => Promise<Response>): Promise<boolean> {
  try {
    return (await probe()).status === 200
  } catch {
    return false
  }
}

/** The screen list, with Agenturen after Projekte when this workspace may see it. */
export function withAgencyScreen<K extends string, O extends { key: K | 'agenturen'; label: string }>(
  screens: O[],
  allowed: boolean,
): (O | { key: 'agenturen'; label: string })[] {
  if (!allowed) return screens
  const at = screens.findIndex((o) => o.key === 'projekte')
  const entry = { key: 'agenturen' as const, label: t('Agenturen') }
  return at < 0 ? [...screens, entry] : [...screens.slice(0, at + 1), entry, ...screens.slice(at + 1)]
}

/** The contact to store with an adopted agency. Read from a public ad, so
 *  `public_web` — a third-party origin, which queues the GDPR Art. 14 notice —
 *  and the ad itself as the answer to "where did you get my data?". */
export function contactPayload(c: ContactCandidateDTO) {
  return {
    full_name: c.full_name,
    role_title: c.role_title,
    email: c.email,
    phone: c.phone,
    source: 'public_web' as const,
    source_detail: (c.evidence[0]?.url ?? `hub_job_postings/${c.evidence[0]?.posting_id}`).slice(0, 500),
  }
}
