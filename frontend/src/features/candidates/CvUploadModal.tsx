import { useRef, useState } from 'react'
import { UploadCloud, FileText, X, Check, AlertTriangle, Loader2 } from 'lucide-react'
import { api } from '@/api/client'
import type { CVExtractionResultDTO } from '@/api/types'
import { cn } from '@/lib/cn'

interface Props {
  onClose: () => void
  onCreated: () => void
}

function ConfidenceBar({ value, review }: { value: number; review: boolean }) {
  const pct = Math.round(value * 100)
  const tone = review ? 'bg-accent-500' : value >= 0.85 ? 'bg-brand-500' : 'bg-brand-400'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
        <div className={cn('h-full rounded-full', tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-[12px] tabular-nums text-ink-muted">{pct}%</span>
    </div>
  )
}

/** Upload a PDF CV → extract fields (preview) → save as a candidate. */
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6">
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-card bg-white shadow-card">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-ink">Kandidat aus CV</h2>
            <p className="text-[13px] text-ink-muted">
              PDF hochladen — Felder werden extrahiert und geprüft.
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-50">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {/* Dropzone */}
          {!result && (
            <button
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
                'flex w-full flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-6 py-12 transition-colors',
                dragging ? 'border-brand-400 bg-brand-50' : 'border-line hover:bg-slate-50',
              )}
            >
              {loading ? (
                <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
              ) : (
                <UploadCloud className="h-8 w-8 text-brand-500" />
              )}
              <div className="text-center">
                <div className="font-semibold text-ink">
                  {loading ? 'Wird extrahiert…' : 'PDF hierher ziehen oder klicken'}
                </div>
                <div className="text-[13px] text-ink-muted">Nur PDF · max. 10 MB</div>
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
            <div className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-[14px] text-rose-600">
              {error}
            </div>
          )}

          {/* Results */}
          {result && (
            <div>
              <div className="flex items-center gap-2 text-[14px] text-ink-soft">
                <FileText className="h-4 w-4 text-ink-faint" />
                <span className="font-medium text-ink">{result.document_name}</span>
                <span className="text-ink-muted">
                  · {accepted} von {result.fields.length} Feldern übernommen
                </span>
              </div>

              {scanned && (
                <div className="mt-3 flex items-center gap-2 rounded-xl bg-amber-50 px-4 py-3 text-[13px] text-accent-600">
                  <AlertTriangle className="h-4 w-4" />
                  Kein Text erkannt — vermutlich ein gescanntes/Bild-PDF. OCR nötig.
                </div>
              )}

              <div className="mt-4 divide-y divide-line rounded-2xl border border-line">
                {result.fields.map((f) => (
                  <div key={f.field} className="flex items-center gap-4 px-4 py-3">
                    <div className="w-32 shrink-0 text-[13px] text-ink-muted">{f.label}</div>
                    <div className="min-w-0 flex-1 truncate text-[14px] font-medium text-ink">
                      {f.value}
                    </div>
                    <ConfidenceBar value={f.confidence} review={f.needs_review} />
                    {f.needs_review ? (
                      <span className="flex w-24 items-center gap-1 text-[12px] font-semibold text-accent-600">
                        <AlertTriangle className="h-3.5 w-3.5" /> Prüfen
                      </span>
                    ) : (
                      <span className="flex w-24 items-center gap-1 text-[12px] font-semibold text-brand-600">
                        <Check className="h-3.5 w-3.5" /> Übernommen
                      </span>
                    )}
                  </div>
                ))}
                {result.fields.length === 0 && (
                  <div className="px-4 py-6 text-center text-[14px] text-ink-muted">
                    Keine Felder erkannt.
                  </div>
                )}
              </div>

              <p className="mt-3 text-[12px] text-ink-faint">
                Felder unter der Konfidenzschwelle werden markiert und nicht automatisch
                übernommen — sie gehen in die manuelle Prüfung.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-line px-6 py-4">
          <button
            onClick={() => {
              setResult(null)
              setFile(null)
              setError(null)
            }}
            className={cn(
              'text-[14px] font-medium text-ink-muted hover:text-ink-soft',
              !result && 'invisible',
            )}
          >
            Andere Datei
          </button>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="rounded-xl border border-line px-4 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50"
            >
              Abbrechen
            </button>
            <button
              onClick={handleSave}
              disabled={!result || saving || result.fields.length === 0}
              className="flex items-center gap-2 rounded-xl bg-brand-500 px-5 py-2 text-[14px] font-semibold text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              Als Kandidat speichern
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}