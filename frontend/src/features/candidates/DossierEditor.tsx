import { useState } from 'react'
import { Plus, Trash2, X, Save, Ban, AlertCircle } from 'lucide-react'
import { api } from '@/api/client'
import type { CandidateDTO, CandidateUpdatePayload, EducationDTO, WorkRoleDTO } from '@/api/types'

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
  industry: string
  employment_type: string
  willing_to_relocate: string
  notice_period: string
  availability: string
  total_years_experience: string
  current_salary: string
  salary_expectation: string
  salary_currency: string
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
    industry: s(dto.industry),
    employment_type: s(dto.employment_type),
    willing_to_relocate: s(dto.willing_to_relocate),
    notice_period: s(dto.notice_period),
    availability: s(dto.availability),
    total_years_experience: s(dto.total_years_experience),
    current_salary: numStr(dto.current_salary),
    salary_expectation: numStr(dto.salary_expectation),
    salary_currency: dto.salary_currency || 'EUR',
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
  ] as const) {
    const t = v.trim()
    if (t !== '' && (!Number.isFinite(Number(t)) || Number(t) < 0)) {
      return `${label} muss eine positive Zahl sein.`
    }
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
  str('industry', d.industry, dto.industry)
  str('employment_type', d.employment_type, dto.employment_type)
  str('willing_to_relocate', d.willing_to_relocate, dto.willing_to_relocate)
  str('notice_period', d.notice_period, dto.notice_period)
  str('availability', d.availability, dto.availability)
  str('total_years_experience', d.total_years_experience, dto.total_years_experience)
  str('source', d.source, dto.source)
  str('motivation', d.motivation, dto.motivation)

  // Currency is never null (defaults to EUR on the backend).
  const cur = d.salary_currency.trim().toUpperCase()
  if (cur && cur !== (dto.salary_currency ?? '').toUpperCase()) patch.salary_currency = cur

  // Numbers.
  const curSal = toNum(d.current_salary)
  if (curSal !== (dto.current_salary ?? null)) patch.current_salary = curSal
  const expSal = toNum(d.salary_expectation)
  if (expSal !== (dto.salary_expectation ?? null)) patch.salary_expectation = expSal

  // Enum.
  if (d.work_permit && d.work_permit !== dto.work_permit) patch.work_permit = d.work_permit

  // Lists — compare JSON; backend re-diffs and skips no-ops anyway.
  const skills = cleanList(d.skills)
  if (JSON.stringify(skills) !== JSON.stringify(dto.skills ?? [])) patch.skills = skills
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

export function DossierEditor({
  dto,
  onCancel,
  onSaved,
}: {
  dto: CandidateDTO
  onCancel: () => void
  onSaved: (updated: CandidateDTO) => void
}) {
  const [d, setD] = useState<Draft>(() => seed(dto))
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

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
    <div>
      {/* Persönliche Daten */}
      <Group title="Persönliche Daten">
        <TextField label="Vollständiger Name" value={d.full_name} onChange={(v) => set('full_name', v)} />
        <TextField label="Vorname" value={d.first_name} onChange={(v) => set('first_name', v)} />
        <TextField label="Nachname" value={d.last_name} onChange={(v) => set('last_name', v)} />
        <TextField label="Geschlecht" value={d.sex} onChange={(v) => set('sex', v)} />
        <TextField label="Namenszusatz" value={d.name_prefix} onChange={(v) => set('name_prefix', v)} />
        <TextField
          label="Geburtsdatum"
          value={d.date_of_birth}
          onChange={(v) => set('date_of_birth', v)}
          placeholder="TT.MM.JJJJ"
        />
      </Group>

      {/* Kontakt */}
      <Group title="Kontakt">
        <TextField label="E-Mail" value={d.email} onChange={(v) => set('email', v)} type="email" />
        <TextField label="Telefon" value={d.phone} onChange={(v) => set('phone', v)} />
        <TextField label="LinkedIn" value={d.linkedin_url} onChange={(v) => set('linkedin_url', v)} />
        <TextField label="Xing" value={d.xing_url} onChange={(v) => set('xing_url', v)} />
        <TextField label="Straße" value={d.street} onChange={(v) => set('street', v)} />
        <TextField label="PLZ" value={d.postal_code} onChange={(v) => set('postal_code', v)} />
        <TextField label="Stadt" value={d.city} onChange={(v) => set('city', v)} />
        <TextField label="Land" value={d.country} onChange={(v) => set('country', v)} />
        <TextField label="Standort" value={d.location} onChange={(v) => set('location', v)} />
      </Group>

      {/* Karriere */}
      <Group title="Karriere">
        <TextField label="Job-Titel" value={d.current_title} onChange={(v) => set('current_title', v)} />
        <TextField
          label="Aktuelles Unternehmen"
          value={d.current_company}
          onChange={(v) => set('current_company', v)}
        />
        <TextField label="Branche" value={d.industry} onChange={(v) => set('industry', v)} />
        <TextField label="Anstellungsart" value={d.employment_type} onChange={(v) => set('employment_type', v)} />
        <SelectField
          label="Umzugsbereit"
          value={d.willing_to_relocate}
          onChange={(v) => set('willing_to_relocate', v)}
          options={RELOCATE}
        />
        <TextField label="Kündigungsfrist" value={d.notice_period} onChange={(v) => set('notice_period', v)} />
        <TextField label="Verfügbarkeit" value={d.availability} onChange={(v) => set('availability', v)} />
        <TextField
          label="Berufserfahrung (Jahre)"
          value={d.total_years_experience}
          onChange={(v) => set('total_years_experience', v)}
        />
        <TextField
          label="Aktuelles Gehalt"
          value={d.current_salary}
          onChange={(v) => set('current_salary', v)}
          type="number"
        />
        <TextField
          label="Wunschgehalt"
          value={d.salary_expectation}
          onChange={(v) => set('salary_expectation', v)}
          type="number"
        />
        <TextField label="Währung" value={d.salary_currency} onChange={(v) => set('salary_currency', v)} />
        <SelectField
          label="Arbeitserlaubnis"
          value={d.work_permit}
          onChange={(v) => set('work_permit', v)}
          options={WORK_PERMITS}
        />
        <TextField label="Quelle" value={d.source} onChange={(v) => set('source', v)} />
      </Group>

      {/* Sprachen */}
      <section className="mt-6">
        <Label>Sprachen</Label>
        <TagEditor tags={d.languages} onChange={(v) => set('languages', v)} placeholder="Sprache hinzufügen…" />
      </section>

      {/* Skills */}
      <section className="mt-6">
        <Label>Skills</Label>
        <TagEditor tags={d.skills} onChange={(v) => set('skills', v)} placeholder="Skill hinzufügen…" />
      </section>

      {/* Berufserfahrung */}
      <section className="mt-7">
        <Label>Berufserfahrung</Label>
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
            label="Rolle hinzufügen"
            onClick={() => set('work_history', [...d.work_history, { highlights: [] }])}
          />
        </div>
      </section>

      {/* Ausbildung */}
      <section className="mt-7">
        <Label>Ausbildung</Label>
        <div className="space-y-3">
          {d.education.map((edu, i) => (
            <EduCard
              key={i}
              edu={edu}
              onChange={(e) => set('education', d.education.map((x, j) => (j === i ? e : x)))}
              onRemove={() => set('education', d.education.filter((_, j) => j !== i))}
            />
          ))}
          <AddButton label="Ausbildung hinzufügen" onClick={() => set('education', [...d.education, {}])} />
        </div>
      </section>

      {/* Profil / Motivation */}
      <section className="mt-7">
        <Label>Profil</Label>
        <textarea
          value={d.motivation}
          onChange={(e) => set('motivation', e.target.value)}
          rows={4}
          className="w-full rounded-lg border border-line px-3 py-2 text-[14px] leading-relaxed text-ink outline-none focus:border-brand-500"
          placeholder="Kurzprofil / Motivation…"
        />
      </section>

      {/* Sticky action bar — pinned to the bottom of the (scrolling) panel */}
      <div className="sticky bottom-0 z-10 -mx-7 mt-7 flex items-center gap-3 border-t border-line bg-white px-7 py-3">
        {err && (
          <div className="flex items-center gap-1.5 text-[13px] font-medium text-rose-600">
            <AlertCircle className="h-4 w-4" /> {err}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={onCancel}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-xl border border-line px-3.5 py-2 text-[13px] font-medium text-ink-soft hover:bg-slate-50 disabled:opacity-50"
          >
            <Ban className="h-4 w-4" /> Abbrechen
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-xl bg-brand-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
          >
            <Save className="h-4 w-4" /> {saving ? 'Speichert…' : 'Speichern'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ---------- input primitives ---------- */

function Label({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-ink-muted">{children}</h4>
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 first:mt-0">
      <Label>{title}</Label>
      <div className="grid grid-cols-2 gap-x-5 gap-y-3 md:grid-cols-3">{children}</div>
    </section>
  )
}

const fieldClass =
  'w-full rounded-lg border border-line px-2.5 py-1.5 text-[14px] text-ink outline-none focus:border-brand-500'

function TextField({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: 'text' | 'email' | 'number'
}) {
  return (
    <label className="min-w-0 block">
      <span className="mb-1 block text-[11px] uppercase tracking-wide text-ink-faint">{label}</span>
      <input
        type={type}
        inputMode={type === 'number' ? 'numeric' : undefined}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={fieldClass}
      />
    </label>
  )
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <label className="min-w-0 block">
      <span className="mb-1 block text-[11px] uppercase tracking-wide text-ink-faint">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={fieldClass}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function TagEditor({
  tags,
  onChange,
  placeholder,
}: {
  tags: string[]
  onChange: (v: string[]) => void
  placeholder?: string
}) {
  const [input, setInput] = useState('')
  const add = () => {
    const v = input.trim()
    if (v && !tags.includes(v)) onChange([...tags, v])
    setInput('')
  }
  return (
    <div className="rounded-lg border border-line p-2 focus-within:border-brand-500">
      <div className="flex flex-wrap gap-1.5">
        {tags.map((t, i) => (
          <span
            key={`${t}-${i}`}
            className="flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-[12px] font-medium text-ink-soft"
          >
            {t}
            <button
              onClick={() => onChange(tags.filter((_, j) => j !== i))}
              className="text-ink-faint hover:text-rose-600"
              aria-label={`${t} entfernen`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              add()
            } else if (e.key === 'Backspace' && !input && tags.length) {
              onChange(tags.slice(0, -1))
            }
          }}
          onBlur={add}
          placeholder={placeholder}
          className="min-w-[120px] flex-1 bg-transparent px-1 text-[13px] outline-none placeholder:text-ink-faint"
        />
      </div>
    </div>
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
    <div className="rounded-xl border border-line p-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <MiniInput placeholder="Titel" value={role.title ?? ''} onChange={(v) => upd({ title: v })} span2 />
        <MiniInput placeholder="Unternehmen" value={role.company ?? ''} onChange={(v) => upd({ company: v })} />
        <MiniInput placeholder="Ort" value={role.location ?? ''} onChange={(v) => upd({ location: v })} />
        <MiniInput placeholder="Von (z.B. 03/2021)" value={role.start_date ?? ''} onChange={(v) => upd({ start_date: v })} />
        <MiniInput placeholder="Bis (z.B. heute)" value={role.end_date ?? ''} onChange={(v) => upd({ end_date: v })} />
      </div>
      <textarea
        value={(role.highlights ?? []).join('\n')}
        onChange={(e) => upd({ highlights: e.target.value.split('\n') })}
        rows={2}
        placeholder="Aufgaben / Erfolge — eine pro Zeile"
        className="mt-2 w-full rounded-lg border border-line px-2.5 py-1.5 text-[13px] text-ink-soft outline-none focus:border-brand-500"
      />
      <button
        onClick={onRemove}
        className="mt-1.5 flex items-center gap-1 text-[12px] font-medium text-ink-faint hover:text-rose-600"
      >
        <Trash2 className="h-3.5 w-3.5" /> Entfernen
      </button>
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
    <div className="rounded-xl border border-line p-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <MiniInput placeholder="Abschluss" value={edu.degree ?? ''} onChange={(v) => upd({ degree: v })} span2 />
        <MiniInput placeholder="Institution" value={edu.institution ?? ''} onChange={(v) => upd({ institution: v })} />
        <MiniInput placeholder="Ort" value={edu.location ?? ''} onChange={(v) => upd({ location: v })} />
        <MiniInput placeholder="Von" value={edu.start_date ?? ''} onChange={(v) => upd({ start_date: v })} />
        <MiniInput placeholder="Bis" value={edu.end_date ?? ''} onChange={(v) => upd({ end_date: v })} />
      </div>
      <button
        onClick={onRemove}
        className="mt-1.5 flex items-center gap-1 text-[12px] font-medium text-ink-faint hover:text-rose-600"
      >
        <Trash2 className="h-3.5 w-3.5" /> Entfernen
      </button>
    </div>
  )
}

function MiniInput({
  value,
  onChange,
  placeholder,
  span2,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  span2?: boolean
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`${span2 ? 'col-span-2' : ''} rounded-lg border border-line px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-brand-500`}
    />
  )
}

function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-lg border border-dashed border-line px-3 py-2 text-[13px] font-medium text-ink-soft hover:border-brand-500 hover:text-brand-700"
    >
      <Plus className="h-4 w-4" /> {label}
    </button>
  )
}
