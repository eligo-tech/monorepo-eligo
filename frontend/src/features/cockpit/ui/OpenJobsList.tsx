// ELI-33: "Offene Stellen" — the company's open jobs in Markt and its careers
// page. Used on the company page (all) and on the manager page (the first few).

import { t } from '@/i18n'
import { locale } from '@/i18n/format'
import { ExternalLink } from 'lucide-react'
import type { CompanyMarketDTO } from '@/api/types'
import { jobsShown } from './openJobs'

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(locale(), { day: '2-digit', month: '2-digit', year: 'numeric' }) : null

export function CareersLink({ market }: { market: CompanyMarketDTO }) {
  if (!market.careers) return null
  return (
    <a
      href={market.careers.url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-[13px] text-mint-400 hover:text-mint-300"
    >
      <ExternalLink className="h-3.5 w-3.5" />
      {market.careers.kind === 'careers' ? t('Karriereseite') : t('Website')}
    </a>
  )
}

export function OpenJobs({
  market,
  limit = 50,
  companyHref,
}: {
  market: CompanyMarketDTO
  limit?: number
  /** Where "… weitere" leads (the company page), when only a few are shown. */
  companyHref?: string
}) {
  if (!market.linked)
    return (
      <p className="text-[13px] text-cockpit-dim">
        {t('Noch nicht mit dem Markt verknüpft. Unternehmen mit gleichem Namen und Ort werden täglich automatisch verknüpft.')}
      </p>
    )
  if (market.total === 0)
    return <p className="text-[13px] text-cockpit-dim">{t('Im Markt gerade keine offene Stelle.')}</p>
  const { shown, more } = jobsShown(market, limit)
  return (
    <div>
      <ul>
        {shown.map((j, i) => (
          <li key={`${j.title}-${i}`} className="flex flex-wrap items-baseline gap-x-3 border-b border-cockpit-line/60 py-1.5 last:border-0">
            {j.url ? (
              <a href={j.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 text-[13px] text-cockpit-text hover:text-mint-400">
                {j.title}
              </a>
            ) : (
              <span className="min-w-0 flex-1 text-[13px] text-cockpit-text">{j.title}</span>
            )}
            {j.city && <span className="text-[12px] text-cockpit-faint">{j.city}</span>}
            {j.posted_at && <span className="font-mono text-[11px] text-cockpit-faint">{day(j.posted_at)}</span>}
          </li>
        ))}
      </ul>
      {more > 0 &&
        (companyHref ? (
          <a href={companyHref} className="mt-1 inline-block text-[12px] text-mint-400 hover:text-mint-300">
            {t('+ {n} weitere', { n: String(more) })}
          </a>
        ) : (
          <p className="mt-1 text-[12px] text-cockpit-faint">{t('+ {n} weitere', { n: String(more) })}</p>
        ))}
    </div>
  )
}
