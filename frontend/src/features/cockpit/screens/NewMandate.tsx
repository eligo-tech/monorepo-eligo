// "Neues Mandat" — the client, the job, and who to call there, in one pass.
//
// This was the hole in the product. `POST /jobs` and `POST /companies` have
// existed the whole time and NOTHING in the frontend called either, so a new
// workspace could only ever work with what an ATS import had put there. And
// `jobs.manager_id` existed since the first migration while appearing in no
// schema at all, which is why a mandate could only say "Kein Ansprechpartner
// hinterlegt — über Projekte anreichern" and send the reader to another
// screen that does not link a contact to a job either.
//
// Three decisions this form makes:
//
//  1. **The title is the only required field.** A search starts before the
//     band, the region and often the contact are known — the showcase mandate
//     literally has no contact — and a form that insists on all of it is a
//     form people fill in somewhere else.
//  2. **A client and a contact can be created without leaving.** "Pick from a
//     list or type a new name" in one control, because the alternative is
//     three screens in sequence to record one phone call.
//  3. **A new contact is a person, so it carries provenance.** `source` and
//     `source_detail` are set on the way in; that is what the Art. 14 flow
//     reads later. A contact recorded with no origin cannot be assessed for
//     it afterwards.

import { useMemo, useState } from 'react'
import { Building2, Check, Plus, UserRound, X } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { CompanyDTO, ManagerDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { searchScore } from '@/lib/search'
import {
  Button,
  CloseButton,
  FieldLabel,
  Modal,
  TagInput,
  TextInput,
} from '../ui/forms'
import { Label } from '../ui/primitives'

/** "92.000" / "92000" / "92k" → 92000. Empty → null. */
function toAmount(text: string): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const digits = trimmed.replace(/[^\d]/g, '')
  if (!digits) return null
  const value = Number(digits)
  return /k$/i.test(trimmed) && value < 1000 ? value * 1000 : value
}

/** Pick one of these, or type a name that is not in the list yet. */
function Picker<T extends { id: string }>({
  rows,
  label,
  placeholder,
  nameOf,
  hintOf,
  value,
  onPick,
  draft,
  onDraft,
  icon: Icon,
}: {
  rows: T[]
  label: string
  placeholder: string
  nameOf: (row: T) => string
  hintOf?: (row: T) => string | null
  value: string | null
  onPick: (id: string | null) => void
  /** The typed name, when it matches nothing — what would be created. */
  draft: string
  onDraft: (text: string) => void
  icon: typeof Building2
}) {
  const [query, setQuery] = useState('')
  const picked = rows.find((r) => r.id === value) ?? null

  const matches = useMemo(() => {
    if (!query.trim()) return rows.slice(0, 6)
    return rows
      .map((row) => ({ row, score: searchScore([{ text: nameOf(row), weight: 1 }], query) }))
      .filter((m) => m.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 6)
      .map((m) => m.row)
  }, [rows, query, nameOf])

  // Typing a name nothing matches is a request to create it, not an error.
  const exact = rows.some(
    (row) => nameOf(row).trim().toLowerCase() === query.trim().toLowerCase(),
  )
  const wouldCreate = query.trim().length > 1 && !exact

  if (picked) {
    return (
      <div className="space-y-1">
        <FieldLabel>{label}</FieldLabel>
        <div className="flex items-center gap-2 rounded-lg border border-mint-700/50 bg-mint-800/20 px-3 py-2">
          <Icon className="h-4 w-4 shrink-0 text-mint-400" />
          <span className="min-w-0 flex-1 truncate text-[13.5px] text-cockpit-text">
            {nameOf(picked)}
            {hintOf?.(picked) && (
              <span className="ml-2 font-mono text-[11px] text-cockpit-faint">
                {hintOf(picked)}
              </span>
            )}
          </span>
          <button
            type="button"
            onClick={() => {
              onPick(null)
              onDraft('')
              setQuery('')
            }}
            className="shrink-0 text-cockpit-faint transition-colors hover:text-coral-300"
            title="ändern"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    )
  }

  if (draft) {
    return (
      <div className="space-y-1">
        <FieldLabel>{label}</FieldLabel>
        <div className="flex items-center gap-2 rounded-lg border border-gold-600/50 bg-gold-800/20 px-3 py-2">
          <Plus className="h-4 w-4 shrink-0 text-gold-400" />
          <span className="min-w-0 flex-1 truncate text-[13.5px] text-cockpit-text">
            {draft}
            <span className="ml-2 font-mono text-[11px] text-gold-300">wird neu angelegt</span>
          </span>
          <button
            type="button"
            onClick={() => {
              onDraft('')
              setQuery('')
            }}
            className="shrink-0 text-cockpit-faint transition-colors hover:text-coral-300"
            title="verwerfen"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-1">
      <TextInput label={label} value={query} onChange={setQuery} placeholder={placeholder} />
      {(matches.length > 0 || wouldCreate) && (
        <div className="mt-1 overflow-hidden rounded-lg border border-cockpit-line">
          {matches.map((row) => (
            <button
              key={row.id}
              type="button"
              onClick={() => onPick(row.id)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-cockpit-dim transition-colors hover:bg-cockpit-raised hover:text-cockpit-text"
            >
              <Icon className="h-3.5 w-3.5 shrink-0 text-cockpit-faint" />
              <span className="min-w-0 flex-1 truncate">{nameOf(row)}</span>
              {hintOf?.(row) && (
                <span className="shrink-0 font-mono text-[11px] text-cockpit-faint">
                  {hintOf(row)}
                </span>
              )}
            </button>
          ))}
          {wouldCreate && (
            <button
              type="button"
              onClick={() => onDraft(query.trim())}
              className="flex w-full items-center gap-2 border-t border-cockpit-line px-3 py-2 text-left text-[13px] text-gold-300 transition-colors hover:bg-gold-800/20"
            >
              <Plus className="h-3.5 w-3.5 shrink-0" />
              „{query.trim()}" neu anlegen
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function NewMandate({
  onClose,
  onCreated,
}: {
  onClose: () => void
  /** Hands back the new job id so the caller can open its cockpit. */
  onCreated: (jobId: string) => void
}) {
  const [title, setTitle] = useState('')
  const [companyId, setCompanyId] = useState<string | null>(null)
  const [companyDraft, setCompanyDraft] = useState('')
  const [managerId, setManagerId] = useState<string | null>(null)
  const [managerDraft, setManagerDraft] = useState('')
  const [managerRole, setManagerRole] = useState('')
  const [managerEmail, setManagerEmail] = useState('')
  const [location, setLocation] = useState('')
  const [salaryMin, setSalaryMin] = useState('')
  const [salaryMax, setSalaryMax] = useState('')
  const [mustHave, setMustHave] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: companies } = useAsync<CompanyDTO[]>(
    () => api.companies().catch(() => []),
    [],
  )
  // Contacts at the chosen client only: a mandate's Ansprechpartner works
  // there, and the backend refuses one who does not.
  const { data: managers } = useAsync<ManagerDTO[]>(
    () =>
      companyId
        ? api.managers({ companyId, limit: 200 }).catch(() => [])
        : Promise.resolve([]),
    [companyId],
  )

  const hasClient = Boolean(companyId || companyDraft.trim())
  const canSave = title.trim().length > 1 && hasClient && !busy

  async function save() {
    if (!canSave) return
    setBusy(true)
    setError(null)
    try {
      let client = companyId
      if (!client && companyDraft.trim()) {
        client = (await api.createCompany({ name: companyDraft.trim() })).id
      }

      let contact = managerId
      if (!contact && managerDraft.trim() && client) {
        contact = (
          await api.createManager({
            company_id: client,
            full_name: managerDraft.trim(),
            role_title: managerRole.trim() || null,
            email: managerEmail.trim() || null,
            // Provenance on the way in: the Art. 14 flow reads this later,
            // and a contact with no recorded origin cannot be assessed for
            // it afterwards.
            source: 'self_reported',
            source_detail: `beim Anlegen des Mandats „${title.trim()}" erfasst`,
          })
        ).id
      }

      const job = await api.createJob({
        title: title.trim(),
        client_company_id: client,
        manager_id: contact,
        location: location.trim() || null,
        must_have_skills: mustHave,
        salary_min: toAmount(salaryMin),
        salary_max: toAmount(salaryMax),
      })
      onCreated(job.id)
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `Nicht angelegt (HTTP ${e.status}). ${e.status === 422 ? 'Bitte Eingaben prüfen.' : ''}`
          : 'Nicht angelegt — bitte erneut versuchen.',
      )
      setBusy(false)
    }
  }

  return (
    <Modal onClose={onClose} className="max-w-3xl">
      <div className="flex items-center gap-3 border-b border-cockpit-line px-7 py-4">
        <Label>Neues Mandat</Label>
        <span className="ml-auto">
          <CloseButton onClose={onClose} />
        </span>
      </div>
      <div className="space-y-5 overflow-y-auto px-7 py-6">
        <p className="text-[13px] leading-relaxed text-cockpit-dim">
          Kunde, Job und Ansprechpartner in einem Schritt. Nur der Job-Titel ist
          nötig — Ort, Band und Muss-Kriterien lassen sich im Mandat jederzeit
          nachtragen.
        </p>

        <TextInput
          label="Job-Titel"
          value={title}
          onChange={setTitle}
          placeholder="IT-Administrator produktionsnahe IT / OT (m/w/d)"
        />

        <Picker
          rows={companies ?? []}
          label="Kunde"
          placeholder="Firma suchen oder neuen Namen eingeben…"
          nameOf={(c) => c.name}
          value={companyId}
          onPick={(id) => {
            setCompanyId(id)
            setManagerId(null)
            setManagerDraft('')
          }}
          draft={companyDraft}
          onDraft={setCompanyDraft}
          icon={Building2}
        />

        {hasClient && (
          <>
            <Picker
              rows={managers ?? []}
              label="Ansprechpartner (optional)"
              placeholder={
                companyId
                  ? 'Kontakt suchen oder neuen Namen eingeben…'
                  : 'Name des Ansprechpartners…'
              }
              nameOf={(m) => m.full_name}
              hintOf={(m) => m.role_title ?? null}
              value={managerId}
              onPick={setManagerId}
              draft={managerDraft}
              onDraft={setManagerDraft}
              icon={UserRound}
            />
            {managerDraft && (
              <div className="grid gap-3 sm:grid-cols-2">
                <TextInput
                  label="Rolle"
                  value={managerRole}
                  onChange={setManagerRole}
                  placeholder="Head of IT"
                />
                <TextInput
                  label="E-Mail"
                  value={managerEmail}
                  onChange={setManagerEmail}
                  placeholder="optional"
                />
              </div>
            )}
          </>
        )}

        <div className="space-y-3 border-t border-cockpit-line pt-4">
          <Label>Suchprofil · später ergänzbar</Label>
          <div className="grid gap-3 sm:grid-cols-3">
            <TextInput
              label="Ort"
              value={location}
              onChange={setLocation}
              placeholder="Dillenburg"
            />
            <TextInput
              label="Band von"
              value={salaryMin}
              onChange={setSalaryMin}
              placeholder="60000"
            />
            <TextInput
              label="bis"
              value={salaryMax}
              onChange={setSalaryMax}
              placeholder="70000"
            />
          </div>
          <div className="space-y-1">
            {/* Said out loud: these are hard filters, not keywords. */}
            <FieldLabel>Muss-Kriterien — der Matcher schließt daran aus</FieldLabel>
            <TagInput
              tags={mustHave}
              onChange={setMustHave}
              placeholder="Kriterium hinzufügen…"
            />
          </div>
        </div>

        {error && <p className="text-[13px] text-coral-400">{error}</p>}

        <div className="flex items-center gap-2 border-t border-cockpit-line pt-4">
          <Button tone="primary" onClick={() => void save()} disabled={!canSave}>
            <Check className="h-4 w-4" />
            {busy ? 'Legt an…' : 'Mandat anlegen'}
          </Button>
          <Button onClick={onClose}>
            <X className="h-4 w-4" /> Abbrechen
          </Button>
          {!canSave && !busy && (
            <span className="ml-auto font-mono text-[11px] text-cockpit-faint">
              Titel und Kunde fehlen noch
            </span>
          )}
        </div>
      </div>
    </Modal>
  )
}
