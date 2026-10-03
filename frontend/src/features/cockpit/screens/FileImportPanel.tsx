// "Datei importieren" — onboarding that works whatever system a customer
// leaves behind.
//
// The flow is three steps and the middle one is the product: choose what the
// file contains, SEE what importing it would do, then do it. An import that
// silently creates 800 half-filled candidates is worse than one that refuses,
// so nothing is written until the preview has been shown.
//
// The mapping is a suggestion the server makes from the header names and the
// recruiter corrects. Asking a customer to rename columns before the product
// works is how onboarding dies.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowRight, FileSpreadsheet, Upload } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { ImportEntityDTO, ImportPreviewDTO, ImportResultDTO } from '@/api/types'
import { cn } from '@/lib/cn'
import { Button, SelectInput } from '../ui/forms'
import { Chip, Panel } from '../ui/primitives'

const ACTION_TONE: Record<string, string> = {
  create: 'text-mint-300',
  update: 'text-gold-300',
  skip: 'text-cockpit-faint',
}
const ACTION_LABEL: Record<string, string> = {
  create: 'neu',
  update: 'aktualisiert',
  skip: 'übersprungen',
}

export function FileImportPanel({
  canCommit = true,
  onImported,
}: {
  /** Previewing is for everyone; writing hundreds of rows over the record
   *  is an admin act. The server enforces it either way. */
  canCommit?: boolean
  onImported?: () => void
}) {
  const [entities, setEntities] = useState<ImportEntityDTO[]>([])
  const [entity, setEntity] = useState('candidates')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreviewDTO | null>(null)
  const [result, setResult] = useState<ImportResultDTO | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api
      .importEntities()
      .then(setEntities)
      .catch(() => setEntities([]))
  }, [])

  const spec = entities.find((e) => e.key === entity)

  const describe = (e: unknown) =>
    e instanceof ApiError
      ? // 422 carries the parser's own sentence ("…bitte als .xlsx speichern"),
        // which is more useful than anything this layer could invent.
        e.status === 422 || e.status === 400
        ? stripDetail(e.message)
        : `Fehlgeschlagen (HTTP ${e.status}).`
      : 'Fehlgeschlagen — keine Antwort vom Server.'

  const run = useCallback(
    async (chosen: File, kind: string, mapping?: Record<string, string>) => {
      setBusy(true)
      setError(null)
      setResult(null)
      try {
        setPreview(await api.importPreview(chosen, kind, mapping))
      } catch (e) {
        setPreview(null)
        setError(describe(e))
      }
      setBusy(false)
    },
    [],
  )

  async function commit() {
    if (!file || !preview) return
    setBusy(true)
    setError(null)
    try {
      const done = await api.importCommit(file, entity, preview.mapping)
      setResult(done)
      setPreview(null)
      setFile(null)
      onImported?.()
    } catch (e) {
      setError(describe(e))
    }
    setBusy(false)
  }

  /** Re-plan with a corrected mapping — the counts change as you fix it. */
  function remap(column: string, target: string) {
    if (!preview || !file) return
    const mapping = { ...preview.mapping }
    if (target) {
      // One field, one column: claiming a field frees it elsewhere, or the
      // second column would silently win on the server.
      for (const [key, value] of Object.entries(mapping)) {
        if (value === target && key !== column) delete mapping[key]
      }
      mapping[column] = target
    } else {
      delete mapping[column]
    }
    void run(file, entity, mapping)
  }

  const fieldOptions = [
    { value: '', label: '— nicht importieren' },
    ...(spec?.fields ?? []).map((f) => ({
      value: f.name,
      label: f.required ? `${f.label} *` : f.label,
    })),
  ]

  return (
    <Panel className="px-6 py-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
          <FileSpreadsheet className="h-5 w-5" />
        </span>
        <div className="min-w-0">
          <h3 className="text-[16px] font-semibold text-cockpit-text">
            Datei importieren
          </h3>
          <p className="text-[13px] text-cockpit-dim">
            {spec?.hint ??
              'CSV oder Excel aus Ihrem bisherigen System — Spalten werden erkannt.'}
          </p>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-end gap-3">
        <SelectInput
          label="Was enthält die Datei?"
          value={entity}
          onChange={(v) => {
            setEntity(v)
            setPreview(null)
            setResult(null)
            if (file) void run(file, v)
          }}
          options={entities.map((e) => ({ value: e.key, label: e.label }))}
        />
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".csv,.txt,.xlsx,.xlsm"
          onChange={(e) => {
            const chosen = e.target.files?.[0]
            if (chosen) {
              setFile(chosen)
              void run(chosen, entity)
            }
            e.target.value = ''
          }}
        />
        <Button onClick={() => fileRef.current?.click()} disabled={busy}>
          <Upload className="h-4 w-4" /> {file ? 'Andere Datei' : 'Datei wählen'}
        </Button>
        {file && (
          <span className="font-mono text-[12px] text-cockpit-faint">{file.name}</span>
        )}
      </div>

      {error && <p className="mt-4 text-[13px] text-coral-400">{error}</p>}

      {result && (
        <div className="mt-4 rounded-xl border border-mint-600/50 bg-mint-800/20 px-4 py-3 text-[13px] text-mint-300">
          {result.created} neu angelegt · {result.updated} aktualisiert ·{' '}
          {result.skipped} übersprungen.
          {result.problems.length > 0 && (
            <span className="block text-cockpit-dim">{result.problems.join(' ')}</span>
          )}
        </div>
      )}

      {preview && (
        <div className="mt-5 space-y-4 border-t border-cockpit-line pt-5">
          <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 font-mono text-[12px] text-cockpit-faint">
            <span>{preview.note}</span>
            <span>
              <span className="text-cockpit-text">{preview.row_count}</span> Zeilen
            </span>
            <span className="text-mint-300">{preview.counts.create} neu</span>
            <span className="text-gold-300">{preview.counts.update} aktualisiert</span>
            <span>{preview.counts.skip} übersprungen</span>
          </div>

          {preview.problems.map((problem) => (
            <p key={problem} className="text-[13px] text-gold-300">
              {problem}
            </p>
          ))}

          {/* The mapping, as a table you can correct. Columns the server did
              not recognise sit at "nicht importieren" until you say what
              they are. */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-left">
              <thead>
                <tr className="font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
                  <th className="border-b border-cockpit-line pb-2 pr-4">Spalte</th>
                  <th className="border-b border-cockpit-line pb-2 pr-4">Beispiel</th>
                  <th className="border-b border-cockpit-line pb-2">Feld</th>
                </tr>
              </thead>
              <tbody>
                {preview.columns.map((column) => {
                  const sample = preview.sample.find((r) => r.values)?.values ?? {}
                  const target = preview.mapping[column] ?? ''
                  const shown = target ? sample[target] : undefined
                  return (
                    <tr key={column} className="align-middle">
                      <td className="border-b border-cockpit-line/60 py-2 pr-4 text-[13px] text-cockpit-text">
                        {column}
                      </td>
                      <td className="max-w-[220px] truncate border-b border-cockpit-line/60 py-2 pr-4 font-mono text-[12px] text-cockpit-faint">
                        {shown === undefined
                          ? '—'
                          : Array.isArray(shown)
                            ? shown.join(', ')
                            : String(shown)}
                      </td>
                      <td className="border-b border-cockpit-line/60 py-1.5">
                        <select
                          value={target}
                          onChange={(e) => remap(column, e.target.value)}
                          className={cn(
                            'rounded-lg border bg-cockpit-inset px-2.5 py-1.5 text-[12.5px] text-cockpit-text',
                            target ? 'border-cockpit-line' : 'border-cockpit-line/50 text-cockpit-faint',
                          )}
                        >
                          {fieldOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {preview.sample.some((r) => r.action === 'skip') && (
            <ul className="space-y-1 font-mono text-[11.5px] text-cockpit-faint">
              {preview.sample
                .filter((r) => r.action === 'skip')
                .slice(0, 5)
                .map((r) => (
                  <li key={r.line}>
                    Zeile {r.line} übersprungen — {r.reason}
                  </li>
                ))}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              tone="primary"
              onClick={commit}
              disabled={
                busy ||
                !canCommit ||
                preview.counts.create + preview.counts.update === 0
              }
              title={canCommit ? undefined : 'Nur Administratoren können importieren'}
            >
              {preview.counts.create + preview.counts.update} Zeilen importieren
              <ArrowRight className="h-4 w-4" />
            </Button>
            <span className="font-mono text-[11.5px] text-cockpit-faint">
              {!canCommit && 'Nur Administratoren können importieren. '}
              Noch wurde nichts geschrieben. Dieselbe Datei erneut zu importieren
              aktualisiert die Datensätze, statt sie zu verdoppeln.
            </span>
          </div>

          {preview.sample.length > 0 && (
            <details className="text-[12px] text-cockpit-faint">
              <summary className="cursor-pointer">
                Erste {preview.sample.length} Zeilen, wie sie landen würden
              </summary>
              <ul className="mt-2 space-y-1">
                {preview.sample.map((row) => (
                  <li key={row.line} className="font-mono text-[11.5px]">
                    <span className={ACTION_TONE[row.action]}>
                      {ACTION_LABEL[row.action]}
                    </span>{' '}
                    · {summarise(row.values)}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {!preview && !result && (
        <p className="mt-4 text-[12px] leading-relaxed text-cockpit-faint">
          CSV (auch mit Semikolon und Umlauten) oder .xlsx. Die Spalten werden
          erkannt und vor dem Import angezeigt — geschrieben wird erst, wenn Sie
          bestätigen. <Chip>max. 20 MB</Chip>
        </p>
      )}
    </Panel>
  )
}

/** "Jörg Müller · j.mueller@example.de · Senior Java Entwickler" */
function summarise(values: Record<string, unknown>): string {
  const parts = Object.values(values)
    .filter((v) => typeof v === 'string' && v.length > 0)
    .slice(0, 3) as string[]
  return parts.join(' · ') || '—'
}

/** FastAPI wraps errors as {"detail": "..."}; show the sentence, not the JSON. */
function stripDetail(message: string): string {
  try {
    const parsed = JSON.parse(message)
    if (typeof parsed?.detail === 'string') return parsed.detail
  } catch {
    /* not JSON — use it as it is */
  }
  return message
}
