import { useEffect, useState } from 'react'
import {
  X,
  Mail,
  Phone,
  MapPin,
  ShieldCheck,
  Briefcase,
  GraduationCap,
  Languages,
  CalendarClock,
  Wallet,
  Building2,
  FileText,
  Sparkles,
  Download,
  FileWarning,
  ChevronsRight,
  ChevronsLeft,
  User,
  Pencil,
} from 'lucide-react'
import type { Candidate, CandidateProfile } from '@/data/types'
import type { CandidateDTO } from '@/api/types'
import { api } from '@/api/client'
import { Avatar } from '@/components/ui/Avatar'
import { SkillBadge } from '@/components/ui/SkillBadge'
import { LinkedInMark } from '@/components/ui/LinkedInMark'
import { DossierEditor } from './DossierEditor'

/** Full candidate dossier: the ORIGINAL uploaded CV on the left (the evidence),
 *  the PARSED CV — the structured record extracted from it — on the right. */
export function CandidateDossier({
  candidate,
  onClose,
  onSaved,
}: {
  candidate: Candidate
  onClose: () => void
  /** Called after a manual edit is persisted, with the fresh record. */
  onSaved?: (updated: CandidateDTO) => void
}) {
  const [cvUrl, setCvUrl] = useState<string | null>(null)
  const [cvState, setCvState] = useState<'loading' | 'ready' | 'missing'>('loading')
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [dto, setDto] = useState<CandidateDTO | null>(null)
  const [dtoError, setDtoError] = useState(false)

  async function startEdit() {
    setExpanded(true)
    setEditing(true)
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

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

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
    <div className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Schließen" onClick={onClose} className="absolute inset-0 bg-ink/40 backdrop-blur-[2px]" />

      <div
        className={`relative flex h-full w-full flex-col bg-page shadow-2xl transition-[max-width] duration-300 ${
          expanded ? 'max-w-[1600px]' : 'max-w-[1180px]'
        }`}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-line bg-white px-8 py-5">
          <div className="flex items-center gap-4">
            <Avatar initials={candidate.initials} tone={candidate.avatar} size="lg" />
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-[20px] font-semibold leading-tight text-ink">{candidate.name}</h2>
                {candidate.linkedinUrl && <LinkedInMark href={candidate.linkedinUrl} />}
              </div>
              <p className="mt-0.5 text-[14px] text-ink-muted">
                {candidate.currentTitle}
                {candidate.currentCompany !== '—' && ` · ${candidate.currentCompany}`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <a
              href={`mailto:${candidate.email}`}
              className="flex items-center gap-1.5 rounded-xl bg-ink px-3.5 py-2 text-[13px] font-semibold text-white hover:bg-ink-soft"
            >
              <Mail className="h-4 w-4" /> E-Mail
            </a>
            {p?.xingUrl && (
              <a
                href={p.xingUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-xl border border-line px-3.5 py-2 text-[13px] font-medium text-ink-soft hover:bg-slate-50"
              >
                Xing
              </a>
            )}
            <button onClick={onClose} className="rounded-xl border border-line p-2 text-ink-muted hover:bg-slate-50" aria-label="Schließen">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Body: original CV (left) · parsed CV (right) */}
        <div className="grid flex-1 grid-cols-2 overflow-hidden">
          {/* LEFT — Original CV (attachment) */}
          <div className="flex flex-col border-r border-line bg-slate-100">
            <PanelLabel icon={FileText}>
              Original-CV
              {cvState === 'ready' && cvUrl && (
                <a
                  href={cvUrl}
                  download={`${candidate.name}.pdf`}
                  className="ml-auto flex items-center gap-1 text-[12px] font-medium text-brand-600 hover:underline"
                >
                  <Download className="h-3.5 w-3.5" /> Download
                </a>
              )}
            </PanelLabel>
            <div className="flex-1 overflow-hidden p-3">
              {cvState === 'loading' && (
                <Placeholder>CV wird geladen…</Placeholder>
              )}
              {cvState === 'missing' && (
                <Placeholder icon={FileWarning}>
                  Kein Original-CV hinterlegt.
                  <span className="mt-1 block text-[12px]">
                    Nur über den CV-Upload importierte Kandidaten haben ein angehängtes Original.
                  </span>
                </Placeholder>
              )}
              {cvState === 'ready' && cvUrl && (
                <iframe
                  title="Original-CV"
                  src={`${cvUrl}#toolbar=1&view=FitH`}
                  className="h-full w-full rounded-lg border border-line bg-white"
                />
              )}
            </div>
          </div>

          {/* RIGHT — Parsed CV (the structured record) */}
          <div className="flex flex-col overflow-hidden bg-white">
            <PanelLabel icon={Sparkles}>
              Parsed CV
              <span className="ml-2 rounded-md bg-brand-50 px-1.5 py-0.5 text-[11px] font-medium text-brand-700">
                verifiziert extrahiert
              </span>
              {!editing && (
                <div className="ml-auto flex items-center gap-2">
                  <button
                    onClick={startEdit}
                    className="flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-[12px] font-medium normal-case tracking-normal text-ink-soft hover:bg-slate-50"
                    title="Felder bearbeiten"
                  >
                    <Pencil className="h-3.5 w-3.5" /> Bearbeiten
                  </button>
                  <button
                    onClick={() => setExpanded((e) => !e)}
                    className="flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-[12px] font-medium normal-case tracking-normal text-ink-soft hover:bg-slate-50"
                    title={expanded ? 'Kompaktansicht' : 'Vollständiges Profil (Dossier 360)'}
                  >
                    {expanded ? (
                      <>
                        <ChevronsLeft className="h-4 w-4" /> Kompakt
                      </>
                    ) : (
                      <>
                        Dossier 360 <ChevronsRight className="h-4 w-4" />
                      </>
                    )}
                  </button>
                </div>
              )}
            </PanelLabel>
            <div className="flex-1 overflow-y-auto px-7 py-6">
              {editing ? (
                dtoError ? (
                  <Placeholder icon={FileWarning}>
                    Profil konnte nicht geladen werden.
                    <button onClick={startEdit} className="mt-2 block text-brand-600 hover:underline">
                      Erneut versuchen
                    </button>
                  </Placeholder>
                ) : dto ? (
                  <DossierEditor dto={dto} onCancel={() => setEditing(false)} onSaved={handleSaved} />
                ) : (
                  <Placeholder>Profil wird geladen…</Placeholder>
                )
              ) : (
                <>
              {/* Key facts — compact (populated only) or the full 360 field set */}
              {expanded ? (
                <Profile360 candidate={candidate} p={p} />
              ) : (
                <dl className="grid grid-cols-2 gap-x-5 gap-y-1">
                  <InfoRow icon={Mail} label="E-Mail">
                    <a href={`mailto:${candidate.email}`} className="text-brand-600 hover:underline">
                      {candidate.email}
                    </a>
                  </InfoRow>
                  <InfoRow icon={Phone} label="Telefon" value={candidate.phone} />
                  <InfoRow icon={MapPin} label="Standort" value={address || candidate.location} />
                  <InfoRow icon={Building2} label="Branche" value={p?.industry} />
                  <InfoRow icon={Briefcase} label="Anstellungsart" value={p?.employmentType} />
                  <InfoRow icon={CalendarClock} label="Verfügbarkeit" value={p?.availability} />
                  <InfoRow icon={CalendarClock} label="Kündigungsfrist" value={p?.noticePeriod} />
                  <InfoRow icon={Wallet} label="Gehalt" value={salary} />
                  <InfoRow icon={ShieldCheck} label="Arbeitserlaubnis" value={permitLabel(p?.workPermit)} />
                  <InfoRow icon={Briefcase} label="Erfahrung" value={yearsLabel(candidate, p?.totalYearsExperience)} />
                </dl>
              )}

              {p?.languages?.length ? (
                <div className="mt-5">
                  <MiniLabel icon={Languages}>Sprachen</MiniLabel>
                  <div className="flex flex-wrap gap-1.5">
                    {p.languages.map((l) => (
                      <span key={l} className="rounded-md bg-slate-100 px-2 py-0.5 text-[12px] font-medium text-ink-soft">
                        {l}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="mt-5">
                <MiniLabel>Skills</MiniLabel>
                <div className="flex flex-wrap gap-1.5">
                  {skills.length ? (
                    skills.map((s) => <SkillBadge key={s} label={s} tone="mint" />)
                  ) : (
                    <Empty>Keine Skills erfasst</Empty>
                  )}
                </div>
              </div>

              <hr className="my-6 border-line" />

              {/* Profil */}
              <CvSection icon={Sparkles} title="Profil">
                <p className="text-[14px] leading-relaxed text-ink-soft">
                  {p?.motivation?.trim() || candidate.aiSummary}
                </p>
              </CvSection>

              {/* Berufserfahrung */}
              <CvSection icon={Briefcase} title="Berufserfahrung">
                {roles ? (
                  <ol className="relative space-y-5 border-l border-line pl-5">
                    {roles.map((r, i) => (
                      <li key={i} className="relative">
                        <span className="absolute -left-[23px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-brand-500" />
                        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                          <span className="text-[14px] font-semibold text-ink">{r.title || 'Rolle'}</span>
                          {r.period && <span className="text-[12px] font-medium text-ink-muted">{r.period}</span>}
                        </div>
                        {(r.company || r.location) && (
                          <div className="text-[13px] text-ink-soft">
                            {[r.company, r.location].filter(Boolean).join(' · ')}
                          </div>
                        )}
                        {r.highlights.length > 0 && (
                          <ul className="mt-1.5 space-y-1">
                            {r.highlights.map((h, j) => (
                              <li key={j} className="flex gap-2 text-[13px] leading-relaxed text-ink-soft">
                                <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-ink-faint" />
                                <span>{h}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty>Keine Berufserfahrung erfasst</Empty>
                )}
              </CvSection>

              {/* Ausbildung */}
              <CvSection icon={GraduationCap} title="Ausbildung">
                {education.length ? (
                  <ul className="space-y-3">
                    {education.map((e, i) => (
                      <li key={i}>
                        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                          <span className="text-[14px] font-semibold text-ink">{e.degree}</span>
                          {e.period && <span className="text-[12px] font-medium text-ink-muted">{e.period}</span>}
                        </div>
                        {(e.institution || e.location) && (
                          <div className="text-[13px] text-ink-soft">
                            {[e.institution, e.location].filter(Boolean).join(' · ')}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Empty>Keine Ausbildung erfasst</Empty>
                )}
              </CvSection>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ---------- presentational helpers ---------- */

function PanelLabel({ icon: Icon, children }: { icon: React.ComponentType<{ className?: string }>; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 border-b border-line bg-white/60 px-7 py-3 text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
      <Icon className="h-4 w-4" /> {children}
    </div>
  )
}

function MiniLabel({ icon: Icon, children }: { icon?: React.ComponentType<{ className?: string }>; children: React.ReactNode }) {
  return (
    <h4 className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
      {Icon && <Icon className="h-3.5 w-3.5" />} {children}
    </h4>
  )
}

function Placeholder({ icon: Icon, children }: { icon?: React.ComponentType<{ className?: string }>; children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-lg border border-dashed border-line bg-white text-center text-[13px] text-ink-muted">
      {Icon && <Icon className="mb-2 h-8 w-8 text-ink-faint" />}
      <div className="max-w-[240px] px-4">{children}</div>
    </div>
  )
}

function InfoRow({
  icon: Icon,
  label,
  value,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value?: string | null
  children?: React.ReactNode
}) {
  if (!children && !value) return null
  return (
    <div className="flex items-start gap-2.5 py-1.5">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
      <div className="min-w-0 flex-1">
        <dt className="text-[12px] text-ink-muted">{label}</dt>
        <dd className="truncate text-[14px] font-medium text-ink">{children ?? value}</dd>
      </div>
    </div>
  )
}

function CvSection({ icon: Icon, title, children }: { icon: React.ComponentType<{ className?: string }>; title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 first:mt-0">
      <h2 className="mb-3 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wide text-brand-700">
        <Icon className="h-4 w-4" /> {title}
      </h2>
      {children}
    </section>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-[13px] italic text-ink-faint">{children}</p>
}

/* ---------- full 360 profile (all aiFind fields, grouped) ---------- */

type FieldT = [label: string, value: string | undefined, href?: string]

function Profile360({ candidate, p }: { candidate: Candidate; p?: CandidateProfile }) {
  const money = (n?: number | null) => (n != null ? fmtMoney(n, p?.salaryCurrency) : undefined)
  const val = (s: string | undefined) => (s && s !== '—' ? s : undefined)

  const sections: { title: string; icon: React.ComponentType<{ className?: string }>; fields: FieldT[] }[] = [
    {
      title: 'Persönliche Daten',
      icon: User,
      fields: [
        ['Vollständiger Name', candidate.name],
        ['Vorname', p?.firstName],
        ['Nachname', p?.lastName],
        ['Geschlecht', p?.sex],
        ['Namenszusatz', p?.namePrefix],
        ['Geburtsdatum', p?.dateOfBirth],
      ],
    },
    {
      title: 'Kontakt',
      icon: Mail,
      fields: [
        ['E-Mail', candidate.email, `mailto:${candidate.email}`],
        ['Telefon', val(candidate.phone)],
        ['LinkedIn', p?.linkedinUrl, p?.linkedinUrl],
        ['Xing', p?.xingUrl, p?.xingUrl],
        ['Straße', p?.street],
        ['PLZ', p?.postalCode],
        ['Stadt', p?.city],
        ['Land', p?.country],
        ['Standort', val(candidate.location)],
      ],
    },
    {
      title: 'Karriere',
      icon: Briefcase,
      fields: [
        ['Job-Titel', val(candidate.currentTitle)],
        ['Aktuelles Unternehmen', val(candidate.currentCompany)],
        ['Branche', p?.industry],
        ['Anstellungsart', p?.employmentType],
        ['Umzugsbereit', relocate(p?.willingToRelocate)],
        ['Kündigungsfrist', p?.noticePeriod],
        ['Verfügbarkeit', p?.availability],
        ['Berufserfahrung', yearsLabel(candidate, p?.totalYearsExperience)],
        ['Aktuelles Gehalt', money(p?.currentSalary)],
        ['Wunschgehalt', money(p?.salaryExpectation)],
        ['Währung', p?.salaryCurrency],
        ['Arbeitserlaubnis', permitLabel(p?.workPermit)],
        ['Quelle', p?.source],
      ],
    },
  ]

  return (
    <div className="space-y-5">
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

function Field({ label, value, href }: { label: string; value?: string; href?: string }) {
  return (
    <div className="min-w-0 border-b border-line/70 pb-1.5">
      <div className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</div>
      {value ? (
        href ? (
          <a
            href={href}
            target={href.startsWith('http') ? '_blank' : undefined}
            rel="noopener noreferrer"
            className="block truncate text-[14px] font-medium text-brand-600 hover:underline"
          >
            {value}
          </a>
        ) : (
          <div className="truncate text-[14px] font-medium text-ink">{value}</div>
        )
      ) : (
        <div className="text-[14px] text-ink-faint">—</div>
      )}
    </div>
  )
}

const relocate = (v?: string) =>
  v == null || v === '' ? undefined : /^(ja|yes|true)$/i.test(v) ? 'Ja' : /^(nein|no|false)$/i.test(v) ? 'Nein' : v

/* ---------- formatting ---------- */

function fmtMoney(amount: number, currency = 'EUR'): string {
  try {
    return new Intl.NumberFormat('de-DE', { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount)
  } catch {
    return `${amount} ${currency}`
  }
}

const PERMIT_LABELS: Record<string, string> = {
  citizen: 'Staatsbürger',
  permanent: 'Unbefristet',
  work_visa: 'Arbeitsvisum',
  needs_sponsorship: 'Sponsoring nötig',
  unknown: 'Unbekannt',
}
const permitLabel = (v?: string) => (v ? (PERMIT_LABELS[v] ?? v) : undefined)

function yearsLabel(candidate: Candidate, total?: string): string | undefined {
  if (total && total.trim() && total.trim() !== '0') return `${total} Jahre`
  return candidate.stats.total !== '—' ? candidate.stats.total : undefined
}
