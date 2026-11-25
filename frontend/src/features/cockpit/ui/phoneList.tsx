// ELI-46: a contact has as many numbers as it has — Mobil, Durchwahl,
// Zentrale, Sonstige — and one of them is the primary. The primary is what
// `phone` carries, so the Leads list and "Anruf erfassen" keep dialling it.
//
// The company's switchboard from its Impressum is shown next to them,
// read-only and labelled "Zentrale (Firma)": it belongs to the company, not
// to the person, and is never stored on the contact.

import { Phone, Plus, Star, Trash2 } from 'lucide-react'

import { t } from '@/i18n'
import type { ManagerDTO, ManagerPhoneDTO, PhoneKind, SwitchboardDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { FIELD_BOX } from './forms'
import { telHref } from './switchboard'

export const PHONE_KINDS: PhoneKind[] = ['mobile', 'direct', 'switchboard', 'other']

export const phoneKindLabel = (kind: string): string =>
  kind === 'mobile'
    ? t('Mobil')
    : kind === 'direct'
      ? t('Durchwahl')
      : kind === 'switchboard'
        ? t('Zentrale')
        : t('Sonstige')

/** Every number, the primary first. An older answer without `phones`
 *  still shows its one number. */
export function phonesOf(m: Pick<ManagerDTO, 'phone' | 'phones'>): ManagerPhoneDTO[] {
  if (m.phones) return m.phones
  return m.phone ? [{ number: m.phone, kind: 'other', is_primary: true }] : []
}

const digits = (n: string) => n.replace(/\D/g, '')

/** The company's switchboard, unless the contact already has that number. */
export function companySwitchboard(
  phones: ManagerPhoneDTO[],
  board: SwitchboardDTO | null | undefined,
): string | null {
  const phone = board?.phone
  if (!phone) return null
  const held = new Set(phones.map((p) => digits(p.number)))
  return held.has(digits(phone)) ? null : phone
}

/** What the editor holds: blank rows allowed while typing. */
export type PhoneDraft = ManagerPhoneDTO[]

/** The list to send: trimmed, blanks dropped, exactly one primary (the
 *  marked one, else the first). */
export function cleanPhones(draft: PhoneDraft): ManagerPhoneDTO[] {
  const rows = draft
    .map((p) => ({ ...p, number: p.number.trim() }))
    .filter((p) => p.number)
  const primary = Math.max(0, rows.findIndex((p) => p.is_primary))
  return rows.map((p, i) => ({ ...p, is_primary: i === primary }))
}

/** The list if it changed, else undefined — an unchanged list is not sent,
 *  so it is not checked against the erasure list again. */
export function phonesPatch(
  m: Pick<ManagerDTO, 'phone' | 'phones'>,
  draft: PhoneDraft,
): ManagerPhoneDTO[] | undefined {
  const next = cleanPhones(draft)
  const key = (rows: ManagerPhoneDTO[]) =>
    JSON.stringify(
      [...rows]
        .sort((a, b) => Number(b.is_primary) - Number(a.is_primary))
        .map((p) => [p.number, p.kind, p.is_primary]),
    )
  return key(next) === key(phonesOf(m)) ? undefined : next
}

export function PhoneListEditor({
  value,
  onChange,
}: {
  value: PhoneDraft
  onChange: (next: PhoneDraft) => void
}) {
  const set = (i: number, patch: Partial<ManagerPhoneDTO>) =>
    onChange(value.map((p, j) => (j === i ? { ...p, ...patch } : p)))
  const makePrimary = (i: number) => onChange(value.map((p, j) => ({ ...p, is_primary: j === i })))
  const remove = (i: number) => onChange(value.filter((_, j) => j !== i))
  const add = () =>
    onChange([...value, { number: '', kind: 'mobile', is_primary: value.length === 0 }])

  return (
    <div className="space-y-2" data-field="phones">
      <span className="block font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
        {t('Telefonnummern')}
      </span>
      {value.map((p, i) => (
        // ELI-75: the number takes the rest of the row and never less than
        // a readable width; on a phone it wraps onto a line of its own.
        <div key={i} className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => makePrimary(i)}
            aria-pressed={p.is_primary}
            title={p.is_primary ? t('Hauptnummer') : t('Als Hauptnummer festlegen')}
            className={cn(
              'shrink-0 rounded p-1 transition-colors',
              p.is_primary ? 'text-gold-400' : 'text-cockpit-faint hover:text-gold-400',
            )}
          >
            <Star className={cn('h-4 w-4', p.is_primary && 'fill-current')} />
          </button>
          <select
            value={p.kind}
            onChange={(e) => set(i, { kind: e.target.value as PhoneKind })}
            aria-label={t('Art der Nummer')}
            className={cn(FIELD_BOX, 'w-[8.5rem] shrink-0')}
          >
            {PHONE_KINDS.map((k) => (
              <option key={k} value={k} className="bg-cockpit-surface">
                {phoneKindLabel(k)}
              </option>
            ))}
          </select>
          <input
            value={p.number}
            onChange={(e) => set(i, { number: e.target.value })}
            placeholder="+49 30 1234567"
            aria-label={t('Telefon')}
            className={cn(FIELD_BOX, 'min-w-[11rem] flex-1 font-mono')}
          />
          <button
            type="button"
            onClick={() => remove(i)}
            title={t('Nummer entfernen')}
            className="shrink-0 rounded p-1 text-cockpit-faint transition-colors hover:text-coral-400"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="flex items-center gap-1.5 font-mono text-[12px] text-mint-400 transition-colors hover:text-mint-300"
      >
        <Plus className="h-3.5 w-3.5" />
        {t('Nummer hinzufügen')}
      </button>
    </div>
  )
}

/** The numbers on the manager card, each with its kind and a tel: link. */
export function PhoneList({
  phones,
  board,
}: {
  phones: ManagerPhoneDTO[]
  board?: SwitchboardDTO | null
}) {
  const company = companySwitchboard(phones, board)
  if (!phones.length && !company) return null
  return (
    <ul className="space-y-1">
      {phones.map((p) => (
        <li key={p.number} className="flex flex-wrap items-center gap-x-2">
          <a href={telHref(p.number)} className="flex items-center gap-1 text-mint-400 hover:underline">
            <Phone className="h-3.5 w-3.5 text-cockpit-faint" />
            {p.number}
          </a>
          <span className="font-mono text-[11px] text-cockpit-faint">{phoneKindLabel(p.kind)}</span>
          {p.is_primary && phones.length > 1 && (
            <span className="rounded border border-gold-600/50 px-1.5 text-[11px] text-gold-400">
              {t('Hauptnummer')}
            </span>
          )}
        </li>
      ))}
      {company && (
        <li
          className="flex flex-wrap items-center gap-x-2"
          title={t('Die Zentrale der Firma laut Impressum — nicht beim Kontakt gespeichert.')}
        >
          <a href={telHref(company)} className="flex items-center gap-1 text-cockpit-dim hover:text-mint-400">
            <Phone className="h-3.5 w-3.5 text-cockpit-faint" />
            {company}
          </a>
          <span className="font-mono text-[11px] text-cockpit-faint">{t('Zentrale (Firma)')}</span>
        </li>
      )}
    </ul>
  )
}
