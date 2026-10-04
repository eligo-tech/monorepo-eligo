// The Kerndaten of a candidate, as a checklist of what is there and what is
// missing.
//
// Every one of these fields was already editable — the Dossier editor behind
// "Bearbeiten" writes all of them. Nobody could find it, and a form you have
// to go looking for is a form that does not get filled in. So the record
// itself states what it still needs, in the recruiter's own grouping:
// before the Qualifikationsgespräch you usually have only the CV, and the
// rest is what the conversation is for.
//
// Each row is a claim about the record, never about the person: "fehlt"
// means nothing is stored, not that the candidate has nothing to say.

import { CheckCircle2, Circle, Pencil } from 'lucide-react'

import type { Candidate, CandidateProfile } from '@/data/types'
import { cn } from '@/lib/cn'

interface Row {
  label: string
  value: string | null
}

const money = (value: number | null | undefined, currency = 'EUR') =>
  value != null
    ? `${value.toLocaleString('de-DE')} ${currency === 'EUR' ? '€' : currency}`
    : null

const list = (values: string[] | undefined, max = 4) =>
  values && values.length > 0
    ? values.slice(0, max).join(' · ') + (values.length > max ? ` +${values.length - max}` : '')
    : null

const text = (value: string | undefined | null) => {
  const trimmed = (value ?? '').trim()
  if (!trimmed || trimmed === '—') return null
  return trimmed.length > 90 ? `${trimmed.slice(0, 90)}…` : trimmed
}

/** The four groups the recruiter's own Kerndaten list uses. */
function groups(c: Candidate, p: CandidateProfile | undefined): [string, Row[]][] {
  const address = [p?.street, [p?.postalCode, p?.city].filter(Boolean).join(' ')]
    .filter(Boolean)
    .join(', ')
  return [
    [
      'Anschrift & Kontakt',
      [
        { label: 'Name', value: text(c.name) },
        { label: 'Adresse', value: text(address) },
        { label: 'Geburtsdatum', value: text(p?.dateOfBirth) },
        { label: 'E-Mail', value: text(c.email) },
        { label: 'Telefon', value: text(c.phone) },
      ],
    ],
    [
      'Beruf & Profil',
      [
        { label: 'Job-Titel', value: text(c.currentTitle) },
        { label: 'Branchen', value: list(p?.industries) },
        { label: 'Anstellungsform', value: text(p?.employmentForm) },
        { label: 'Werdegang', value: p?.roles?.length ? `${p.roles.length} Stationen` : null },
        { label: 'Skills', value: p?.allSkills?.length ? `${p.allSkills.length} erfasst` : null },
        { label: 'LinkedIn / Xing', value: [c.linkedinUrl, p?.xingUrl].some(Boolean) ? 'verknüpft' : null },
      ],
    ],
    [
      'Nach dem Qualifikationsgespräch',
      [
        { label: 'Verfügbarkeit', value: text(p?.availability) },
        { label: 'Kündigungsfrist', value: text(p?.noticePeriod) },
        { label: 'Aktuelles Gehalt', value: money(p?.currentSalary, p?.salaryCurrency) },
        { label: 'Mindestgehalt', value: money(p?.salaryMinimum, p?.salaryCurrency) },
        { label: 'Wunschgehalt', value: money(p?.salaryExpectation, p?.salaryCurrency) },
        { label: 'Wechselmotivation', value: text(p?.motivation) },
        { label: 'Andere Prozesse', value: text(p?.otherProcesses) },
        { label: '… bei welchen Firmen', value: list(p?.otherProcessCompanies) },
      ],
    ],
  ]
}

export function QualificationChecklist({
  candidate,
  onEdit,
}: {
  candidate: Candidate
  onEdit: () => void
}) {
  const sections = groups(candidate, candidate.profile)
  const rows = sections.flatMap(([, items]) => items)
  const filled = rows.filter((r) => r.value !== null).length

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          Kerndaten
        </span>
        <span className="font-mono text-[12px] text-cockpit-faint">
          <span className="text-cockpit-text">{filled}</span> von {rows.length} erfasst
        </span>
        <button
          type="button"
          onClick={onEdit}
          className="ml-auto flex items-center gap-1.5 rounded-lg border border-cockpit-line px-2.5 py-1 text-[12px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-mint-300"
        >
          <Pencil className="h-3.5 w-3.5" /> Erfassen
        </button>
      </div>

      {sections.map(([title, items]) => (
        <div key={title} className="space-y-1">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-cockpit-faint">
            {title}
          </p>
          <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
            {items.map((row) => (
              <div
                key={row.label}
                className="flex items-baseline gap-2 border-t border-cockpit-line/50 py-1 text-[13px]"
              >
                {row.value !== null ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mint-500" />
                ) : (
                  <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
                )}
                <dt className="shrink-0 text-cockpit-faint">{row.label}</dt>
                <dd
                  className={cn(
                    'ml-auto min-w-0 truncate text-right',
                    row.value !== null ? 'text-cockpit-text' : 'text-cockpit-faint',
                  )}
                >
                  {row.value ?? 'fehlt'}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  )
}
