// Upload a PDF CV → extract fields (preview, writes nothing) → save as a candidate.
//
// The preview step IS the verification gate: fields below the confidence threshold
// are marked and withheld, and the laufwise trace at the bottom shows each check as
// a predicate over the real extraction result rather than model prose.

import { useRef, useState } from 'react'
import { AlertTriangle, Check, FileText, Loader2, UploadCloud } from 'lucide-react'
import { api } from '@/api/client'
import type { CVExtractionResultDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Button, CloseButton, Modal } from '../../ui/forms'

interface Props {
  onClose: () => void
  onCreated: () => void
}

function ConfidenceBar({ value, review }: { value: number; review: boolean }) {
  const pct = Math.round(value * 100)
  const tone = review ? 'bg-gold-400' : value >= 0.85 ? 'bg-mint-400' : 'bg-mint-600'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-[#26281f]">
        <div className={cn('h-full rounded-full', tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 font-mono text-[12px] text-cockpit-faint">{pct}%</span>
    </div>
  )
}

export function CvUploadModal({ onClose, onCreated }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<CVExtractionResultDTO | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  async function handleFile(f: File) {
    setFile(f)
    setError(null)
    setResult(null)
    setLoading(true)
    try {
      setResult(await api.extractCv(f, false)) // preview — writes nothing
    } catch (e) {
      setError((e as Error).message || 'Extraktion fehlgeschlagen')
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    if (!file) return
    setSaving(true)
    setError(null)
    try {
      await api.extractCv(file, true) // persist — creates the candidate
      onCreated()
      onClose()
    } catch (e) {
      setError((e as Error).message || 'Speichern fehlgeschlagen')
      setSaving(false)
    }
  }

  const accepted = result?.fields.filter((f) => !f.needs_review).length ?? 0
  const scanned = result !== null && result.text_chars === 0

  return (
    <Modal onClose={onClose} className="max-w-3xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 border-b border-cockpit-line px-6 py-4">
        <div>
          <h2 className="text-[19px] font-semibold tracking-tight text-cockpit-text">
            Kandidat aus CV
          </h2>
          <p className="mt-0.5 text-[13px] text-cockpit-dim">
            PDF hochladen — Felder werden extrahiert und geprüft.
          </p>
        </div>
        <CloseButton onClose={onClose} />
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        {/* Dropzone */}
        {!result && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              const f = e.dataTransfer.files?.[0]
              if (f) handleFile(f)
            }}
            className={cn(
              'flex w-full flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-6 py-14 transition-colors',
              dragging
                ? 'border-mint-500 bg-mint-800/20'
                : 'border-cockpit-line hover:border-cockpit-edge hover:bg-white/[0.02]',
            )}
          >
            {loading ? (
              <Loader2 className="h-8 w-8 animate-spin text-mint-400" />
            ) : (
              <UploadCloud className="h-8 w-8 text-mint-400" />
            )}
            <div className="text-center">
              <div className="font-semibold text-cockpit-text">
                {loading ? 'Wird extrahiert…' : 'PDF hierher ziehen oder klicken'}
              </div>
              <div className="mt-0.5 font-mono text-[12px] text-cockpit-faint">
                Nur PDF · max. 10 MB
              </div>
            </div>
          </button>
        )}

        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleFile(f)
          }}
        />

        {error && (
          <div className="mt-4 rounded-xl border border-coral-600 bg-coral-800/25 px-4 py-3 text-[14px] text-coral-300">
            {error}
          </div>
        )}

        {/* Results */}
        {result && (
          <div>
            <div className="flex flex-wrap items-center gap-2 text-[14px] text-cockpit-dim">
              <FileText className="h-4 w-4 shrink-0 text-cockpit-faint" />
              <span className="font-medium text-cockpit-text">{result.document_name}</span>
              <span className="font-mono text-[13px] text-cockpit-faint">
                · {accepted} von {result.fields.length} Feldern übernommen
              </span>
            </div>

            {scanned && (
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-gold-600 bg-gold-800/25 px-4 py-3 text-[13px] text-gold-300">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                Kein Text erkannt — vermutlich ein gescanntes/Bild-PDF. OCR nötig.
              </div>
            )}

            <div className="mt-4 divide-y divide-cockpit-line rounded-2xl border border-cockpit-line">
              {result.fields.map((f) => (
                <div key={f.field} className="flex flex-wrap items-center gap-4 px-4 py-3">
                  <div className="w-32 shrink-0 font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint">
                    {f.label}
                  </div>
                  <div className="min-w-0 flex-1 truncate text-[14px] font-medium text-cockpit-text">
                    {f.value}
                  </div>
                  <ConfidenceBar value={f.confidence} review={f.needs_review} />
                  {f.needs_review ? (
                    <span className="flex w-28 items-center gap-1 font-mono text-[12px] text-gold-400">
                      <AlertTriangle className="h-3.5 w-3.5" /> Prüfen
                    </span>
                  ) : (
                    <span className="flex w-28 items-center gap-1 font-mono text-[12px] text-mint-400">
                      <Check className="h-3.5 w-3.5" /> Übernommen
                    </span>
                  )}
                </div>
              ))}
              {result.fields.length === 0 && (
                <div className="px-4 py-6 text-center text-[14px] text-cockpit-dim">
                  Keine Felder erkannt.
                </div>
              )}
            </div>

            <p className="mt-3 text-[12px] leading-relaxed text-cockpit-faint">
              Felder unter der Konfidenzschwelle werden markiert und nicht automatisch übernommen —
              sie gehen in die manuelle Prüfung.
            </p>

            {/* laufwise verification trace — every check is a predicate over real
                state (the extracted result / the DB), not model text. */}
            {result.notes.length > 0 && (
              <details className="mt-4 rounded-2xl border border-cockpit-line">
                <summary className="cursor-pointer px-4 py-2.5 text-[13px] font-semibold text-cockpit-text">
                  Prüf-Protokoll{' '}
                  <span className="font-mono font-normal text-cockpit-faint">
                    (laufwise · {result.notes.length})
                  </span>
                </summary>
                <div className="space-y-1 border-t border-cockpit-line px-4 py-3 font-mono text-[12px] leading-relaxed">
                  {result.notes.map((n, i) => (
                    <div
                      key={i}
                      className={cn(
                        'flex gap-1.5',
                        n.startsWith('✗') ? 'text-coral-400' : 'text-cockpit-dim',
                      )}
                    >
                      {n}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 border-t border-cockpit-line px-6 py-4">
        <button
          type="button"
          onClick={() => {
            setResult(null)
            setFile(null)
            setError(null)
          }}
          className={cn(
            'font-mono text-[13px] text-cockpit-faint transition-colors hover:text-cockpit-text',
            !result && 'invisible',
          )}
        >
          Andere Datei
        </button>
        <div className="flex items-center gap-3">
          <Button onClick={onClose}>Abbrechen</Button>
          <Button
            tone="primary"
            onClick={handleSave}
            disabled={!result || saving || result.fields.length === 0}
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            Als Kandidat speichern
          </Button>
        </div>
      </div>
    </Modal>
  )
}
