import { useEffect } from 'react'
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
} from 'lucide-react'
import type { Candidate } from '@/data/types'
import { Avatar } from '@/components/ui/Avatar'
import { SkillBadge } from '@/components/ui/SkillBadge'
import { LinkedInMark } from '@/components/ui/LinkedInMark'

/** Full candidate dossier: key information summarised on the left, the CV
 *  (a résumé rendered from the verified structured record) on the right. */
export function CandidateDossier({ candidate, onClose }: { candidate: Candidate; onClose: () => void }) {
  // Close on Escape; lock body scroll while open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

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
      {/* Backdrop */}
      <button
        aria-label="Schließen"
        onClick={onClose}
        className="absolute inset-0 bg-ink/40 backdrop-blur-[2px]"
      />

      {/* Panel */}
      <div className="relative flex h-full w-full max-w-[1080px] flex-col bg-page shadow-2xl">
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
            <button
              onClick={onClose}
              className="rounded-xl border border-line p-2 text-ink-muted hover:bg-slate-50"
              aria-label="Schließen"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Body: key info (left) · CV (right) */}
        <div className="grid flex-1 grid-cols-[360px_1fr] overflow-hidden">
          {/* LEFT — Schlüsselinformationen */}
          <aside className="overflow-y-auto border-r border-line bg-white px-7 py-6">
            <SectionLabel>Schlüsselinformationen</SectionLabel>

            <dl className="space-y-1">
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
              <InfoRow icon={FileText} label="Quelle" value={p?.source} />
            </dl>

            {p?.languages?.length ? (
              <div className="mt-6">
                <SectionLabel>
                  <Languages className="h-3.5 w-3.5" /> Sprachen
                </SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {p.languages.map((l) => (
                    <span
                      key={l}
                      className="rounded-md bg-slate-100 px-2 py-0.5 text-[12px] font-medium text-ink-soft"
                    >
                      {l}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="mt-6">
              <SectionLabel>Skills</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {skills.length ? (
                  skills.map((s) => <SkillBadge key={s} label={s} tone="mint" />)
                ) : (
                  <Empty>Keine Skills erfasst</Empty>
                )}
              </div>
            </div>
          </aside>

          {/* RIGHT — Lebenslauf (CV) */}
          <div className="overflow-y-auto px-8 py-7">
            <div className="mx-auto max-w-[680px] space-y-6">
              {/* CV document header */}
              <div className="flex items-center gap-2 text-[13px] font-medium uppercase tracking-wide text-ink-muted">
                <FileText className="h-4 w-4" /> Lebenslauf
              </div>

              <div className="rounded-2xl border border-line bg-white p-8 shadow-sm">
                {/* CV title block */}
                <div className="border-b border-line pb-5">
                  <h1 className="text-[26px] font-bold leading-tight text-ink">{candidate.name}</h1>
                  <p className="mt-1 text-[15px] text-ink-soft">
                    {candidate.currentTitle}
                    {candidate.currentCompany !== '—' && ` · ${candidate.currentCompany}`}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-muted">
                    <span className="inline-flex items-center gap-1">
                      <Mail className="h-3.5 w-3.5" /> {candidate.email}
                    </span>
                    {candidate.phone !== '—' && (
                      <span className="inline-flex items-center gap-1">
                        <Phone className="h-3.5 w-3.5" /> {candidate.phone}
                      </span>
                    )}
                    {(address || candidate.location !== '—') && (
                      <span className="inline-flex items-center gap-1">
                        <MapPin className="h-3.5 w-3.5" /> {address || candidate.location}
                      </span>
                    )}
                  </div>
                </div>

                {/* Profil / KI-Zusammenfassung */}
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
                            <span className="text-[14px] font-semibold text-ink">
                              {r.title || 'Rolle'}
                            </span>
                            {r.period && (
                              <span className="text-[12px] font-medium text-ink-muted">
                                {r.period}
                              </span>
                            )}
                          </div>
                          {(r.company || r.location) && (
                            <div className="text-[13px] text-ink-soft">
                              {[r.company, r.location].filter(Boolean).join(' · ')}
                            </div>
                          )}
                          {r.highlights.length > 0 && (
                            <ul className="mt-1.5 space-y-1">
                              {r.highlights.map((h, j) => (
                                <li
                                  key={j}
                                  className="flex gap-2 text-[13px] leading-relaxed text-ink-soft"
                                >
                                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-ink-faint" />
                                  <span>{h}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </li>
                      ))}
                    </ol>
                  ) : candidate.experience.length ? (
                    <ol className="relative space-y-4 border-l border-line pl-5">
                      {candidate.experience.map((e, i) => (
                        <li key={i} className="relative">
                          <span className="absolute -left-[23px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-brand-500" />
                          <div className="text-[14px] font-semibold text-ink">{e.title}</div>
                          <div className="text-[13px] text-ink-muted">
                            {[e.company, e.period].filter(Boolean).join(' · ')}
                          </div>
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
                            {e.period && (
                              <span className="text-[12px] font-medium text-ink-muted">
                                {e.period}
                              </span>
                            )}
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
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ---------- small presentational helpers ---------- */

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-3 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
      {children}
    </h3>
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
    <div className="flex items-start gap-3 py-1.5">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
      <div className="min-w-0 flex-1">
        <dt className="text-[12px] text-ink-muted">{label}</dt>
        <dd className="truncate text-[14px] font-medium text-ink">{children ?? value}</dd>
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
    <section className="mt-6">
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

/* ---------- formatting ---------- */

function fmtMoney(amount: number, currency = 'EUR'): string {
  try {
    return new Intl.NumberFormat('de-DE', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(amount)
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
