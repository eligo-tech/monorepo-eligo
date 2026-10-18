// Candidate dossier drawer.
//
// The layout is the argument: the ORIGINAL uploaded CV on the left (the evidence),
// the PARSED record extracted from it on the right (the claim). Side by side, a
// recruiter can check any field against its source — which is the whole product
// thesis rendered as a screen.

import { locale } from '@/i18n/format'

import { t } from '@/i18n'

import { useEffect, useState } from 'react'
import {
  Briefcase,
  Building2,
  CalendarClock,
  ChevronsLeft,
  ChevronsRight,
  Download,
  FileText,
  FileWarning,
  GraduationCap,
  Languages,
  Mail,
  MapPin,
  Paperclip,
  Pencil,
  Phone,
  ShieldCheck,
  Sparkles,
  User,
  Wallet,
} from 'lucide-react'
import type { Candidate, CandidateProfile } from '@/data/types'
import type { CandidateDTO } from '@/api/types'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useAsync'
import { Avatar } from '@/components/ui/Avatar'
import { LinkedInMark } from '@/components/ui/LinkedInMark'
import { cn } from '@/lib/cn'
import { Chip } from '../../ui/primitives'
import { Button, CloseButton, Drawer } from '../../ui/forms'
import { HistoryTrail } from '../../ui/HistoryTrail'
import { AssignToMandate } from './AssignToMandate'
import { QualificationChecklist } from './QualificationChecklist'
import { AttachmentsPanel } from './AttachmentsPanel'
import { DossierEditor } from './DossierEditor'

export function CandidateDrawer({
  candidate,
  onClose,
  onSaved,
  onPipelineChanged,
}: {
  candidate: Candidate
  onClose: () => void
  /** Called after a manual edit is persisted, with the fresh record. */
  onSaved?: (updated: CandidateDTO) => void
  /** Called after an assignment: the cockpit's board just changed, and the
   *  next thing the recruiter does is open it. */
  onPipelineChanged?: () => void
}) {
  const [cvUrl, setCvUrl] = useState<string | null>(null)
  const [cvState, setCvState] = useState<'loading' | 'ready' | 'missing'>('loading')
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  // Which box the reader asked for, when they came from a "fehlt" row.
  const [focusField, setFocusField] = useState<string | undefined>(undefined)
  const [dto, setDto] = useState<CandidateDTO | null>(null)
  const [dtoError, setDtoError] = useState(false)

  // Which mandates this person is running on. The cockpit links here; without
  // the way back, the record is a dead end — you read the CV and then have to
  // find the search again by name.
  const [runsKey, setRunsKey] = useState(0)
  const { data: runs } = useAsync(
    () =>
      api
        .processes()
        .then((jobs) =>
          jobs
            .filter((j) => j.candidates.some((c) => c.candidate_id === candidate.id))
            .map((j) => ({ id: j.job_id, title: j.job_title, client: j.company_name })),
        )
        .catch(() => []),
    [candidate.id, runsKey],
  )

  async function startEdit(field?: string) {
    setExpanded(true)
    setEditing(true)
    setFocusField(field)
    setDtoError(false)
    if (!dto) {
      try {
        setDto(await api.candidate(candidate.id))
      } catch {
        setDtoError(true)
      }
    }
  }

  function handleSaved(updated: CandidateDTO) {
    setDto(updated)
    setEditing(false)
    onSaved?.(updated)
  }

  // Fetch the original CV as a blob → object URL for the embedded viewer.
  useEffect(() => {
    let url: string | null = null
    let alive = true
    setCvState('loading')
    api
      .candidateCv(candidate.id)
      .then((blob) => {
        if (!alive) return
        if (!blob) return setCvState('missing')
        url = URL.createObjectURL(blob)
        setCvUrl(url)
        setCvState('ready')
      })
      .catch(() => alive && setCvState('missing'))
    return () => {
      alive = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [candidate.id])

  const p = candidate.profile
  const salary =
    p?.salaryExpectation != null
      ? fmtMoney(p.salaryExpectation, p.salaryCurrency)
      : p?.currentSalary != null
        ? fmtMoney(p.currentSalary, p.salaryCurrency)
        : undefined
  const address = [p?.street, [p?.postalCode, p?.city].filter(Boolean).join(' '), p?.country]
    .filter(Boolean)
    .join(', ')
  const skills = p?.allSkills.length ? p.allSkills : candidate.skills.map((s) => s.label)
  const roles = p?.roles.length ? p.roles : null
  const education = p?.education ?? []

  return (
    <Drawer onClose={onClose} wide={expanded}>
      {/* Header */}
      <div className="flex items-start justify-between gap-4 border-b border-cockpit-line bg-cockpit-surface px-8 py-5">
        <div className="flex items-center gap-4">
          <Avatar initials={candidate.initials} tone={candidate.avatar} size="lg" />
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[20px] font-semibold leading-tight text-cockpit-text">
                {candidate.name}
              </h2>
              {candidate.linkedinUrl && <LinkedInMark href={candidate.linkedinUrl} />}
            </div>
            <p className="mt-0.5 text-[14px] text-cockpit-dim">
              {candidate.currentTitle}
              {candidate.currentCompany !== '—' && ` · ${candidate.currentCompany}`}
            </p>
          </div>
        </div>

        <div className="relative flex items-center gap-2">
          <AssignToMandate
            candidateId={candidate.id}
            assignedJobIds={(runs ?? []).map((r) => r.id)}
            onAssigned={() => {
              setRunsKey((k) => k + 1)
              onPipelineChanged?.()
            }}
          />
          {(runs ?? []).map((run) => (
            <a
              key={run.id}
              href={`#cockpit/${run.id}`}
              title={t('{title} im Cockpit öffnen', { title: run.title })}
              className="flex max-w-[15rem] items-center gap-1.5 rounded-xl border border-cockpit-line px-3.5 py-2 text-[13px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-mint-300"
            >
              <Briefcase className="h-4 w-4 shrink-0" />
              <span className="truncate">{t('Im Prozess')}: {run.client ?? run.title}</span>
            </a>
          ))}
          <a
            href={`mailto:${candidate.email}`}
            className="flex items-center gap-1.5 rounded-xl border border-mint-600 bg-mint-800/40 px-3.5 py-2 text-[13px] font-medium text-mint-300 transition-colors hover:bg-mint-800/70"
          >
            <Mail className="h-4 w-4" /> E-Mail
          </a>
          {p?.xingUrl && (
            <a
              href={p.xingUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-xl border border-cockpit-line px-3.5 py-2 text-[13px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
            >
              Xing
            </a>
          )}
          <CloseButton onClose={onClose} />
        </div>
      </div>

      {/* Body: original CV (left) · parsed record (right) */}
      <div className="grid flex-1 grid-cols-2 overflow-hidden">
        {/* LEFT — the evidence */}
        <div className="flex flex-col border-r border-cockpit-line bg-cockpit-inset">
          <PanelLabel icon={FileText} title={t('Original-CV')}>
            {cvState === 'ready' && cvUrl && (
              <a
                href={cvUrl}
                download={`${candidate.name}.pdf`}
                className="ml-auto flex items-center gap-1 whitespace-nowrap font-mono text-[11px] text-mint-400 hover:underline"
              >
                <Download className="h-3.5 w-3.5" /> Download
              </a>
            )}
          </PanelLabel>
          <div className="flex-1 overflow-hidden p-3">
            {cvState === 'loading' && <Placeholder>{t('CV wird geladen…')}</Placeholder>}
            {cvState === 'missing' && (
              <Placeholder icon={FileWarning}>
                {t('Kein Original-CV hinterlegt.')}
                <span className="mt-1 block text-[12px]">
                  {t('Nur über den CV-Upload importierte Kandidaten haben ein angehängtes Original.')}
                </span>
              </Placeholder>
            )}
            {cvState === 'ready' && cvUrl && (
              <iframe
                title={t('Original-CV')}
                src={`${cvUrl}#toolbar=1&view=FitH`}
                className="h-full w-full rounded-lg border border-cockpit-line bg-white"
              />
            )}
          </div>
        </div>

        {/* RIGHT — the extracted record */}
        <div className="flex flex-col overflow-hidden bg-cockpit-bg">
          <PanelLabel icon={Sparkles} title="Parsed CV">
            <Chip tone="mint" className="whitespace-nowrap">
              {t('verifiziert extrahiert')}
            </Chip>
            {!editing && (
              <div className="ml-auto flex items-center gap-2">
                <Button
                  onClick={() => void startEdit()}
                  className="whitespace-nowrap px-2.5 py-1 text-[12px]"
                  title={t('Felder bearbeiten')}
                >
                  <Pencil className="h-3.5 w-3.5" /> {t('Bearbeiten')}
                </Button>
                <Button
                  onClick={() => setExpanded((e) => !e)}
                  className="whitespace-nowrap px-2.5 py-1 text-[12px]"
                  title={expanded ? t('Kompaktansicht') : t('Vollständiges Profil (Dossier 360)')}
                >
                  {expanded ? (
                    <>
                      <ChevronsLeft className="h-4 w-4" /> {t('Kompakt')}
                    </>
                  ) : (
                    <>
                      Dossier 360 <ChevronsRight className="h-4 w-4" />
                    </>
                  )}
                </Button>
              </div>
            )}
          </PanelLabel>

          <div className="flex-1 overflow-y-auto px-7 py-6">
            {editing ? (
              dtoError ? (
                <Placeholder icon={FileWarning}>
                  {t('Profil konnte nicht geladen werden.')}
                  <button
                    onClick={() => void startEdit(focusField)}
                    className="mt-2 block w-full text-mint-400 hover:underline"
                  >
                    {t('Erneut versuchen')}
                  </button>
                </Placeholder>
              ) : dto ? (
                <DossierEditor
                  dto={dto}
                  focusField={focusField}
                  onCancel={() => setEditing(false)}
                  onSaved={handleSaved}
                />
              ) : (
                <Placeholder>{t('Profil wird geladen…')}</Placeholder>
              )
            ) : (
              <>
                {/* What the Qualifikationsgespräch is supposed to produce,
                    and what of it the record already holds. The editor
                    behind "Erfassen" has always written every one of these
                    fields; nobody could tell which were still empty. */}
                <div className="mb-6 border-b border-cockpit-line pb-5">
                  <QualificationChecklist
                    candidate={candidate}
                    onEdit={(field) => void startEdit(field)}
                  />
                </div>

                {expanded ? (
                  <Profile360 candidate={candidate} p={p} />
                ) : (
                  <dl className="grid grid-cols-2 gap-x-6 gap-y-1">
                    <InfoRow icon={Mail} label={t('E-Mail')}>
                      <a
                        href={`mailto:${candidate.email}`}
                        className="font-mono text-mint-400 hover:underline"
                      >
                        {candidate.email}
                      </a>
                    </InfoRow>
                    <InfoRow icon={Phone} label={t('Telefon')} value={candidate.phone} mono />
                    <InfoRow icon={MapPin} label={t('Standort')} value={address || candidate.location} />
                    <InfoRow
                      icon={Building2}
                      label={t('Branchen')}
                      value={p?.industries.join(' · ')}
                    />
                    <InfoRow
                      icon={Briefcase}
                      label={t('Anstellungsform')}
                      value={employmentFormLabel(p?.employmentForm)}
                    />
                    <InfoRow icon={CalendarClock} label={t('Verfügbarkeit')} value={p?.availability} />
                    <InfoRow icon={CalendarClock} label={t('Kündigungsfrist')} value={p?.noticePeriod} />
                    <InfoRow icon={Wallet} label={t('Gehalt')} value={salary} mono />
                    <InfoRow
                      icon={ShieldCheck}
                      label={t('Arbeitserlaubnis')}
                      value={permitLabel(p?.workPermit)}
                    />
                    <InfoRow
                      icon={Briefcase}
                      label={t('Erfahrung')}
                      value={yearsLabel(candidate, p?.totalYearsExperience)}
                    />
                  </dl>
                )}

                {p?.languages?.length ? (
                  <div className="mt-6">
                    <MiniLabel icon={Languages}>{t('Sprachen')}</MiniLabel>
                    <div className="flex flex-wrap gap-1.5">
                      {p.languages.map((l) => (
                        <Chip key={l}>{l}</Chip>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="mt-6">
                  <MiniLabel>{t('Skills')}</MiniLabel>
                  <div className="flex flex-wrap gap-1.5">
                    {skills.length ? (
                      skills.map((s) => (
                        <Chip key={s} tone="mint">
                          {s}
                        </Chip>
                      ))
                    ) : (
                      <Empty>{t('Keine Skills erfasst')}</Empty>
                    )}
                  </div>
                </div>

                <hr className="my-7 border-cockpit-line" />

                {/* The recruiter's summary of the conversation outranks the
                    synthesised one — a person wrote it, having spoken to them. */}
                <CvSection icon={Sparkles} title={t('Profil')}>
                  <p className="text-[14px] leading-relaxed text-cockpit-dim">
                    {p?.profileSummary?.trim() ||
                      p?.motivation?.trim() ||
                      candidate.aiSummary}
                  </p>
                </CvSection>

                {(p?.focusAreas?.length ?? 0) > 0 && (
                  <CvSection icon={Sparkles} title={t('Schwerpunkte')}>
                    <div className="flex flex-wrap gap-1.5">
                      {p?.focusAreas.map((area) => (
                        <Chip key={area}>{area}</Chip>
                      ))}
                    </div>
                  </CvSection>
                )}

                {/* Prose, and deliberately next to the Skills chips rather
                    than merged into them: the chips are what the hard
                    filters read, this is what the person actually said. */}
                {p?.technicalProfile?.trim() && (
                  <CvSection icon={Sparkles} title={t('Technisches Know-how')}>
                    <p className="text-[14px] leading-relaxed text-cockpit-dim">
                      {p.technicalProfile}
                    </p>
                  </CvSection>
                )}

                {p?.profileSummary?.trim() && p?.motivation?.trim() && (
                  <CvSection icon={Sparkles} title={t('Wechselmotivation')}>
                    <p className="text-[14px] leading-relaxed text-cockpit-dim">
                      {p.motivation}
                    </p>
                  </CvSection>
                )}

                {p?.otherNotes?.trim() && (
                  <CvSection icon={Sparkles} title={t('Weitere relevante Punkte')}>
                    <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-cockpit-dim">
                      {p.otherNotes}
                    </p>
                  </CvSection>
                )}

                <CvSection icon={Briefcase} title={t('Berufserfahrung')}>
                  {roles ? (
                    <ol className="relative space-y-5 border-l border-cockpit-line pl-5">
                      {roles.map((r, i) => (
                        <li key={i} className="relative">
                          <span className="absolute -left-[23px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-cockpit-bg bg-mint-500" />
                          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                            <span className="text-[14px] font-semibold text-cockpit-text">
                              {r.title || t('Rolle')}
                            </span>
                            {r.period && (
                              <span className="font-mono text-[12px] text-cockpit-faint">
                                {r.period}
                              </span>
                            )}
                          </div>
                          {(r.company || r.location) && (
                            <div className="text-[13px] text-cockpit-dim">
                              {[r.company, r.location].filter(Boolean).join(' · ')}
                            </div>
                          )}
                          {r.highlights.length > 0 && (
                            <ul className="mt-1.5 space-y-1">
                              {r.highlights.map((h, j) => (
                                <li
                                  key={j}
                                  className="flex gap-2 text-[13px] leading-relaxed text-cockpit-dim"
                                >
                                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-cockpit-faint" />
                                  <span>{h}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <Empty>{t('Keine Berufserfahrung erfasst')}</Empty>
                  )}
                </CvSection>

                <CvSection icon={GraduationCap} title={t('Ausbildung')}>
                  {education.length ? (
                    <ul className="space-y-3">
                      {education.map((e, i) => (
                        <li key={i}>
                          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                            <span className="text-[14px] font-semibold text-cockpit-text">
                              {e.degree}
                            </span>
                            {e.period && (
                              <span className="font-mono text-[12px] text-cockpit-faint">
                                {e.period}
                              </span>
                            )}
                          </div>
                          {(e.institution || e.location) && (
                            <div className="text-[13px] text-cockpit-dim">
                              {[e.institution, e.location].filter(Boolean).join(' · ')}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <Empty>{t('Keine Ausbildung erfasst')}</Empty>
                  )}
                </CvSection>

                <CvSection icon={Paperclip} title={t('Dateien')}>
                  <AttachmentsPanel
                    candidateId={candidate.id}
                    onCandidateChanged={handleSaved}
                  />
                </CvSection>

                <div className="mt-7">
                  <HistoryTrail entityType="candidate" entityId={candidate.id} />
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </Drawer>
  )
}

/* ---------- presentational helpers ---------- */

/**
 * Header strip above each half of the drawer. `title` never wraps; trailing
 * `children` (chip, action buttons) wrap onto their own line when the panel is
 * too narrow for them — which it is at the compact width.
 */
function PanelLabel({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-2 border-b border-cockpit-line bg-cockpit-surface px-7 py-3">
      <span className="flex shrink-0 items-center gap-2 whitespace-nowrap font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-dim">
        <Icon className="h-4 w-4" />
        {title}
      </span>
      {children}
    </div>
  )
}

function MiniLabel({
  icon: Icon,
  children,
}: {
  icon?: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  return (
    <h4 className="mb-2 flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
      {Icon && <Icon className="h-3.5 w-3.5" />} {children}
    </h4>
  )
}

function Placeholder({
  icon: Icon,
  children,
}: {
  icon?: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-lg border border-dashed border-cockpit-line text-center text-[13px] text-cockpit-dim">
      {Icon && <Icon className="mb-2 h-8 w-8 text-cockpit-faint" />}
      <div className="max-w-[240px] px-4">{children}</div>
    </div>
  )
}

function InfoRow({
  icon: Icon,
  label,
  value,
  children,
  mono,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value?: string | null
  children?: React.ReactNode
  mono?: boolean
}) {
  if (!children && !value) return null
  return (
    <div className="flex items-start gap-2.5 py-1.5">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-cockpit-faint" />
      <div className="min-w-0 flex-1">
        <dt className="font-mono text-[11px] uppercase tracking-[0.08em] text-cockpit-faint">
          {label}
        </dt>
        <dd
          className={cn(
            'truncate text-[14px] font-medium text-cockpit-text',
            mono && 'font-mono text-[13px]',
          )}
        >
          {children ?? value}
        </dd>
      </div>
    </div>
  )
}

function CvSection({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="mt-7 first:mt-0">
      <h2 className="mb-3 flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.12em] text-mint-400">
        <Icon className="h-4 w-4" /> {title}
      </h2>
      {children}
    </section>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-[13px] italic text-cockpit-faint">{children}</p>
}

/* ---------- full 360 profile (all aiFind fields, grouped) ---------- */

type FieldT = [label: string, value: string | undefined, href?: string]

function Profile360({ candidate, p }: { candidate: Candidate; p?: CandidateProfile }) {
  const money = (n?: number | null) => (n != null ? fmtMoney(n, p?.salaryCurrency) : undefined)
  const val = (s: string | undefined) => (s && s !== '—' ? s : undefined)

  const sections: {
    title: string
    icon: React.ComponentType<{ className?: string }>
    fields: FieldT[]
  }[] = [
    {
      title: t('Persönliche Daten'),
      icon: User,
      fields: [
        [t('Vollständiger Name'), candidate.name],
        [t('Vorname'), p?.firstName],
        [t('Nachname'), p?.lastName],
        [t('Geschlecht'), p?.sex],
        [t('Namenszusatz'), p?.namePrefix],
        [t('Geburtsdatum'), p?.dateOfBirth],
      ],
    },
    {
      title: t('Kontakt'),
      icon: Mail,
      fields: [
        [t('E-Mail'), candidate.email, `mailto:${candidate.email}`],
        [t('Telefon'), val(candidate.phone)],
        ['LinkedIn', p?.linkedinUrl, p?.linkedinUrl],
        ['Xing', p?.xingUrl, p?.xingUrl],
        [t('Straße'), p?.street],
        [t('PLZ'), p?.postalCode],
        [t('Stadt'), p?.city],
        [t('Land'), p?.country],
        [t('Standort'), val(candidate.location)],
      ],
    },
    {
      title: t('Karriere'),
      icon: Briefcase,
      fields: [
        [t('Job-Titel'), val(candidate.currentTitle)],
        [t('Aktuelles Unternehmen'), val(candidate.currentCompany)],
        [t('Branchen'), p?.industries.join(' · ') || undefined],
        [t('Anstellungsform'), employmentFormLabel(p?.employmentForm)],
        // What the source called it, kept visible as provenance for the form.
        [t('Anstellungsart (Quelle)'), p?.employmentType],
        [t('Umzugsbereit'), relocate(p?.willingToRelocate)],
        [t('Kündigungsfrist'), p?.noticePeriod],
        [t('Verfügbarkeit'), p?.availability],
        [t('Berufserfahrung'), yearsLabel(candidate, p?.totalYearsExperience)],
        [t('Aktuelles Gehalt'), money(p?.currentSalary)],
        [t('Mindestgehalt'), money(p?.salaryMinimum)],
        [t('Wunschgehalt'), money(p?.salaryExpectation)],
        [t('Währung'), p?.salaryCurrency],
        [t('Arbeitserlaubnis'), permitLabel(p?.workPermit)],
        [t('Quelle'), p?.source],
      ],
    },
  ]

  // Only after the Qualifikationsgespräch is there anything here; an empty
  // block of "—" would suggest the conversation happened and yielded nothing.
  const qualification: FieldT[] = [
    [t('Verfügbarkeit für Interviews'), p?.interviewAvailability],
    [t('Andere Prozesse bei'), p?.otherProcessCompanies.join(' · ') || undefined],
    [t('Notiz zu anderen Prozessen'), p?.otherProcesses],
  ]
  if (qualification.some(([, value]) => value)) {
    sections.push({
      title: t('Nach dem Qualifikationsgespräch'),
      icon: CalendarClock,
      fields: qualification,
    })
  }

  return (
    <div className="space-y-6">
      {sections.map((s) => (
        <section key={s.title}>
          <MiniLabel icon={s.icon}>{s.title}</MiniLabel>
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
            {s.fields.map(([label, value, href]) => (
              <Field key={label} label={label} value={value} href={href} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

const EMPLOYMENT_FORM_LABELS: Record<string, string> = {
  festanstellung: t('Festanstellung'),
  freelance: 'Freelance',
  beides: t('Beides'),
}

/** Unset means nobody established it — shown as a gap, not as a guess. */
function employmentFormLabel(form?: string): string | undefined {
  return form ? (EMPLOYMENT_FORM_LABELS[form] ?? form) : undefined
}

function Field({ label, value, href }: { label: string; value?: string; href?: string }) {
  return (
    <div className="min-w-0 border-b border-cockpit-line pb-1.5">
      <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-cockpit-faint">
        {label}
      </div>
      {value ? (
        href ? (
          <a
            href={href}
            target={href.startsWith('http') ? '_blank' : undefined}
            rel="noopener noreferrer"
            className="block truncate text-[14px] font-medium text-mint-400 hover:underline"
          >
            {value}
          </a>
        ) : (
          <div className="truncate text-[14px] font-medium text-cockpit-text">{value}</div>
        )
      ) : (
        <div className="font-mono text-[14px] text-cockpit-faint">—</div>
      )}
    </div>
  )
}

const relocate = (v?: string) =>
  v == null || v === ''
    ? undefined
    : /^(ja|yes|true)$/i.test(v)
      ? t('Ja')
      : /^(nein|no|false)$/i.test(v)
        ? t('Nein')
        : v

/* ---------- formatting ---------- */

function fmtMoney(amount: number, currency = 'EUR'): string {
  try {
    return new Intl.NumberFormat(locale(), {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(amount)
  } catch {
    return `${amount} ${currency}`
  }
}

const PERMIT_LABELS: Record<string, string> = {
  citizen: t('Staatsbürger'),
  permanent: t('Unbefristet'),
  work_visa: t('Arbeitsvisum'),
  needs_sponsorship: t('Sponsoring nötig'),
  unknown: t('Unbekannt'),
}
const permitLabel = (v?: string) => (v ? (PERMIT_LABELS[v] ?? v) : undefined)

function yearsLabel(candidate: Candidate, total?: string): string | undefined {
  if (total && total.trim() && total.trim() !== '0') return t('{n} Jahre', { n: total })
  return candidate.stats.total !== '—' ? candidate.stats.total : undefined
}
