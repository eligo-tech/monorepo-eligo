// ELI-54: employer headcount ("Mitarbeitende") on Markt.
//
// The buckets, the overlap rule and the 30% gate are the backend's
// (`app/domain/hub/headcount.py`); this file only labels them. The server
// says whether the filter is offered (`filter_available`), so the threshold
// lives in one place.

import type { HeadcountCoverageDTO } from '@/api/types'
import { t } from '@/i18n'
import { num } from '@/i18n/format'

/** The ten bucket keys, in order — the API's `employees` values. */
export const HEADCOUNT_BUCKETS = [
  '1-3',
  '4-10',
  '11-50',
  '51-150',
  '151-300',
  '301-650',
  '651-1000',
  '1001-5000',
  '5001-10000',
  '10001+',
] as const

/** "1001-5000" → "1.001–5.000"; "10001+" → "10.001+". */
export function bucketLabel(key: string): string {
  if (key.endsWith('+')) return `${num(Number(key.slice(0, -1)))}+`
  const [lo, hi] = key.split('-').map(Number)
  return `${num(lo)}–${num(hi)}`
}

/** An employer's stored value: "250", "51–200", "500+". */
export function headcountLabel(min: number, max: number | null | undefined): string {
  if (max == null) return `${num(min)}+`
  if (max === min) return num(min)
  return `${num(min)}–${num(max)}`
}

/** Whether Markt shows the filter, and the coverage to name when it does not. */
export function headcountGate(coverage: HeadcountCoverageDTO | null | undefined): {
  show: boolean
  percent: number
} {
  const percent = Math.round((coverage?.coverage ?? 0) * 100)
  return { show: !!coverage?.filter_available, percent }
}

/** Where a value came from, for its tooltip. */
export function headcountSource(source: string | null | undefined): string {
  if (source === 'ad_text') return t('aus einer Stellenanzeige des Unternehmens')
  if (source === 'wikidata') return t('aus Wikidata')
  if (source === 'eures') return t('aus EURES')
  return ''
}
