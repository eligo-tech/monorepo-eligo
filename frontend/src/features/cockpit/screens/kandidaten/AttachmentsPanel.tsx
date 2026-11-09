// Everything on file for one candidate — and the files that are read rather
// than only stored: the transcript, and any Zeugnis or Zertifikat.
//
// `data/examples/metadata_quailfication.txt` asks for two things the dossier
// could not hold: the Zeugnisse and Zertifikate a client wants before an
// interview, and the Gesprächstranskript the post-interview data comes from.
// Both are files on a candidate; what separates them is the `kind`.
//
// The transcript is read for the qualification fields — but the result is a
// list of PROPOSALS with their confidence, not a write. A model reading
// hedged speech ("so um die 100") must not put a number into the record over
// a recruiter's signature; confirming is a click, and that click is an
// ordinary edit the receipt can honestly attribute to a person.
//
// A Zeugnis or Zertifikat is read the same way, with one addition: every
// proposal shows the sentence it came from, and the server has already
// dropped any whose sentence is not in the document. The grade decoded from
// Zeugnissprache is an interpretation and is shown and stored as one.

import { locale } from '@/i18n/format'

import { t } from '@/i18n'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Download, FileText, Loader2, Sparkles, UploadCloud } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import { ReaddDeclined, withReaddConfirm } from '../../erasure/readd'
import { buildReferencePatch } from './referenceMerge'
import { type ReadableKind, isReadable, readsAfterUpload } from './attachmentRules'
import type {
  CVExtractionResultDTO,
  CandidateDTO,
  CandidateDocumentDTO,
  CandidateUpdatePayload,
  DocumentKind,
} from '@/api/types'
import { cn } from '@/lib/cn'
import { Button, FieldLabel } from '../../ui/forms'
import { Chip } from '../../ui/primitives'

const KIND_LABEL: Record<DocumentKind, string> = {
  cv: 'CV',
  transkript: t('Transkript'),
  zeugnis: t('Zeugnis'),
  zertifikat: t('Zertifikat'),
  sonstiges: t('Sonstiges'),
}

/** What can be attached from the drop zone, in the order a recruiter needs
 *  them. The transcript has its own button: it is read, not filed. */
const UPLOAD_KINDS = ['zeugnis', 'zertifikat', 'cv', 'sonstiges'] as const

/** Extracted field name → the candidate column it belongs in.
 *
 *  Only these are offered. A field the record cannot hold is dropped rather
 *  than silently sent, which would come back a 422 the recruiter cannot act
 *  on. `expected_salary` is the one rename: the extractor speaks the CV's
 *  vocabulary, the record speaks its own. */
const TO_COLUMN: Record<string, keyof CandidateUpdatePayload> = {
  notice_period: 'notice_period',
  availability: 'availability',
  current_salary: 'current_salary',
  salary_minimum: 'salary_minimum',
  expected_salary: 'salary_expectation',
  motivation: 'motivation',
  skills: 'skills',
  other_processes: 'other_processes',
  interview_availability: 'interview_availability',
  profile_summary: 'profile_summary',
}

const NUMERIC = new Set(['current_salary', 'salary_minimum', 'expected_salary'])

/** "92.000 €" → 92000. Returns null when nothing numeric is in there, so a
 *  stray word never becomes a salary of 0. */
function toAmount(value: string): number | null {
  const digits = value.replace(/[^\d]/g, '')
  return digits ? Number(digits) : null
}

function kb(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${Math.round(bytes / 1024)} KB`
}

function dateDe(iso: string): string {
  return new Date(iso).toLocaleDateString(locale(), {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Europe/Berlin',
  })
}

export function AttachmentsPanel({
  candidateId,
  onCandidateChanged,
}: {
  candidateId: string
  /** The confirmed proposals land on the candidate — the drawer re-reads it. */
  onCandidateChanged?: (updated: CandidateDTO) => void
}) {
  const [docs, setDocs] = useState<CandidateDocumentDTO[] | null>(null)
  const [kind, setKind] = useState<DocumentKind>('zeugnis')
  const [busy, setBusy] = useState(false)
  /** What the drop zone is doing, so it can say so instead of just greying out. */
  const [phase, setPhase] = useState<'upload' | 'read' | null>(null)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [proposals, setProposals] = useState<CVExtractionResultDTO | null>(null)
  /** What the open proposals were read from — decides how they are confirmed. */
  const [source, setSource] = useState<'transkript' | ReadableKind>('transkript')
  const [notice, setNotice] = useState<string | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const fileRef = useRef<HTMLInputElement>(null)
  const transcriptRef = useRef<HTMLInputElement>(null)

  const reload = useCallback(async () => {
    try {
      setDocs(await api.candidateDocuments(candidateId))
    } catch {
      setDocs([])
    }
  }, [candidateId])

  useEffect(() => {
    void reload()
  }, [reload])

  const describe = (e: unknown) =>
    e instanceof ReaddDeclined
      ? e.message
      : e instanceof ApiError
      ? `Fehlgeschlagen (HTTP ${e.status}).`
      : t('Fehlgeschlagen — keine Antwort vom Server.')

  /** Store the file; a Zeugnis or Zertifikat is then read straight away, so
   *  the recruiter sees proposals without hunting for a button. */
  async function attach(file: File) {
    setBusy(true)
    setPhase('upload')
    setError(null)
    setNotice(null)
    let doc: CandidateDocumentDTO | null = null
    try {
      doc = await api.uploadDocument(candidateId, file, kind)
      await reload()
    } catch (e) {
      setError(describe(e))
    }
    setPhase(null)
    setBusy(false)
    if (!doc) return
    if (readsAfterUpload(doc.kind, doc.content_type)) {
      await readReference(doc)
    } else if (isReadable(doc.kind)) {
      setNotice(t('Gespeichert. Fotos und Scans können noch nicht gelesen werden — bitte die Angaben von Hand erfassen.'))
    }
  }

  async function readTranscript(file: File) {
    setBusy(true)
    setError(null)
    setNotice(null)
    setProposals(null)
    try {
      const result = await api.extractTranscript(candidateId, file)
      setSource('transkript')
      setProposals(result)
      // Pre-tick what was read plainly; anything hedged stays unticked so it
      // is a decision, not a default.
      setChosen(
        new Set(
          result.fields
            .filter((f) => !f.needs_review && f.field in TO_COLUMN)
            .map((f) => f.field),
        ),
      )
      await reload()
    } catch (e) {
      setError(describe(e))
    }
    setBusy(false)
  }

  async function readReference(doc: CandidateDocumentDTO) {
    setBusy(true)
    setPhase('read')
    setError(null)
    setNotice(null)
    setProposals(null)
    try {
      const result = await api.readDocument(doc.id)
      setSource(doc.kind as ReadableKind)
      setProposals(result)
      // An interpretation is never a default, whatever its confidence.
      setChosen(
        new Set(
          result.fields
            .filter((f) => !f.needs_review && !f.interpretation)
            .map((f) => f.field),
        ),
      )
    } catch (e) {
      setError(
        // Only the no-text refusal is a scan; any other 422 says what it is.
        e instanceof ApiError && e.status === 422 && e.message.includes('OCR')
          ? t('Dieses Dokument enthält keinen lesbaren Text (Scan oder Foto) — bitte die Angaben von Hand erfassen.')
          : describe(e),
      )
    }
    setPhase(null)
    setBusy(false)
  }

  /** Zeugnis/Zertifikat: merged into the record as it is NOW. The PATCH
   *  replaces whole lists, so the current candidate is read first and the
   *  write carries its version — a change in between is refused, not lost. */
  async function confirmReference(kind: ReadableKind) {
    if (!proposals) return
    setBusy(true)
    setError(null)
    try {
      const current = await api.candidate(candidateId)
      const patch = buildReferencePatch(current, proposals.fields, chosen, kind)
      if (Object.keys(patch).length === 0) {
        setNotice(t('Alles Ausgewählte steht schon im Datensatz.'))
        setProposals(null)
      } else {
        const updated = await withReaddConfirm((override) =>
          api.updateCandidate(candidateId, { ...patch, override_suppression: override || undefined }),
        )
        onCandidateChanged?.(updated)
        setProposals(null)
      }
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? t('Der Datensatz wurde gerade geändert — bitte erneut übernehmen.')
          : describe(e),
      )
    }
    setBusy(false)
  }

  async function confirmChosen() {
    if (!proposals) return
    if (source !== 'transkript') return confirmReference(source)
    const patch: CandidateUpdatePayload = {}
    for (const field of proposals.fields) {
      if (!chosen.has(field.field)) continue
      const column = TO_COLUMN[field.field]
      if (!column) continue
      if (NUMERIC.has(field.field)) {
        const amount = toAmount(field.value)
        if (amount !== null) (patch as Record<string, unknown>)[column] = amount
      } else if (field.field === 'skills') {
        patch.skills = field.value
          .split(/[;,]/)
          .map((x) => x.trim())
          .filter(Boolean)
      } else {
        ;(patch as Record<string, unknown>)[column] = field.value
      }
    }
    if (Object.keys(patch).length === 0) {
      setProposals(null)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const updated = await withReaddConfirm((override) =>
        api.updateCandidate(candidateId, { ...patch, override_suppression: override || undefined }),
      )
      onCandidateChanged?.(updated)
      setProposals(null)
    } catch (e) {
      setError(describe(e))
    }
    setBusy(false)
  }

  const toggle = (field: string) =>
    setChosen((prev) => {
      const next = new Set(prev)
      if (next.has(field)) next.delete(field)
      else next.add(field)
      return next
    })

  return (
    <section className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault()
          if (!busy) setDragging(true)
        }}
        // Leaving for a child (a chip, the text) is not leaving the zone.
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const file = e.dataTransfer.files?.[0]
          if (file && !busy) void attach(file)
        }}
        className={cn(
          'space-y-4 rounded-2xl border-2 border-dashed p-4 transition-colors',
          dragging
            ? 'border-mint-500 bg-mint-800/20'
            : 'border-cockpit-line bg-cockpit-inset/40 hover:border-cockpit-edge',
        )}
      >
        <div>
          <FieldLabel>{t('Art')}</FieldLabel>
          <div role="radiogroup" aria-label={t('Art')} className="flex flex-wrap gap-1.5">
            {UPLOAD_KINDS.map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={kind === value}
                onClick={() => setKind(value)}
                disabled={busy}
                className={cn(
                  'rounded-full border px-3 py-1 font-mono text-[12px] tracking-[0.04em] transition-colors disabled:opacity-50',
                  kind === value
                    ? 'border-mint-500 bg-mint-800/50 text-mint-300'
                    : 'border-cockpit-line text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text',
                )}
              >
                {KIND_LABEL[value]}
              </button>
            ))}
          </div>
        </div>

        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".pdf,.png,.jpg,.jpeg,.txt"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void attach(file)
            e.target.value = ''
          }}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="flex w-full flex-col items-center gap-2 rounded-xl px-4 py-6 text-center transition-colors hover:bg-white/[0.02] disabled:cursor-wait"
        >
          {busy && phase ? (
            <Loader2 className="h-6 w-6 animate-spin text-mint-300" />
          ) : (
            <UploadCloud className={cn('h-6 w-6', dragging ? 'text-mint-300' : 'text-cockpit-faint')} />
          )}
          <span className="text-[14px] text-cockpit-text">
            {phase === 'upload'
              ? t('Wird hochgeladen…')
              : phase === 'read'
              ? t('Wird ausgewertet…')
              : t('Datei hier ablegen oder klicken')}
          </span>
          <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-cockpit-faint">
            {t('PDF, PNG, JPG oder TXT · max. 10 MB')}
          </span>
          {isReadable(kind) && !phase && (
            <span className="text-[12px] text-lav-400">
              {t('Wird danach ausgewertet — Vorschläge mit Beleg, erst nach Ihrer Bestätigung im Datensatz')}
            </span>
          )}
        </button>
      </div>

      <div className="flex justify-end">
        <input
          ref={transcriptRef}
          type="file"
          className="hidden"
          accept=".pdf,.txt"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void readTranscript(file)
            e.target.value = ''
          }}
        />
        <Button
          onClick={() => transcriptRef.current?.click()}
          disabled={busy}
          tone="primary"
          className="whitespace-nowrap"
          title={t('Gesprächsnotiz auswerten — schlägt Felder vor, schreibt nichts')}
        >
          <Sparkles className="h-4 w-4" /> {t('Transkript auswerten')}
        </Button>
      </div>

      {error && <p className="text-[13px] text-coral-400">{error}</p>}
      {notice && <p className="text-[13px] text-cockpit-dim">{notice}</p>}

      {proposals && (
        <div className="space-y-3 rounded-xl border border-lav-600/50 bg-lav-800/25 p-4">
          <p className="font-mono text-[12px] uppercase tracking-[0.08em] text-lav-400">
            {t('Vorschläge aus {document} — nichts gespeichert', { document: proposals.document_name })}
          </p>
          {proposals.fields.length === 0 ? (
            <p className="text-[13px] text-cockpit-dim">
              {source === 'transkript'
                ? t('Aus dem Transkript konnte nichts sicher gelesen werden — bitte die Felder von Hand erfassen. Die Datei ist gespeichert.')
                : t('Aus dem Dokument konnte nichts belegt gelesen werden — bitte die Angaben von Hand erfassen.')}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {proposals.fields.map((f) => {
                const known = source !== 'transkript' || f.field in TO_COLUMN
                return (
                  <li key={f.field} className="flex items-start gap-2.5">
                    <button
                      type="button"
                      disabled={!known}
                      onClick={() => toggle(f.field)}
                      aria-pressed={chosen.has(f.field)}
                      className={cn(
                        'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors',
                        chosen.has(f.field)
                          ? 'border-mint-500 bg-mint-800/60 text-mint-300'
                          : 'border-cockpit-line text-transparent',
                        !known && 'cursor-not-allowed opacity-40',
                      )}
                    >
                      <Check className="h-3 w-3" />
                    </button>
                    <span className="min-w-0 text-[13px] leading-relaxed text-cockpit-dim">
                      <span className="text-cockpit-text">
                        {source === 'transkript' ? f.label : t(f.label)}:
                      </span>{' '}
                      {f.value}
                      {f.interpretation ? (
                        <Chip tone="gold" className="ml-2">
                          {t('Interpretation')}
                        </Chip>
                      ) : (
                        f.needs_review && (
                          <Chip tone="gold" className="ml-2">
                            unsicher {Math.round(f.confidence * 100)}%
                          </Chip>
                        )
                      )}
                      {f.evidence && (
                        <span className="mt-0.5 block text-[12px] italic text-cockpit-faint">
                          „{f.evidence}“
                        </span>
                      )}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
          <div className="flex items-center gap-2">
            <Button onClick={() => setProposals(null)}>{t('Verwerfen')}</Button>
            {proposals.fields.length > 0 && (
              <Button tone="primary" onClick={confirmChosen} disabled={busy}>
                {chosen.size > 0
                  ? t('{n} übernehmen', { n: chosen.size })
                  : t('Nichts ausgewählt')}
              </Button>
            )}
          </div>
        </div>
      )}

      {docs === null ? (
        <p className="text-[13px] italic text-cockpit-faint">{t('Dateien werden geladen…')}</p>
      ) : docs.length === 0 ? (
        <p className="text-[13px] italic text-cockpit-faint">
          {t('Keine Dateien hinterlegt — Zeugnisse und Zertifikate gehören hierher.')}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {docs.map((doc) => (
            <li
              key={doc.id}
              className="flex items-center gap-3 border-b border-cockpit-line pb-1.5"
            >
              <FileText className="h-4 w-4 shrink-0 text-cockpit-faint" />
              <span className="min-w-0 flex-1 truncate text-[14px] text-cockpit-text">
                {doc.filename}
              </span>
              <Chip>{KIND_LABEL[doc.kind] ?? doc.kind}</Chip>
              {isReadable(doc.kind) && (
                <button
                  type="button"
                  onClick={() => void readReference(doc)}
                  disabled={busy}
                  title={t('Dokument auswerten — schlägt Angaben mit Beleg vor, schreibt nichts')}
                  className="flex shrink-0 items-center gap-1 text-[12px] text-cockpit-faint transition-colors hover:text-lav-400 disabled:opacity-40"
                >
                  <Sparkles className="h-3.5 w-3.5" /> {t('Auswerten')}
                </button>
              )}
              <span className="shrink-0 font-mono text-[12px] text-cockpit-faint">
                {kb(doc.byte_size)} · {dateDe(doc.created_at)}
              </span>
              <a
                href={api.documentUrl(doc.id)}
                target="_blank"
                rel="noreferrer"
                title={t('Öffnen')}
                className="shrink-0 text-cockpit-faint transition-colors hover:text-mint-300"
              >
                <Download className="h-4 w-4" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
