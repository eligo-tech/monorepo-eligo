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

import { t } from '@/i18n'

import { useMemo, useState } from 'react'
import { Building2, Check, Link2, Plus, UserRound, X } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { CompanyDTO, JobSpecProposalDTO, ManagerDTO } from '@/api/types'
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

/** The typed name, when it is not one of the rows: what would be created.
 *
 *  Pressing the button has to do what the form looks like it will do. A name
 *  typed and left in the box is an answer; requiring a click on a suggestion
 *  row to "really" mean it is a trap, and it is the one people walked into. */
export function typedName<T>(rows: T[], query: string, nameOf: (row: T) => string): string {
  const text = query.trim()
  if (text.length < 2) return ''
  const exists = rows.some(
    (row) => nameOf(row).trim().toLowerCase() === text.toLowerCase(),
  )
  return exists ? '' : text
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
  query,
  onQuery,
  icon: Icon,
}: {
  rows: T[]
  label: string
  placeholder: string
  nameOf: (row: T) => string
  hintOf?: (row: T) => string | null
  value: string | null
  onPick: (id: string | null) => void
  /** A name the reader confirmed by clicking "neu anlegen". */
  draft: string
  onDraft: (text: string) => void
  /** The typed text, OWNED BY THE PARENT.
   *
   *  It used to live in here, and that was a bug people hit immediately:
   *  typing "New Firm" and pressing "Mandat anlegen" did nothing, because
   *  the only state the form could see was set by CLICKING the "neu
   *  anlegen" row. The button stayed disabled under a hint that said the
   *  client was missing while the reader was looking at it on screen. */
  query: string
  onQuery: (text: string) => void
  icon: typeof Building2
}) {
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
              onQuery('')
            }}
            className="shrink-0 text-cockpit-faint transition-colors hover:text-coral-300"
            title={t('ändern')}
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
            <span className="ml-2 font-mono text-[11px] text-gold-300">{t('wird neu angelegt')}</span>
          </span>
          <button
            type="button"
            onClick={() => {
              onDraft('')
              onQuery('')
            }}
            className="shrink-0 text-cockpit-faint transition-colors hover:text-coral-300"
            title={t('verwerfen')}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-1">
      <TextInput label={label} value={query} onChange={onQuery} placeholder={placeholder} />
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
              {t('„{name}“ neu anlegen', { name: query.trim() })}
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
  const [companyQuery, setCompanyQuery] = useState('')
  const [managerId, setManagerId] = useState<string | null>(null)
  const [managerDraft, setManagerDraft] = useState('')
  const [managerQuery, setManagerQuery] = useState('')
  const [managerRole, setManagerRole] = useState('')
  const [managerEmail, setManagerEmail] = useState('')
  const [location, setLocation] = useState('')
  const [salaryMin, setSalaryMin] = useState('')
  const [salaryMax, setSalaryMax] = useState('')
  const [mustHave, setMustHave] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // ELI-6: the advert, and what reading it proposed.
  const [advert, setAdvert] = useState('')
  const [reading, setReading] = useState(false)
  const [read, setRead] = useState<JobSpecProposalDTO | null>(null)
  const [readError, setReadError] = useState<string | null>(null)

  /** Read the advert and fill the form in. Fills BLANKS only.
   *
   *  Anything already typed is the recruiter's, and a parser that overwrites
   *  it teaches people not to paste the link until they have finished —
   *  which is the opposite of the point. */
  async function readAdvert() {
    const value = advert.trim()
    if (!value) return
    setReading(true)
    setReadError(null)
    try {
      const looksLikeUrl = /^https?:\/\//i.test(value)
      const spec = await api.parseJobSpec(looksLikeUrl ? { url: value } : { text: value })
      setRead(spec)
      if (spec.title && !title.trim()) setTitle(spec.title.value)
      if (spec.location && !location.trim()) setLocation(spec.location.value)
      if (spec.salary_min && !salaryMin.trim()) setSalaryMin(spec.salary_min.value)
      if (spec.salary_max && !salaryMax.trim()) setSalaryMax(spec.salary_max.value)
      // Muss-Kriterien are hard filters — they exclude people — so they are
      // offered as chips to tick, never filled in. See `proposedSkills`.
    } catch (e) {
      setReadError(
        e instanceof ApiError && e.status === 422
          ? t('Diese Anzeige ließ sich nicht lesen — bitte den Text der Anzeige einfügen.')
          : t('Die Anzeige konnte nicht gelesen werden.'),
      )
    }
    setReading(false)
  }

  /** What the advert suggested as required, minus what is already ticked. */
  const proposedSkills = (read?.must_have_skills ?? [])
    .map((s) => s.value)
    .filter((s) => !mustHave.includes(s))

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

  // What the form WILL create: a confirmed draft, or simply what was typed.
  const newClient =
    companyDraft.trim() || typedName(companies ?? [], companyQuery, (c) => c.name)
  const newContact =
    managerDraft.trim() || typedName(managers ?? [], managerQuery, (m) => m.full_name)

  const hasClient = Boolean(companyId || newClient)
  const hasTitle = title.trim().length > 1
  const canSave = hasTitle && hasClient && !busy
  // Name only what is actually missing. The old hint said "Titel und Kunde
  // fehlen noch" with the title filled in and the client name on screen,
  // which is how a form teaches people to distrust it.
  const missing = [!hasTitle && t('ein Job-Titel'), !hasClient && t('ein Kunde')].filter(
    Boolean,
  ) as string[]

  async function save() {
    if (!canSave) return
    setBusy(true)
    setError(null)
    try {
      let client = companyId
      if (!client && newClient) {
        client = (await api.createCompany({ name: newClient })).id
      }

      let contact = managerId
      if (!contact && newContact && client) {
        contact = (
          await api.createManager({
            company_id: client,
            full_name: newContact,
            role_title: managerRole.trim() || null,
            email: managerEmail.trim() || null,
            // Provenance on the way in: the Art. 14 flow reads this later,
            // and a contact with no recorded origin cannot be assessed for
            // it afterwards.
            source: 'self_reported',
            source_detail: t('beim Anlegen des Mandats „{title}“ erfasst', {
              title: title.trim(),
            }),
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
          ? `${t('Nicht angelegt (HTTP {status}).', { status: e.status })} ${
              e.status === 422 ? t('Bitte Eingaben prüfen.') : ''
            }`
          : t('Nicht angelegt — bitte erneut versuchen.'),
      )
      setBusy(false)
    }
  }

  return (
    <Modal onClose={onClose} className="max-w-3xl">
      <div className="flex items-center gap-3 border-b border-cockpit-line px-7 py-4">
        <Label>{t('Neues Mandat')}</Label>
        <span className="ml-auto">
          <CloseButton onClose={onClose} />
        </span>
      </div>
      <div className="space-y-5 overflow-y-auto px-7 py-6">
        <p className="text-[13px] leading-relaxed text-cockpit-dim">
          {t('Kunde, Job und Ansprechpartner in einem Schritt. Nur der Job-Titel ist nötig — Ort, Band und Muss-Kriterien lassen sich im Mandat jederzeit nachtragen.')}
        </p>

        {/* ELI-6. Above the title because it fills the title in: a tool
            offered after the typing has started is a tool nobody uses. */}
        <div className="rounded-xl border border-cockpit-line bg-cockpit-inset p-4">
          <FieldLabel>{t('Aus Stellenanzeige übernehmen')}</FieldLabel>
          <div className="mt-2 flex flex-wrap gap-2">
            <input
              value={advert}
              onChange={(e) => setAdvert(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void readAdvert()
                }
              }}
              placeholder={t('Link zur Anzeige — oder den Anzeigentext einfügen')}
              className="min-w-[260px] flex-1 rounded-lg border border-cockpit-line bg-cockpit-bg px-3 py-2 text-[13px] text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none"
            />
            <Button onClick={() => void readAdvert()} disabled={reading || !advert.trim()}>
              <Link2 className="h-4 w-4" />
              {reading ? t('Liest…') : t('Anzeige lesen')}
            </Button>
          </div>
          <p className="mt-2 text-[12px] leading-relaxed text-cockpit-faint">
            {t('Füllt nur leere Felder — Getipptes bleibt stehen. Muss-Kriterien schlagen wir vor, setzen sie aber nicht: sie schließen Kandidaten aus.')}
          </p>
          {readError && <p className="mt-2 text-[13px] text-coral-400">{readError}</p>}
          {read && !readError && (
            <p className="mt-2 text-[13px] text-mint-300">
              {t('Gelesen — bitte prüfen, die Anzeige ist die Quelle, nicht die Wahrheit.')}
            </p>
          )}
          {proposedSkills.length > 0 && (
            <div className="mt-3">
              <p className="font-mono text-[11px] uppercase tracking-wide text-cockpit-faint">
                {t('Aus der Anzeige — antippen zum Übernehmen')}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {proposedSkills.map((skill) => (
                  <button
                    key={skill}
                    type="button"
                    onClick={() => setMustHave((rows) => [...rows, skill])}
                    className="rounded-full border border-dashed border-cockpit-edge px-2.5 py-1 text-[12px] text-cockpit-dim transition-colors hover:border-mint-600 hover:text-mint-300"
                  >
                    <Plus className="mr-1 inline h-3 w-3" />
                    {skill}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <TextInput
          label={t('Job-Titel')}
          value={title}
          onChange={setTitle}
          placeholder="IT-Administrator produktionsnahe IT / OT (m/w/d)"
        />

        <Picker
          rows={companies ?? []}
          label={t('Kunde')}
          placeholder={t('Firma suchen oder neuen Namen eingeben…')}
          nameOf={(c) => c.name}
          value={companyId}
          onPick={(id) => {
            setCompanyId(id)
            setManagerId(null)
            setManagerDraft('')
          }}
          draft={companyDraft}
          onDraft={setCompanyDraft}
          query={companyQuery}
          onQuery={setCompanyQuery}
          icon={Building2}
        />

        {hasClient && (
          <>
            <Picker
              rows={managers ?? []}
              label={t('Ansprechpartner (optional)')}
              placeholder={
                companyId
                  ? t('Kontakt suchen oder neuen Namen eingeben…')
                  : t('Name des Ansprechpartners…')
              }
              nameOf={(m) => m.full_name}
              hintOf={(m) => m.role_title ?? null}
              value={managerId}
              onPick={setManagerId}
              draft={managerDraft}
              onDraft={setManagerDraft}
              query={managerQuery}
              onQuery={setManagerQuery}
              icon={UserRound}
            />
            {newContact && (
              <div className="grid gap-3 sm:grid-cols-2">
                <TextInput
                  label={t('Rolle')}
                  value={managerRole}
                  onChange={setManagerRole}
                  placeholder="Head of IT"
                />
                <TextInput
                  label={t('E-Mail')}
                  value={managerEmail}
                  onChange={setManagerEmail}
                  placeholder={t('optional')}
                />
              </div>
            )}
          </>
        )}

        <div className="space-y-3 border-t border-cockpit-line pt-4">
          <Label>{t('Suchprofil · später ergänzbar')}</Label>
          <div className="grid gap-3 sm:grid-cols-3">
            <TextInput
              label={t('Ort')}
              value={location}
              onChange={setLocation}
              placeholder="Dillenburg"
            />
            <TextInput
              label={t('Band von')}
              value={salaryMin}
              onChange={setSalaryMin}
              placeholder="60000"
            />
            <TextInput
              label={t('bis')}
              value={salaryMax}
              onChange={setSalaryMax}
              placeholder="70000"
            />
          </div>
          <div className="space-y-1">
            {/* Said out loud: these are hard filters, not keywords. */}
            <FieldLabel>{t('Muss-Kriterien — der Matcher schließt daran aus')}</FieldLabel>
            <TagInput
              tags={mustHave}
              onChange={setMustHave}
              placeholder={t('Kriterium hinzufügen…')}
            />
          </div>
        </div>

        {error && <p className="text-[13px] text-coral-400">{error}</p>}

        <div className="flex items-center gap-2 border-t border-cockpit-line pt-4">
          <Button tone="primary" onClick={() => void save()} disabled={!canSave}>
            <Check className="h-4 w-4" />
            {busy ? t('Legt an…') : t('Mandat anlegen')}
          </Button>
          <Button onClick={onClose}>
            <X className="h-4 w-4" /> {t('Abbrechen')}
          </Button>
          {missing.length > 0 && !busy && (
            <span className="ml-auto font-mono text-[11px] text-cockpit-faint">
              {t('Es fehlt noch')} {missing.join(t(' und '))}
            </span>
          )}
        </div>
      </div>
    </Modal>
  )
}
