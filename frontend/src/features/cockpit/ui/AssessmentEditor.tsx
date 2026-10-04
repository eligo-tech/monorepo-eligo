// The Kandidatenauswertung, written after the Qualifikationsgespräch — the
// whole document, on the page where it is read.
//
// It was readable and not writable: `data/examples/KandidatenInfo.txt` could
// be imported by a script, the cockpit rendered 8/10 with Stärken and
// Risiken, and a recruiter who had just put the phone down had no way to
// record the same thing for the next candidate. The endpoint existed; the
// form did not.
//
// The document has four sections and they do NOT all belong to the same
// row, so the form says which is which and writes to both:
//
//   A · C · D  → the ASSESSMENT, keyed on the application. The same person
//                against another Muss-Profil is a different fit, a different
//                risk list and a different text for the client.
//   B          → the CANDIDATE's own columns. Kündigungsfrist, Gehalt,
//                Wechselmotivation and the rest describe the person and hold
//                across every mandate; a per-application copy would be three
//                answers to one question.
//
// Both halves save together, because that is how the document is written —
// in one sitting, from one conversation.
//
// A is a full replacement, not a patch, and the server says so too: a
// recruiter re-reads the whole evaluation after a round, and a half-updated
// verdict (new risks, old Kurzfazit) is worse than no verdict at all. B is
// a PATCH: those columns have other sources (CV extraction, the ATS import)
// and blanking one here because this form did not ask would lose it.

import { useState } from 'react'
import { ClipboardPaste, Save, X } from 'lucide-react'

import { api } from '@/api/client'
import type { CandidateUpdatePayload } from '@/api/types'
import { Button } from './forms'
import type { CandidateAssessment, CandidateProfile, ProcessCard } from '../data/types'

/** One line per entry: the way these lists are actually written down. */
const toLines = (values: string[] | undefined) => (values ?? []).join('\n')
const fromLines = (text: string) =>
  text
    .split('\n')
    .map((line) => line.replace(/^[-•*]\s*/, '').trim())
    .filter(Boolean)

const toCommas = (values: string[] | undefined) => (values ?? []).join(', ')
const fromCommas = (text: string) =>
  text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)

/** "92000", "92.000 €", "92k" → 92000. Empty → null, nonsense → undefined,
 *  which is the difference between "clear it" and "do not touch it". */
function toAmount(text: string): number | null | undefined {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const digits = trimmed.replace(/[^\d]/g, '')
  if (digits === '') return undefined
  const value = Number(digits)
  return /k$/i.test(trimmed) && value < 1000 ? value * 1000 : value
}

const asText = (value: number | null | undefined) =>
  value === null || value === undefined ? '' : String(value)

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block space-y-1">
      <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-cockpit-faint">
        {label}
        {hint && <span className="ml-2 normal-case tracking-normal">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

function Half({
  tag,
  title,
  note,
  children,
}: {
  tag: string
  title: string
  note: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-4 border-t border-cockpit-line pt-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          {tag}
        </span>
        <span className="text-[14px] font-semibold text-cockpit-text">{title}</span>
        <span className="font-mono text-[11.5px] text-cockpit-faint">{note}</span>
      </div>
      {children}
    </section>
  )
}

const BOX =
  'w-full rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 text-[13.5px] leading-relaxed text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none'

export function AssessmentEditor({
  card,
  onClose,
  onSaved,
}: {
  card: ProcessCard
  onClose: () => void
  onSaved?: () => void
}) {
  const a: CandidateAssessment | undefined = card.assessment
  const p: CandidateProfile | undefined = card.profile

  // A · C · D — the fit, keyed on this application.
  const [score, setScore] = useState(a?.fitScore != null ? String(a.fitScore) : '')
  const [verdict, setVerdict] = useState(a?.verdict ?? '')
  const [strengths, setStrengths] = useState(toLines(a?.strengths))
  const [risks, setRisks] = useState(toLines(a?.risks))
  const [clientSummary, setClientSummary] = useState(a?.clientSummary ?? '')
  const [technologies, setTechnologies] = useState(toCommas(a?.technologies))
  const [basis, setBasis] = useState(a?.basis ?? '')

  // B — the person. Saved onto the candidate, not onto this mandate.
  const [summary, setSummary] = useState(p?.summary ?? '')
  const [focusAreas, setFocusAreas] = useState(toCommas(p?.focusAreas))
  const [technical, setTechnical] = useState(p?.technicalProfile ?? '')
  const [noticePeriod, setNoticePeriod] = useState(p?.noticePeriod ?? '')
  const [salaryMin, setSalaryMin] = useState(asText(p?.salaryMinimum))
  const [salaryWish, setSalaryWish] = useState(asText(p?.salaryExpectation))
  const [salaryNow, setSalaryNow] = useState(asText(p?.currentSalary))
  const [motivation, setMotivation] = useState(p?.motivation ?? '')
  const [education, setEducation] = useState(toLines(p?.education))
  const [interviews, setInterviews] = useState(p?.interviewAvailability ?? '')
  const [otherNotes, setOtherNotes] = useState(p?.otherNotes ?? '')
  const [otherProcesses, setOtherProcesses] = useState(p?.otherProcesses ?? '')
  const [otherCompanies, setOtherCompanies] = useState(toCommas(p?.otherProcessCompanies))

  const [paste, setPaste] = useState('')
  const [pasteOpen, setPasteOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  /** Read a pasted document into the fields. Fills, never saves — what the
   *  parser understood is shown to the person who wrote the words before
   *  any of it reaches the record. */
  async function readDocument() {
    if (!paste.trim()) return
    setBusy(true)
    setError(null)
    try {
      const parsed = await api.parseAuswertung(paste)
      const next = parsed.assessment
      const prof = parsed.profile
      const filled: string[] = []
      const set = <T,>(
        value: T | null | undefined,
        apply: (value: T) => void,
        label: string,
      ) => {
        // An absent section leaves the field alone: pasting half a document
        // must not wipe what is already there.
        if (value === null || value === undefined) return
        if (Array.isArray(value) && value.length === 0) return
        apply(value)
        filled.push(label)
      }
      set(next.fit_score, (v) => setScore(String(v)), 'Passung')
      set(next.verdict, setVerdict, 'Kurzfazit')
      set(next.strengths, (v) => setStrengths(v.join('\n')), 'Stärken')
      set(next.risks, (v) => setRisks(v.join('\n')), 'Risiken')
      set(next.client_summary, setClientSummary, 'Kundentext')
      set(next.technologies, (v) => setTechnologies(v.join(', ')), 'Technologien')
      set(next.basis, setBasis, 'Grundlage')
      set(prof.profile_summary, setSummary, 'Profil')
      set(prof.focus_areas, (v) => setFocusAreas(v.join(', ')), 'Schwerpunkte')
      set(prof.technical_profile, setTechnical, 'Know-how')
      set(prof.notice_period, setNoticePeriod, 'Kündigungsfrist')
      set(prof.salary_minimum, (v) => setSalaryMin(String(v)), 'Gehalt')
      set(prof.salary_expectation, (v) => setSalaryWish(String(v)), 'Wunschgehalt')
      set(prof.current_salary, (v) => setSalaryNow(String(v)), 'aktuelles Gehalt')
      set(prof.motivation, setMotivation, 'Wechselmotivation')
      set(prof.education, (v) => setEducation(v.join('\n')), 'Abschluss')
      set(prof.interview_availability, setInterviews, 'Interview-Verfügbarkeit')
      set(prof.other_notes, setOtherNotes, 'weitere Punkte')
      setNote(
        filled.length > 0
          ? `Übernommen: ${filled.join(', ')} — bitte prüfen und speichern.`
          : 'Nichts erkannt — das Dokument folgt der Vorlage A/B/C/D nicht. Felder bleiben unverändert.',
      )
      if (filled.length > 0) setPasteOpen(false)
    } catch {
      setError('Konnte nicht gelesen werden — bitte die Felder von Hand füllen.')
    } finally {
      setBusy(false)
    }
  }

  /** Only what this form asked about, and only when it changed. */
  function profilePatch(): CandidateUpdatePayload {
    const patch: CandidateUpdatePayload = {}
    const text = (value: string, was: string | null | undefined, key: keyof CandidateUpdatePayload) => {
      const next = value.trim() || null
      if (next !== (was ?? null)) Object.assign(patch, { [key]: next })
    }
    const list = (value: string[], was: string[] | undefined, key: keyof CandidateUpdatePayload) => {
      if (JSON.stringify(value) !== JSON.stringify(was ?? [])) {
        Object.assign(patch, { [key]: value })
      }
    }
    const amount = (value: string, was: number | null | undefined, key: keyof CandidateUpdatePayload) => {
      const next = toAmount(value)
      if (next !== undefined && next !== (was ?? null)) Object.assign(patch, { [key]: next })
    }
    text(summary, p?.summary, 'profile_summary')
    text(technical, p?.technicalProfile, 'technical_profile')
    text(noticePeriod, p?.noticePeriod, 'notice_period')
    text(motivation, p?.motivation, 'motivation')
    text(interviews, p?.interviewAvailability, 'interview_availability')
    text(otherNotes, p?.otherNotes, 'other_notes')
    text(otherProcesses, p?.otherProcesses, 'other_processes')
    list(fromCommas(focusAreas), p?.focusAreas, 'focus_areas')
    list(fromLines(education), p?.education, 'education')
    list(fromCommas(otherCompanies), p?.otherProcessCompanies, 'other_process_companies')
    amount(salaryMin, p?.salaryMinimum, 'salary_minimum')
    amount(salaryWish, p?.salaryExpectation, 'salary_expectation')
    amount(salaryNow, p?.currentSalary, 'current_salary')
    return patch
  }

  async function save() {
    const value = score.trim() === '' ? null : Number(score)
    if (value !== null && (Number.isNaN(value) || value < 0 || value > 10)) {
      return setError('Die Passung ist eine Zahl von 0 bis 10.')
    }
    setBusy(true)
    setError(null)
    try {
      await api.setAssessment(card.id, {
        fit_score: value,
        verdict: verdict.trim() || null,
        strengths: fromLines(strengths),
        risks: fromLines(risks),
        client_summary: clientSummary.trim() || null,
        technologies: fromCommas(technologies),
        basis: basis.trim() || null,
      })
      const patch = profilePatch()
      if (card.candidateId && Object.keys(patch).length > 0) {
        await api.updateCandidate(card.candidateId, patch)
      }
      onSaved?.()
      onClose()
    } catch {
      setError('Nicht gespeichert — bitte erneut versuchen.')
      setBusy(false)
    }
  }

  return (
    <div className="mt-6 space-y-5 border-t border-cockpit-line pt-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
          Kandidatenauswertung · {card.candidateName}
        </span>
        <button
          type="button"
          onClick={() => setPasteOpen((open) => !open)}
          className="ml-auto flex items-center gap-1.5 font-mono text-[12px] text-cockpit-faint transition-colors hover:text-mint-300"
        >
          <ClipboardPaste className="h-3.5 w-3.5" />
          {pasteOpen ? 'Einfügen schließen' : 'Dokument einfügen'}
        </button>
      </div>

      {pasteOpen && (
        <div className="space-y-2 rounded-xl border border-dashed border-cockpit-line p-4">
          <Field
            label="Kandidatenauswertung einfügen"
            hint="Abschnitte A/B/C/D — füllt die Felder, speichert nichts"
          >
            <textarea
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
              rows={6}
              placeholder={'A. Passungsbewertung zur Position\nGesamtbewertung: 8 / 10\n…'}
              className={`${BOX} font-mono text-[12.5px]`}
            />
          </Field>
          <Button onClick={() => void readDocument()} disabled={busy || !paste.trim()}>
            <ClipboardPaste className="h-4 w-4" />
            {busy ? 'Liest…' : 'Felder übernehmen'}
          </Button>
        </div>
      )}

      {note && <p className="text-[12.5px] text-mint-300">{note}</p>}

      <Half
        tag="A · C · D"
        title="Passung zu diesem Mandat"
        note={`${card.mandateRef} · gilt nur für dieses Mandat`}
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-4">
            <div className="grid grid-cols-[6rem_1fr] gap-3">
              <Field label="Passung" hint="0–10">
                <input
                  value={score}
                  onChange={(e) => setScore(e.target.value)}
                  inputMode="numeric"
                  placeholder="8"
                  className={`${BOX} font-mono`}
                />
              </Field>
              <Field label="Grundlage" hint="worauf beruht das Urteil">
                <input
                  value={basis}
                  onChange={(e) => setBasis(e.target.value)}
                  placeholder="CV (Kurzversion) + Gesprächstranskript 18.09.2026"
                  className={BOX}
                />
              </Field>
            </div>

            <Field label="Kurzfazit" hint="erster Absatz ist das Fazit, weitere sind die Begründung">
              <textarea
                value={verdict}
                onChange={(e) => setVerdict(e.target.value)}
                rows={5}
                placeholder="Sehr passgenauer Senior-Kandidat — deckt das Muss-Profil vollständig ab …"
                className={BOX}
              />
            </Field>

            <Field label="Relevante Technologien" hint="mit Komma getrennt">
              <input
                value={technologies}
                onChange={(e) => setTechnologies(e.target.value)}
                placeholder="Java, Jakarta EE, WildFly, JPA/Hibernate"
                className={BOX}
              />
            </Field>
          </div>

          <div className="space-y-4">
            <Field label="Stärken" hint="eine pro Zeile">
              <textarea
                value={strengths}
                onChange={(e) => setStrengths(e.target.value)}
                rows={5}
                placeholder={'Deckt das Muss vollständig ab\nArchitektur-Verantwortung real gelebt'}
                className={BOX}
              />
            </Field>
            <Field label="Lücken / Risiken" hint="eine pro Zeile">
              <textarea
                value={risks}
                onChange={(e) => setRisks(e.target.value)}
                rows={5}
                placeholder={'Gehalt am oberen Rand\nKündigungsfrist 3 Monate'}
                className={BOX}
              />
            </Field>
          </div>
        </div>

        <Field label="Text für den Kunden" hint="geht so in die Vorstellung">
          <textarea
            value={clientSummary}
            onChange={(e) => setClientSummary(e.target.value)}
            rows={4}
            placeholder="Der Kandidat ist ein Senior Software Entwickler und Architekt mit …"
            className={BOX}
          />
        </Field>
      </Half>

      <Half
        tag="B"
        title="Gesprächszusammenfassung"
        note="gilt für den Kandidaten — auf jedem Mandat dieselbe"
      >
        <Field label="Zusammenfassung des Profils">
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={4}
            placeholder="Senior Software Entwickler & Architekt mit über 20 Jahren Erfahrung …"
            className={BOX}
          />
        </Field>

        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Schwerpunkte" hint="mit Komma getrennt">
            <input
              value={focusAreas}
              onChange={(e) => setFocusAreas(e.target.value)}
              placeholder="Java-Enterprise-Architektur, WildFly/JBoss, Legacy-Modernisierung"
              className={BOX}
            />
          </Field>
          <Field label="Kündigungsfrist / Verfügbarkeit">
            <input
              value={noticePeriod}
              onChange={(e) => setNoticePeriod(e.target.value)}
              placeholder="3 Monate zum Monatsende → Start ~Jahresanfang"
              className={BOX}
            />
          </Field>
        </div>

        <Field
          label="Technisches Know-how"
          hint="Fließtext; die Muss-Kriterien werden aus den Skills gelesen, nicht hier"
        >
          <textarea
            value={technical}
            onChange={(e) => setTechnical(e.target.value)}
            rows={3}
            placeholder="Java (Experte), Jakarta EE, WildFly, JBoss; Hibernate, JPA …"
            className={BOX}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Minimum" hint="€">
            <input
              value={salaryMin}
              onChange={(e) => setSalaryMin(e.target.value)}
              inputMode="numeric"
              placeholder="92000"
              className={`${BOX} font-mono`}
            />
          </Field>
          <Field label="Wunsch" hint="€">
            <input
              value={salaryWish}
              onChange={(e) => setSalaryWish(e.target.value)}
              inputMode="numeric"
              placeholder="100000"
              className={`${BOX} font-mono`}
            />
          </Field>
          <Field label="Aktuell" hint="€">
            <input
              value={salaryNow}
              onChange={(e) => setSalaryNow(e.target.value)}
              inputMode="numeric"
              placeholder="105000"
              className={`${BOX} font-mono`}
            />
          </Field>
        </div>

        <Field label="Wechselmotivation">
          <textarea
            value={motivation}
            onChange={(e) => setMotivation(e.target.value)}
            rows={3}
            placeholder="Sucht kurze Wege, Gestaltungsspielraum …"
            className={BOX}
          />
        </Field>

        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Höchster Abschluss" hint="einer pro Zeile">
            <textarea
              value={education}
              onChange={(e) => setEducation(e.target.value)}
              rows={2}
              placeholder="Fachinformatiker Anwendungsentwicklung (IHK)"
              className={BOX}
            />
          </Field>
          <Field label="Verfügbarkeit für Interviews">
            <textarea
              value={interviews}
              onChange={(e) => setInterviews(e.target.value)}
              rows={2}
              placeholder="Mittwoch/Donnerstag ab ca. 11–12 Uhr"
              className={BOX}
            />
          </Field>
        </div>

        <Field label="Weitere relevante Punkte" hint="eine pro Zeile, freier Text">
          <textarea
            value={otherNotes}
            onChange={(e) => setOtherNotes(e.target.value)}
            rows={5}
            placeholder={
              'Aktuelle Rolle / Arbeitgeber: …\nRelevante Projekterfahrung: …\nSprachkenntnisse: …'
            }
            className={BOX}
          />
        </Field>

        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Andere Prozesse">
            <textarea
              value={otherProcesses}
              onChange={(e) => setOtherProcesses(e.target.value)}
              rows={2}
              placeholder="Führt parallel mehrere Prozesse / Freelance-Optionen"
              className={BOX}
            />
          </Field>
          {/* Names, not prose: three candidates naming the same company is a
              lead, and a sentence cannot be counted across the pool. */}
          <Field label="… bei welchen Firmen" hint="mit Komma getrennt">
            <input
              value={otherCompanies}
              onChange={(e) => setOtherCompanies(e.target.value)}
              placeholder="Trade Republic, Celonis"
              className={BOX}
            />
          </Field>
        </div>
      </Half>

      {error && <p className="text-[12.5px] text-coral-400">{error}</p>}

      <div className="flex items-center gap-2">
        <Button tone="primary" onClick={() => void save()} disabled={busy}>
          <Save className="h-4 w-4" /> {busy ? 'Speichert…' : 'Auswertung speichern'}
        </Button>
        <Button onClick={onClose}>
          <X className="h-4 w-4" /> Abbrechen
        </Button>
      </div>
    </div>
  )
}
