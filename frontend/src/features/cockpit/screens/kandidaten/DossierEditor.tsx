import { useEffect, useRef, useState } from 'react'
import { Trash2, Save, Ban, AlertCircle } from 'lucide-react'
import { api } from '@/api/client'
import type { CandidateDTO, CandidateUpdatePayload, EducationDTO, WorkRoleDTO } from '@/api/types'
import {
  AddButton,
  Button,
  GroupLabel,
  MiniInput,
  SelectInput,
  TagInput,
  TextArea,
  TextInput,
} from '../../ui/forms'

/** Editable draft — snake_case so it maps 1:1 onto the PATCH payload. Numbers are
 *  held as strings while typing and parsed on save. */
interface Draft {
  full_name: string
  email: string
  phone: string
  current_title: string
  current_company: string
  location: string
  first_name: string
  last_name: string
  sex: string
  name_prefix: string
  date_of_birth: string
  street: string
  postal_code: string
  city: string
  country: string
  linkedin_url: string
  xing_url: string
  industries: string[]
  employment_type: string
  employment_form: string
  willing_to_relocate: string
  notice_period: string
  availability: string
  total_years_experience: string
  current_salary: string
  salary_expectation: string
  salary_minimum: string
  salary_currency: string
  profile_summary: string
  interview_availability: string
  other_processes: string
  other_process_companies: string[]
  work_permit: string
  source: string
  motivation: string
  skills: string[]
  languages: string[]
  work_history: WorkRoleDTO[]
  education: EducationDTO[]
}

const WORK_PERMITS: { value: string; label: string }[] = [
  { value: 'unknown', label: 'Unbekannt' },
  { value: 'citizen', label: 'Staatsbürger' },
  { value: 'permanent', label: 'Unbefristet' },
  { value: 'work_visa', label: 'Arbeitsvisum' },
  { value: 'requires_sponsorship', label: 'Sponsoring nötig' },
  { value: 'none', label: 'Keine' },
]

const EMPLOYMENT_FORMS = [
  { value: '', label: '—' },
  { value: 'festanstellung', label: 'Festanstellung' },
  { value: 'freelance', label: 'Freelance' },
  { value: 'beides', label: 'Beides' },
]

const RELOCATE = [
  { value: '', label: '—' },
  { value: 'Ja', label: 'Ja' },
  { value: 'Nein', label: 'Nein' },
]

const s = (v?: string | null) => v ?? ''
const numStr = (v?: number | null) => (v == null ? '' : String(v))

function normalizeEducation(e: CandidateDTO['education']): EducationDTO[] {
  if (!e?.length) return []
  if (typeof e[0] === 'string') return (e as string[]).map((degree) => ({ degree }))
  return (e as EducationDTO[]).map((x) => ({ ...x }))
}

function seed(dto: CandidateDTO): Draft {
  return {
    full_name: dto.full_name ?? '',
    email: s(dto.email),
    phone: s(dto.phone),
    current_title: s(dto.current_title),
    current_company: s(dto.current_company),
    location: s(dto.location),
    first_name: s(dto.first_name),
    last_name: s(dto.last_name),
    sex: s(dto.sex),
    name_prefix: s(dto.name_prefix),
    date_of_birth: s(dto.date_of_birth),
    street: s(dto.street),
    postal_code: s(dto.postal_code),
    city: s(dto.city),
    country: s(dto.country),
    linkedin_url: s(dto.linkedin_url),
    xing_url: s(dto.xing_url),
    industries: [...(dto.industries ?? [])],
    employment_type: s(dto.employment_type),
    employment_form: s(dto.employment_form),
    willing_to_relocate: s(dto.willing_to_relocate),
    notice_period: s(dto.notice_period),
    availability: s(dto.availability),
    total_years_experience: s(dto.total_years_experience),
    current_salary: numStr(dto.current_salary),
    salary_expectation: numStr(dto.salary_expectation),
    salary_minimum: numStr(dto.salary_minimum),
    salary_currency: dto.salary_currency || 'EUR',
    profile_summary: s(dto.profile_summary),
    interview_availability: s(dto.interview_availability),
    other_processes: s(dto.other_processes),
    other_process_companies: [...(dto.other_process_companies ?? [])],
    work_permit: dto.work_permit || 'unknown',
    source: s(dto.source),
    motivation: s(dto.motivation),
    skills: [...(dto.skills ?? [])],
    languages: [...(dto.languages ?? [])],
    work_history: (dto.work_history ?? []).map((w) => ({ ...w })),
    education: normalizeEducation(dto.education),
  }
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function toNum(v: string): number | null {
  const t = v.trim()
  if (t === '') return null
  const n = Number(t)
  return Number.isFinite(n) ? Math.round(n) : null
}

function validate(d: Draft): string | null {
  if (!d.full_name.trim()) return 'Vollständiger Name darf nicht leer sein.'
  if (d.email.trim() && !EMAIL_RE.test(d.email.trim())) return 'E-Mail-Adresse ist ungültig.'
  for (const [label, v] of [
    ['Aktuelles Gehalt', d.current_salary],
    ['Wunschgehalt', d.salary_expectation],
    ['Mindestgehalt', d.salary_minimum],
  ] as const) {
    const t = v.trim()
    if (t !== '' && (!Number.isFinite(Number(t)) || Number(t) < 0)) {
      return `${label} muss eine positive Zahl sein.`
    }
  }
  // A floor above the wish is a typo every time, and it would silently break
  // the comparison against a mandate's band.
  const min = toNum(d.salary_minimum)
  const wish = toNum(d.salary_expectation)
  if (min !== null && wish !== null && min > wish) {
    return 'Mindestgehalt liegt über dem Wunschgehalt.'
  }
  return null
}

const cleanList = (a: string[]) => a.map((x) => x.trim()).filter(Boolean)

function cleanRole(r: WorkRoleDTO): WorkRoleDTO {
  return {
    ...r,
    title: r.title?.trim() || undefined,
    company: r.company?.trim() || undefined,
    location: r.location?.trim() || undefined,
    start_date: r.start_date?.trim() || undefined,
    end_date: r.end_date?.trim() || undefined,
    highlights: (r.highlights ?? []).map((h) => h.trim()).filter(Boolean),
  }
}

function cleanEdu(e: EducationDTO): EducationDTO {
  return {
    degree: e.degree?.trim() || undefined,
    institution: e.institution?.trim() || undefined,
    location: e.location?.trim() || undefined,
    start_date: e.start_date?.trim() || undefined,
    end_date: e.end_date?.trim() || undefined,
  }
}

/** Build a PATCH body containing only the fields that actually changed. */
function buildPatch(dto: CandidateDTO, d: Draft): CandidateUpdatePayload {
  const patch: CandidateUpdatePayload = {}

  // Text fields: send trimmed value; empty → null (except the required name).
  const str = (key: keyof CandidateUpdatePayload, draftVal: string, orig?: string | null) => {
    const v = draftVal.trim()
    if (v !== (orig ?? '').trim()) {
      ;(patch as Record<string, unknown>)[key] = v === '' ? null : v
    }
  }
  if (d.full_name.trim() && d.full_name.trim() !== dto.full_name.trim()) {
    patch.full_name = d.full_name.trim()
  }
  str('email', d.email, dto.email)
  str('phone', d.phone, dto.phone)
  str('current_title', d.current_title, dto.current_title)
  str('current_company', d.current_company, dto.current_company)
  str('location', d.location, dto.location)
  str('first_name', d.first_name, dto.first_name)
  str('last_name', d.last_name, dto.last_name)
  str('sex', d.sex, dto.sex)
  str('name_prefix', d.name_prefix, dto.name_prefix)
  str('date_of_birth', d.date_of_birth, dto.date_of_birth)
  str('street', d.street, dto.street)
  str('postal_code', d.postal_code, dto.postal_code)
  str('city', d.city, dto.city)
  str('country', d.country, dto.country)
  str('linkedin_url', d.linkedin_url, dto.linkedin_url)
  str('xing_url', d.xing_url, dto.xing_url)
  str('employment_type', d.employment_type, dto.employment_type)
  str('willing_to_relocate', d.willing_to_relocate, dto.willing_to_relocate)
  str('notice_period', d.notice_period, dto.notice_period)
  str('availability', d.availability, dto.availability)
  str('total_years_experience', d.total_years_experience, dto.total_years_experience)
  str('source', d.source, dto.source)
  str('motivation', d.motivation, dto.motivation)
  str('profile_summary', d.profile_summary, dto.profile_summary)
  str('interview_availability', d.interview_availability, dto.interview_availability)
  str('other_processes', d.other_processes, dto.other_processes)

  // Currency is never null (defaults to EUR on the backend).
  const cur = d.salary_currency.trim().toUpperCase()
  if (cur && cur !== (dto.salary_currency ?? '').toUpperCase()) patch.salary_currency = cur

  // Numbers.
  const curSal = toNum(d.current_salary)
  if (curSal !== (dto.current_salary ?? null)) patch.current_salary = curSal
  const expSal = toNum(d.salary_expectation)
  if (expSal !== (dto.salary_expectation ?? null)) patch.salary_expectation = expSal
  const minSal = toNum(d.salary_minimum)
  if (minSal !== (dto.salary_minimum ?? null)) patch.salary_minimum = minSal

  // Enums. An empty Anstellungsform is a real value — "nobody has
  // established it" — so it is sent as null rather than left unchanged.
  if (d.work_permit && d.work_permit !== dto.work_permit) patch.work_permit = d.work_permit
  if (d.employment_form !== (dto.employment_form ?? '')) {
    patch.employment_form = (d.employment_form || null) as typeof patch.employment_form
  }

  // Lists — compare JSON; backend re-diffs and skips no-ops anyway.
  const skills = cleanList(d.skills)
  if (JSON.stringify(skills) !== JSON.stringify(dto.skills ?? [])) patch.skills = skills
  const industries = cleanList(d.industries)
  if (JSON.stringify(industries) !== JSON.stringify(dto.industries ?? [])) {
    patch.industries = industries
  }
  const otherCompanies = cleanList(d.other_process_companies)
  if (
    JSON.stringify(otherCompanies) !==
    JSON.stringify(dto.other_process_companies ?? [])
  ) {
    patch.other_process_companies = otherCompanies
  }
  const languages = cleanList(d.languages)
  if (JSON.stringify(languages) !== JSON.stringify(dto.languages ?? [])) patch.languages = languages

  const roles = d.work_history
    .map(cleanRole)
    .filter((r) => r.title || r.company || (r.highlights && r.highlights.length))
  if (JSON.stringify(roles) !== JSON.stringify(dto.work_history ?? [])) patch.work_history = roles

  const education = d.education.map(cleanEdu).filter((e) => e.degree || e.institution)
  const origEdu = normalizeEducation(dto.education).map(cleanEdu)
  if (JSON.stringify(education) !== JSON.stringify(origEdu)) patch.education = education

  return patch
}

/** Scroll to the box the reader came for and put the cursor in it.
 *
 *  „fehlt" in the Kerndaten list is a question; opening a form of forty
 *  inputs at the top is not an answer. */
function focusTarget(root: HTMLElement | null, field: string | undefined) {
  if (!root || !field) return
  const host = root.querySelector<HTMLElement>(`[data-field="${field}"]`)
  if (!host) return
  // Focus FIRST, then centre. Focusing scrolls the box minimally into view —
  // which on a long form lands it against the bottom edge, half under the
  // action bar — and centring afterwards puts it where a reader expects it.
  // One frame later, because the form is still laying out on mount.
  const control = host.querySelector<HTMLElement>('input, textarea, select')
  window.setTimeout(() => {
    control?.focus({ preventScroll: true })
    // Instant, not smooth: the form re-renders while the fetched record
    // settles, and an animated scroll gets cancelled half way — leaving the
    // reader at the top of the form they were sent into.
    host.scrollIntoView({ block: 'center' })
  }, 120)
}

export function DossierEditor({
  dto,
  onCancel,
  onSaved,
  focusField,
}: {
  dto: CandidateDTO
  onCancel: () => void
  onSaved: (updated: CandidateDTO) => void
  /** Open on this field — the one the Kerndaten list said was missing. */
  focusField?: string
}) {
  const [d, setD] = useState<Draft>(() => seed(dto))
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const root = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    focusTarget(root.current, focusField)
  }, [focusField])

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setD((prev) => ({ ...prev, [key]: value }))

  async function save() {
    const problem = validate(d)
    if (problem) return setErr(problem)
    const patch = buildPatch(dto, d)
    if (Object.keys(patch).length === 0) return onCancel() // nothing changed
    setErr(null)
    setSaving(true)
    try {
      const updated = await api.updateCandidate(dto.id, patch)
      onSaved(updated)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Speichern fehlgeschlagen.')
      setSaving(false)
    }
  }

  return (
    <div ref={root}>
      <Group title="Persönliche Daten">
        <TextInput label="Vollständiger Name" value={d.full_name} onChange={(v) => set('full_name', v)} name="full_name" />
        <TextInput label="Vorname" value={d.first_name} onChange={(v) => set('first_name', v)} />
        <TextInput label="Nachname" value={d.last_name} onChange={(v) => set('last_name', v)} />
        <TextInput label="Geschlecht" value={d.sex} onChange={(v) => set('sex', v)} />
        <TextInput label="Namenszusatz" value={d.name_prefix} onChange={(v) => set('name_prefix', v)} />
        <TextInput
          label="Geburtsdatum"
          value={d.date_of_birth}
          onChange={(v) => set('date_of_birth', v)}
          placeholder="TT.MM.JJJJ"
          name="date_of_birth"
        />
      </Group>

      <Group title="Kontakt">
        <TextInput label="E-Mail" value={d.email} onChange={(v) => set('email', v)} type="email" name="email" />
        <TextInput label="Telefon" value={d.phone} onChange={(v) => set('phone', v)} name="phone" />
        <TextInput label="LinkedIn" value={d.linkedin_url} onChange={(v) => set('linkedin_url', v)} name="linkedin_url" />
        <TextInput label="Xing" value={d.xing_url} onChange={(v) => set('xing_url', v)} name="xing_url" />
        <TextInput label="Straße" value={d.street} onChange={(v) => set('street', v)} name="street" />
        <TextInput label="PLZ" value={d.postal_code} onChange={(v) => set('postal_code', v)} />
        <TextInput label="Stadt" value={d.city} onChange={(v) => set('city', v)} />
        <TextInput label="Land" value={d.country} onChange={(v) => set('country', v)} />
        <TextInput label="Standort" value={d.location} onChange={(v) => set('location', v)} />
      </Group>

      <Group title="Karriere">
        <TextInput label="Job-Titel" value={d.current_title} onChange={(v) => set('current_title', v)} name="current_title" />
        <TextInput
          label="Aktuelles Unternehmen"
          value={d.current_company}
          onChange={(v) => set('current_company', v)}
        />
        <SelectInput
          label="Anstellungsform"
          value={d.employment_form}
          onChange={(v) => set('employment_form', v)}
          name="employment_form"
          options={EMPLOYMENT_FORMS}
        />
        <SelectInput
          label="Umzugsbereit"
          value={d.willing_to_relocate}
          onChange={(v) => set('willing_to_relocate', v)}
          options={RELOCATE}
        />
        <TextInput label="Kündigungsfrist" value={d.notice_period} onChange={(v) => set('notice_period', v)} name="notice_period" />
        <TextInput label="Verfügbarkeit" value={d.availability} onChange={(v) => set('availability', v)} name="availability" />
        <TextInput
          label="Berufserfahrung (Jahre)"
          value={d.total_years_experience}
          onChange={(v) => set('total_years_experience', v)}
        />
        <TextInput
          label="Aktuelles Gehalt"
          value={d.current_salary}
          onChange={(v) => set('current_salary', v)}
          name="current_salary"
          type="number"
        />
        <TextInput
          label="Mindestgehalt"
          value={d.salary_minimum}
          onChange={(v) => set('salary_minimum', v)}
          name="salary_minimum"
          type="number"
        />
        <TextInput
          label="Wunschgehalt"
          value={d.salary_expectation}
          onChange={(v) => set('salary_expectation', v)}
          name="salary_expectation"
          type="number"
        />
        <TextInput label="Währung" value={d.salary_currency} onChange={(v) => set('salary_currency', v)} />
        <SelectInput
          label="Arbeitserlaubnis"
          value={d.work_permit}
          onChange={(v) => set('work_permit', v)}
          options={WORK_PERMITS}
        />
        <TextInput label="Quelle" value={d.source} onChange={(v) => set('source', v)} />
      </Group>

      {/* What only the Qualifikationsgespräch yields — no CV states these.
          See data/examples/metadata_quailfication.txt. */}
      <Group title="Nach dem Qualifikationsgespräch">
        <TextInput
          label="Verfügbarkeit für Interviews"
          value={d.interview_availability}
          onChange={(v) => set('interview_availability', v)}
          placeholder="z. B. Mi/Do ab 11 Uhr"
        />
      </Group>

      <section className="mt-7" data-field="other_process_companies">
        <GroupLabel>Andere aktive Prozesse — bei wem</GroupLabel>
        {/* Names, not prose: the same company named by three candidates is a
            hiring need in this niche, and prose cannot be counted. */}
        <TagInput
          tags={d.other_process_companies}
          onChange={(v) => set('other_process_companies', v)}
          placeholder="Firma hinzufügen…"
        />
        <div className="mt-3" data-field="other_processes">
          <TextArea
            value={d.other_processes}
            onChange={(v) => set('other_processes', v)}
            placeholder="Notiz zum Stand der anderen Prozesse…"
          />
        </div>
      </section>

      <section className="mt-7" data-field="industries">
        <GroupLabel>Branchen</GroupLabel>
        <TagInput
          tags={d.industries}
          onChange={(v) => set('industries', v)}
          placeholder="Branche hinzufügen…"
        />
      </section>

      <section className="mt-7">
        <GroupLabel>Sprachen</GroupLabel>
        <TagInput tags={d.languages} onChange={(v) => set('languages', v)} placeholder="Sprache hinzufügen…" />
      </section>

      <section className="mt-7" data-field="skills">
        <GroupLabel>Skills</GroupLabel>
        <TagInput tags={d.skills} onChange={(v) => set('skills', v)} placeholder="Skill hinzufügen…" />
      </section>

      <section className="mt-7" data-field="work_history">
        <GroupLabel>Berufserfahrung</GroupLabel>
        <div className="space-y-3">
          {d.work_history.map((role, i) => (
            <RoleCard
              key={i}
              role={role}
              onChange={(r) => set('work_history', d.work_history.map((x, j) => (j === i ? r : x)))}
              onRemove={() => set('work_history', d.work_history.filter((_, j) => j !== i))}
            />
          ))}
          <AddButton
            label="+ Rolle hinzufügen"
            onClick={() => set('work_history', [...d.work_history, { highlights: [] }])}
          />
        </div>
      </section>

      <section className="mt-7">
        <GroupLabel>Ausbildung</GroupLabel>
        <div className="space-y-3">
          {d.education.map((edu, i) => (
            <EduCard
              key={i}
              edu={edu}
              onChange={(e) => set('education', d.education.map((x, j) => (j === i ? e : x)))}
              onRemove={() => set('education', d.education.filter((_, j) => j !== i))}
            />
          ))}
          <AddButton label="+ Ausbildung hinzufügen" onClick={() => set('education', [...d.education, {}])} />
        </div>
      </section>

      <section className="mt-7">
        <GroupLabel>Profil-Zusammenfassung</GroupLabel>
        <TextArea
          value={d.profile_summary}
          onChange={(v) => set('profile_summary', v)}
          placeholder="Zusammenfassung des Profils aus dem Gespräch…"
        />
      </section>

      <section className="mt-7" data-field="motivation">
        <GroupLabel>Wechselmotivation</GroupLabel>
        <TextArea
          value={d.motivation}
          onChange={(v) => set('motivation', v)}
          placeholder="Warum will der Kandidat wechseln?"
        />
      </section>

      {/* Sticky action bar — pinned to the bottom of the (scrolling) panel */}
      <div className="sticky bottom-0 z-10 -mx-7 mt-8 flex items-center gap-3 border-t border-cockpit-line bg-cockpit-bg px-7 py-3">
        {err && (
          <div className="flex items-center gap-1.5 text-[13px] font-medium text-coral-400">
            <AlertCircle className="h-4 w-4 shrink-0" /> {err}
          </div>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Button onClick={onCancel} disabled={saving}>
            <Ban className="h-4 w-4" /> Abbrechen
          </Button>
          <Button tone="primary" onClick={save} disabled={saving}>
            <Save className="h-4 w-4" /> {saving ? 'Speichert…' : 'Speichern'}
          </Button>
        </div>
      </div>
    </div>
  )
}

/* ---------- layout helpers (inputs come from ../../ui/forms) ---------- */

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-7 first:mt-0">
      <GroupLabel>{title}</GroupLabel>
      <div className="grid grid-cols-2 gap-x-5 gap-y-3 md:grid-cols-3">{children}</div>
    </section>
  )
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-2 flex items-center gap-1 font-mono text-[12px] text-cockpit-faint transition-colors hover:text-coral-400"
    >
      <Trash2 className="h-3.5 w-3.5" /> Entfernen
    </button>
  )
}

function RoleCard({
  role,
  onChange,
  onRemove,
}: {
  role: WorkRoleDTO
  onChange: (r: WorkRoleDTO) => void
  onRemove: () => void
}) {
  const upd = (patch: Partial<WorkRoleDTO>) => onChange({ ...role, ...patch })
  return (
    <div className="rounded-xl border border-cockpit-line bg-cockpit-raised p-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <MiniInput placeholder="Titel" value={role.title ?? ''} onChange={(v) => upd({ title: v })} span2 />
        <MiniInput placeholder="Unternehmen" value={role.company ?? ''} onChange={(v) => upd({ company: v })} />
        <MiniInput placeholder="Ort" value={role.location ?? ''} onChange={(v) => upd({ location: v })} />
        <MiniInput
          placeholder="Von (z.B. 03/2021)"
          value={role.start_date ?? ''}
          onChange={(v) => upd({ start_date: v })}
        />
        <MiniInput
          placeholder="Bis (z.B. heute)"
          value={role.end_date ?? ''}
          onChange={(v) => upd({ end_date: v })}
        />
      </div>
      <TextArea
        value={(role.highlights ?? []).join('\n')}
        onChange={(v) => upd({ highlights: v.split('\n') })}
        rows={2}
        placeholder="Aufgaben / Erfolge — eine pro Zeile"
        className="mt-2 text-[13px]"
      />
      <RemoveButton onClick={onRemove} />
    </div>
  )
}

function EduCard({
  edu,
  onChange,
  onRemove,
}: {
  edu: EducationDTO
  onChange: (e: EducationDTO) => void
  onRemove: () => void
}) {
  const upd = (patch: Partial<EducationDTO>) => onChange({ ...edu, ...patch })
  return (
    <div className="rounded-xl border border-cockpit-line bg-cockpit-raised p-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <MiniInput placeholder="Abschluss" value={edu.degree ?? ''} onChange={(v) => upd({ degree: v })} span2 />
        <MiniInput
          placeholder="Institution"
          value={edu.institution ?? ''}
          onChange={(v) => upd({ institution: v })}
        />
        <MiniInput placeholder="Ort" value={edu.location ?? ''} onChange={(v) => upd({ location: v })} />
        <MiniInput placeholder="Von" value={edu.start_date ?? ''} onChange={(v) => upd({ start_date: v })} />
        <MiniInput placeholder="Bis" value={edu.end_date ?? ''} onChange={(v) => upd({ end_date: v })} />
      </div>
      <RemoveButton onClick={onRemove} />
    </div>
  )
}
