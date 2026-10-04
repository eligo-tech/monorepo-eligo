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
  /** The editor field this row stands for, so "fehlt" can open it. */
  field: string
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
        { label: 'Name', value: text(c.name), field: 'full_name' },
        { label: 'Adresse', value: text(address), field: 'street' },
        { label: 'Geburtsdatum', value: text(p?.dateOfBirth), field: 'date_of_birth' },
        { label: 'E-Mail', value: text(c.email), field: 'email' },
        { label: 'Telefon', value: text(c.phone), field: 'phone' },
      ],
    ],
    [
      'Beruf & Profil',
      [
        { label: 'Job-Titel', value: text(c.currentTitle), field: 'current_title' },
        { label: 'Branchen', value: list(p?.industries), field: 'industries' },
        { label: 'Anstellungsform', value: text(p?.employmentForm), field: 'employment_form' },
        {
          label: 'Werdegang',
          value: p?.roles?.length ? `${p.roles.length} Stationen` : null,
          field: 'work_history',
        },
        {
          label: 'Skills',
          value: p?.allSkills?.length ? `${p.allSkills.length} erfasst` : null,
          field: 'skills',
        },
        {
          label: 'LinkedIn / Xing',
          value: [c.linkedinUrl, p?.xingUrl].some(Boolean) ? 'verknüpft' : null,
          field: 'linkedin_url',
        },
      ],
    ],
    [
      'Nach dem Qualifikationsgespräch',
      [
        { label: 'Verfügbarkeit', value: text(p?.availability), field: 'availability' },
        { label: 'Kündigungsfrist', value: text(p?.noticePeriod), field: 'notice_period' },
        {
          label: 'Aktuelles Gehalt',
          value: money(p?.currentSalary, p?.salaryCurrency),
          field: 'current_salary',
        },
        {
          label: 'Mindestgehalt',
          value: money(p?.salaryMinimum, p?.salaryCurrency),
          field: 'salary_minimum',
        },
        {
          label: 'Wunschgehalt',
          value: money(p?.salaryExpectation, p?.salaryCurrency),
          field: 'salary_expectation',
        },
        { label: 'Wechselmotivation', value: text(p?.motivation), field: 'motivation' },
        // Section B of the Kandidatenauswertung, line for line. Each one was
        // a question somebody asked on the call, so each one is a row here —
        // the list is what says whether the conversation was written down.
        {
          label: 'Profil-Zusammenfassung',
          value: text(p?.profileSummary),
          field: 'profile_summary',
        },
        { label: 'Schwerpunkte', value: list(p?.focusAreas), field: 'focus_areas' },
        {
          label: 'Technisches Know-how',
          value: text(p?.technicalProfile),
          field: 'technical_profile',
        },
        {
          label: 'Höchster Abschluss',
          value: p?.education?.length ? `${p.education.length} erfasst` : null,
          field: 'education',
        },
        {
          label: 'Interview-Verfügbarkeit',
          value: text(p?.interviewAvailability),
          field: 'interview_availability',
        },
        {
          label: 'Weitere relevante Punkte',
          value: text(p?.otherNotes),
          field: 'other_notes',
        },
        { label: 'Andere Prozesse', value: text(p?.otherProcesses), field: 'other_processes' },
        {
          label: '… bei welchen Firmen',
          value: list(p?.otherProcessCompanies),
          field: 'other_process_companies',
        },
      ],
    ],
  ]
}

export function QualificationChecklist({
  candidate,
  onEdit,
}: {
  candidate: Candidate
  /** Open the editor. With a field: scrolled to it, cursor in it — tapping
   *  a gap should land in the box, not at the top of a form of forty. */
  onEdit: (field?: string) => void
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
          onClick={() => onEdit(rows.find((r) => r.value === null)?.field)}
          title="Öffnet das Formular beim ersten fehlenden Feld"
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
          <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
            {items.map((row) => (
              <button
                key={row.label}
                type="button"
                onClick={() => onEdit(row.field)}
                title={`${row.label} bearbeiten`}
                className="flex w-full items-baseline gap-2 border-t border-cockpit-line/50 py-1 text-left text-[13px] transition-colors hover:text-cockpit-text"
              >
                {row.value !== null ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mint-500" />
                ) : (
                  <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
                )}
                <span className="shrink-0 text-cockpit-faint">{row.label}</span>
                <span
                  className={cn(
                    'ml-auto min-w-0 truncate text-right',
                    row.value !== null
                      ? 'text-cockpit-text'
                      : 'text-gold-400/80 underline decoration-dotted underline-offset-4',
                  )}
                >
                  {row.value ?? 'fehlt'}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
