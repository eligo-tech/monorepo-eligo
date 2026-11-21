// ELI-69 "Angelegt von": who added a lead, a manager or a company. Set by
// the backend from the logged-in account at creation (`created_by_name`, the
// account's name at that moment) — shown here, never edited. Presentational:
// the choices are fetched by `data/useCreators`.

import { t } from '@/i18n'

import type { CreatorDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { FIELD } from './forms'
import { Chip } from './primitives'

/** On a list row: the name, or nothing when nobody is recorded. */
export function CreatedByChip({ name }: { name?: string | null }) {
  if (!name) return null
  return <Chip title={t('Vom System beim Anlegen gesetzt, nicht änderbar.')}>{t('Angelegt von {name}', { name })}</Chip>
}

/** On a detail page: always says it — "unbekannt" when nobody is recorded
 *  (an import, a system job, or a record older than this label). */
export function CreatedByLine({ name }: { name?: string | null }) {
  return name ? (
    <CreatedByChip name={name} />
  ) : (
    <span
      className="font-mono text-[12px] text-cockpit-faint"
      title={t('Importiert, vom System angelegt oder älter als diese Angabe.')}
    >
      {t('Angelegt von: unbekannt')}
    </span>
  )
}

/** The filter's value: '' = Alle, 'me' = Ich, else an account id. */
export type CreatedByChoice = string

export function creatorOptions(creators: CreatorDTO[]): { value: string; label: string }[] {
  return [
    { value: '', label: t('Alle') },
    { value: 'me', label: t('Ich') },
    ...creators.map((c) => ({ value: c.user_id, label: c.name })),
  ]
}

export function CreatedByFilter({
  value,
  onChange,
  creators,
}: {
  value: CreatedByChoice
  onChange: (v: CreatedByChoice) => void
  creators: CreatorDTO[]
}) {
  return (
    <label className="flex items-center gap-2 font-mono text-[12px] text-cockpit-faint">
      {t('Angelegt von')}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(FIELD, 'w-auto min-w-[140px]')}
        aria-label={t('Angelegt von')}
      >
        {creatorOptions(creators).map((o) => (
          <option key={o.value || 'all'} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}
