// ELI-69 "Angelegt von": who added a lead, a manager or a company. Set by
// the backend from the logged-in account at creation — shown here, never
// edited. ELI-70: shown as the account's e-mail address (from the
// workspace's member list), because a default Clerk token carries no name
// and the recorded `created_by_name` is then the raw account id. The choices
// are fetched by `data/useCreators`.

import { t } from '@/i18n'

import { useCreatorLabel } from '@/auth/memberNames'
import type { CreatorDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { FIELD } from './forms'
import { Chip } from './primitives'

type Label = (userId?: string | null, recordedName?: string | null) => string | null

interface CreatorProps {
  /** The creator's account id (`created_by_user_id`). */
  userId?: string | null
  /** The name recorded at creation (`created_by_name`) — may be the raw id. */
  name?: string | null
}

/** On a list row: the e-mail, or nothing when nobody is recorded. */
export function CreatedByChip({ userId, name }: CreatorProps) {
  const label = useCreatorLabel()(userId, name)
  if (!label) return null
  return (
    <Chip title={t('Vom System beim Anlegen gesetzt, nicht änderbar.')}>{t('Angelegt von {name}', { name: label })}</Chip>
  )
}

/** On a detail page: always says it — "unbekannt" when nobody is recorded
 *  (an import, a system job, or a record older than this label). */
export function CreatedByLine({ userId, name }: CreatorProps) {
  const label = useCreatorLabel()(userId, name)
  return label ? (
    <CreatedByChip userId={userId} name={name} />
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

export function creatorOptions(creators: CreatorDTO[], label?: Label): { value: string; label: string }[] {
  return [
    { value: '', label: t('Alle') },
    { value: 'me', label: t('Ich') },
    ...creators.map((c) => ({ value: c.user_id, label: (label ? label(c.user_id, c.name) : c.name) || c.name })),
  ]
}

/** ELI-70: rows grouped by who added them — alphabetically by the shown
 *  e-mail, nobody recorded last, the list's own order kept within a person.
 *  Returns a new array. */
export function sortByCreator<R extends { created_by_user_id?: string | null; created_by_name?: string | null }>(
  rows: readonly R[],
  label: Label,
): R[] {
  const keyed = rows.map((row, i) => ({ row, i, key: label(row.created_by_user_id, row.created_by_name)?.toLowerCase() ?? null }))
  keyed.sort((a, b) => {
    if (a.key === b.key) return a.i - b.i
    if (a.key === null) return 1
    if (b.key === null) return -1
    return a.key < b.key ? -1 : 1
  })
  return keyed.map((k) => k.row)
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
  const label = useCreatorLabel()
  return (
    <label className="flex items-center gap-2 font-mono text-[12px] text-cockpit-faint">
      {t('Angelegt von')}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(FIELD, 'w-auto min-w-[140px]')}
        aria-label={t('Angelegt von')}
      >
        {creatorOptions(creators, label).map((o) => (
          <option key={o.value || 'all'} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}
