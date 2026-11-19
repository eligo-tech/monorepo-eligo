// Sprachen with their level, as the Dossier editor edits them (ELI-56).
//
// One row per language: the name, LinkedIn's level (or none), remove. The
// rows are kept here so a level picked before the name is typed is not lost;
// the parent gets the stored form ("Englisch (Verhandlungssicher)") on every
// change, with an unnamed row as '' — which the editor's save drops.

import { useState } from 'react'
import { X } from 'lucide-react'

import { t } from '@/i18n'
import { AddButton, MiniInput } from '../../ui/forms'
import {
  LANGUAGE_LEVELS,
  joinLanguage,
  languageLevelLabel,
  splitLanguage,
  type LanguageEntry,
  type LanguageLevel,
} from '../../ui/languageLevels'

/** A row remembers the spelling it was loaded with until somebody edits it,
 *  so changing one language does not rewrite the others ("Englisch –
 *  fließend" stays as stored) and send a change nobody made. */
type Row = LanguageEntry & { stored?: string }

export const toStoredLanguages = (rows: Row[]) =>
  rows.map((r) => r.stored ?? (r.name.trim() ? joinLanguage(r) : ''))

export function LanguageListEditor({
  languages,
  onChange,
}: {
  languages: string[]
  onChange: (languages: string[]) => void
}) {
  const [rows, setRows] = useState<Row[]>(() => languages.map((l) => ({ ...splitLanguage(l), stored: l })))

  const update = (next: Row[]) => {
    setRows(next)
    onChange(toStoredLanguages(next))
  }
  const patch = (i: number, change: Partial<LanguageEntry>) =>
    update(rows.map((r, j) => (j === i ? { name: r.name, level: r.level, ...change } : r)))

  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="grid grid-cols-[1fr_auto_auto] items-center gap-2">
          <MiniInput value={row.name} onChange={(name) => patch(i, { name })} placeholder={t('Sprache, z. B. Englisch')} />
          <select
            value={row.level ?? ''}
            onChange={(e) => patch(i, { level: (e.target.value || null) as LanguageLevel | null })}
            aria-label={t('Niveau')}
            className="rounded-lg border border-cockpit-line bg-cockpit-inset px-2 py-2 text-[13px] text-cockpit-text focus:border-cockpit-edge focus:outline-none"
          >
            <option value="" className="bg-cockpit-surface">
              {t('Niveau —')}
            </option>
            {LANGUAGE_LEVELS.map((level) => (
              <option key={level} value={level} className="bg-cockpit-surface">
                {languageLevelLabel(level)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => update(rows.filter((_, j) => j !== i))}
            className="text-cockpit-faint transition-colors hover:text-coral-400"
            aria-label={t('Sprache entfernen')}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
      <AddButton label={t('+ Sprache hinzufügen')} onClick={() => update([...rows, { name: '', level: null }])} />
    </div>
  )
}
