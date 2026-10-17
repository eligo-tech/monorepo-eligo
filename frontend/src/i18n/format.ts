// Numbers and dates in whichever language is on.
//
// There were fourteen files with `'de-DE'` written into them and one with
// `'en-GB'`, which is how an inconsistency survives: each one is right where
// it stands and nobody sees the set. The locale is now derived once from the
// active language, so `1.250` becomes `1,250` and `17.10.2026` becomes
// `17/10/2026` on the same switch that changes the words.
//
// en-GB rather than en-US on purpose: day before month, like the German it
// sits beside, so a date in a shared screenshot cannot be read two ways.

import { getLang } from './index'

export const locale = (): 'de-DE' | 'en-GB' =>
  getLang() === 'en' ? 'en-GB' : 'de-DE'

/** A plain number: thousands separated the way the language does it. */
export const num = (n: number): string => n.toLocaleString(locale())

/** An amount with its currency symbol, no decimals — the cockpit deals in
 *  salary bands and fees, where cents are noise. */
export function money(n: number, currency = 'EUR'): string {
  return new Intl.NumberFormat(locale(), {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(n)
}

export function date(
  iso: string | Date,
  options: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit', year: 'numeric' },
): string {
  const d = typeof iso === 'string' ? new Date(iso) : iso
  return d.toLocaleDateString(locale(), options)
}

export function time(iso: string | Date): string {
  const d = typeof iso === 'string' ? new Date(iso) : iso
  return d.toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' })
}

export function dateTime(
  iso: string | Date,
  options: Intl.DateTimeFormatOptions = {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  },
): string {
  const d = typeof iso === 'string' ? new Date(iso) : iso
  return d.toLocaleString(locale(), options)
}
