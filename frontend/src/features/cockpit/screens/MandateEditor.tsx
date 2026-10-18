// Editing a mandate — the Suchprofil, as a form.
//
// Until now a mandate could only be created by an import or a script, so the
// band, the radius and the Muss-Kriterien were unreachable from the product
// that reads them. Three of these fields are **hard filters**: `salary_max`,
// `location_radius_km` and the required certifications decide who the matcher
// excludes outright. That is why the form says so out loud, why the band is
// validated before it is sent, and why every change leaves a receipt on the
// way in.

import { t } from '@/i18n'

import { useState } from 'react'
import { AlertCircle, X } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { CompanyDTO, JobDTO } from '@/api/types'
import { Button, SelectInput, TagInput, TextInput } from '../ui/forms'
import { Panel } from '../ui/primitives'

const STATUS_OPTIONS = [
  { value: 'open', label: t('Offen') },
  { value: 'on_hold', label: t('Pausiert') },
  { value: 'filled', label: t('Besetzt') },
  { value: 'cancelled', label: t('Abgesagt') },
]

const RELOCATE_PERMIT = [
  { value: 'true', label: t('Erforderlich') },
  { value: 'false', label: t('Nicht erforderlich') },
]

interface Draft {
  title: string
  client_company_id: string
  location: string
  location_radius_km: string
  salary_min: string
  salary_max: string
  salary_currency: string
  status: string
  requires_work_permit: string
  must_have_skills: string[]
  required_certifications: string[]
}

const num = (v?: number | null) => (v == null ? '' : String(v))

function seed(job: JobDTO): Draft {
  return {
    title: job.title,
    client_company_id: job.client_company_id ?? '',
    location: job.location ?? '',
    location_radius_km: num(job.location_radius_km),
    salary_min: num(job.salary_min),
    salary_max: num(job.salary_max),
    salary_currency: job.salary_currency || 'EUR',
    status: job.status || 'open',
    requires_work_permit: String(job.requires_work_permit ?? true),
    must_have_skills: [...(job.must_have_skills ?? [])],
    required_certifications: [...(job.required_certifications ?? [])],
  }
}

/** '' → null, '95000' → 95000. Anything unparseable stays null rather than
 *  becoming 0 — a cap of zero would exclude every candidate alive. */
function toNum(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) && parsed >= 0 ? Math.round(parsed) : null
}

export function MandateEditor({
  job,
  companies,
  onClose,
  onSaved,
}: {
  job: JobDTO
  companies: CompanyDTO[]
  onClose: () => void
  onSaved: (updated: JobDTO) => void
}) {
  const [d, setD] = useState<Draft>(() => seed(job))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setD((prev) => ({ ...prev, [key]: value }))

  const companyOptions = [
    { value: '', label: t('— kein Kunde zugeordnet') },
    ...companies
      .map((c) => ({ value: c.id, label: c.name }))
      .sort((a, b) => a.label.localeCompare(b.label)),
  ]

  async function save() {
    if (!d.title.trim()) return setError(t('Titel darf nicht leer sein.'))
    for (const [label, raw] of [
      [t('Gehalt von'), d.salary_min],
      [t('Gehalt bis'), d.salary_max],
      [t('Umkreis'), d.location_radius_km],
    ] as const) {
      if (raw.trim() !== '' && toNum(raw) === null) {
        return setError(t('{label} muss eine positive Zahl sein.', { label }))
      }
    }
    const min = toNum(d.salary_min)
    const max = toNum(d.salary_max)
    // Checked here as well as on the server: an inverted band is a typo, and
    // a 422 after the dialog closes is a worse way to learn about it.
    if (min !== null && max !== null && min > max) {
      return setError(t('Gehalt von liegt über Gehalt bis.'))
    }

    setBusy(true)
    setError(null)
    try {
      const updated = await api.updateJob(job.id, {
        title: d.title.trim(),
        client_company_id: d.client_company_id || null,
        location: d.location.trim() || null,
        location_radius_km: toNum(d.location_radius_km),
        salary_min: min,
        salary_max: max,
        salary_currency: d.salary_currency.trim().toUpperCase() || 'EUR',
        status: d.status,
        requires_work_permit: d.requires_work_permit === 'true',
        must_have_skills: d.must_have_skills.map((s) => s.trim()).filter(Boolean),
        required_certifications: d.required_certifications
          .map((s) => s.trim())
          .filter(Boolean),
      })
      onSaved(updated)
      onClose()
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 422
          ? t('Abgelehnt — bitte Gehaltsband und Status prüfen.')
          : e instanceof ApiError
            ? t('Konnte nicht gespeichert werden (HTTP {status}).', { status: e.status })
            : t('Konnte nicht gespeichert werden — keine Antwort vom Server.'),
      )
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 py-10"
      onClick={onClose}
    >
      {/* The backdrop closes the dialog; clicks inside must not reach it. */}
      <div className="w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
        <Panel className="space-y-5 p-6">
          <div className="flex items-start gap-3">
            <div>
              <h3 className="text-[18px] font-semibold text-cockpit-text">
                {t('Mandat bearbeiten')}
              </h3>
              <p className="mt-0.5 font-mono text-[12px] text-cockpit-faint">
                {t('Suchprofil · steuert die harten Filter im Matching')}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('Schließen')}
              className="ml-auto text-cockpit-faint transition-colors hover:text-cockpit-text"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <TextInput label={t('Titel')} value={d.title} onChange={(v) => set('title', v)} />
            <SelectInput
              label={t('Kunde')}
              value={d.client_company_id}
              onChange={(v) => set('client_company_id', v)}
              options={companyOptions}
            />
            <TextInput
              label={t('Ort')}
              value={d.location}
              onChange={(v) => set('location', v)}
              placeholder={t('z. B. München')}
            />
            <TextInput
              label={t('Umkreis (km)')}
              value={d.location_radius_km}
              onChange={(v) => set('location_radius_km', v)}
              type="number"
              placeholder={t('leer = kein Radius-Filter')}
            />
            <TextInput
              label={t('Gehalt von')}
              value={d.salary_min}
              onChange={(v) => set('salary_min', v)}
              type="number"
            />
            <TextInput
              label={t('Gehalt bis (Obergrenze)')}
              value={d.salary_max}
              onChange={(v) => set('salary_max', v)}
              type="number"
            />
            <TextInput
              label={t('Währung')}
              value={d.salary_currency}
              onChange={(v) => set('salary_currency', v)}
            />
            <SelectInput
              label={t('Status')}
              value={d.status}
              onChange={(v) => set('status', v)}
              options={STATUS_OPTIONS}
            />
            <SelectInput
              label={t('Arbeitserlaubnis')}
              value={d.requires_work_permit}
              onChange={(v) => set('requires_work_permit', v)}
              options={RELOCATE_PERMIT}
            />
          </div>

          <div className="space-y-2">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              {t('Muss-Kriterien')}
            </span>
            <TagInput
              tags={d.must_have_skills}
              onChange={(v) => set('must_have_skills', v)}
              placeholder={t('Skill hinzufügen…')}
            />
          </div>

          <div className="space-y-2">
            <span className="font-mono text-[12px] uppercase tracking-wide text-cockpit-faint">
              {t('Erforderliche Zertifikate')}
            </span>
            <TagInput
              tags={d.required_certifications}
              onChange={(v) => set('required_certifications', v)}
              placeholder={t('Zertifikat hinzufügen…')}
            />
          </div>

          <p className="text-[12px] leading-relaxed text-cockpit-faint">
            {t('Obergrenze, Umkreis und Zertifikate sind harte Filter: ein Kandidat, der sie reißt, wird ausgeschlossen — nicht nur schlechter bewertet. Jede Änderung wird mit Beleg protokolliert.')}
          </p>

          {error && (
            <p className="flex items-center gap-1.5 text-[13px] text-coral-400">
              <AlertCircle className="h-4 w-4 shrink-0" /> {error}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>{t('Abbrechen')}</Button>
            <Button tone="primary" onClick={save} disabled={busy}>
              {busy ? t('Speichert…') : t('Speichern')}
            </Button>
          </div>
        </Panel>
      </div>
    </div>
  )
}
