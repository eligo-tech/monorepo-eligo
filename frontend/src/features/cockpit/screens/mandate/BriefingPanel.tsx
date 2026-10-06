// "Briefing" — the conversation that defines the mandate.
//
// Phase 2 of the Prozess-Doku is a call with the hiring manager, and the
// product had nowhere to put it: the Suchprofil held the OUTCOME of that
// call (Muss-Kriterien, Band, Ort) and nothing held the call. So the one
// thing a recruiter writes down the minute they hang up — "sie will jemanden,
// der auch WildFly-Cluster kann, Remote erst ab Monat 3" — lived in a
// notebook.
//
// Dated and attributable, because a mandate is briefed more than once: the GE
// example's Muss-Profil was *geschärft* in a second conversation, and reading
// the current Suchprofil against the call that produced it is the point.
//
// The contact is optional. A mandate whose Ansprechpartner is not in the
// record yet is an ordinary state — the showcase mandate literally reads
// "Kein Ansprechpartner hinterlegt" — and refusing the note until somebody
// creates a `managers` row means the note never gets written.

import { useMemo, useState } from 'react'
import { MessageSquareQuote } from 'lucide-react'

import { api } from '@/api/client'
import type { BriefingDTO, ManagerDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { useRemembered } from '@/hooks/useRemembered'
import { Panel } from '../../ui/primitives'
import { Button } from '../../ui/forms'
import { PanelHead } from './parts'
import type { Mandate } from '../../data/types'

const dateDe = (iso: string) =>
  new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })

/** Today, as the date input wants it. */
const today = () => new Date().toISOString().slice(0, 10)

export function BriefingPanel({
  mandate,
  managers,
}: {
  mandate: Mandate
  /** Contacts at this client, to say who was spoken to. */
  managers?: ManagerDTO[]
}) {
  const [text, setText] = useState('')
  const [when, setWhen] = useState(today())
  const [who, setWho] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [key, setKey] = useState(0)

  // Folded by the reader, not per mandate: the briefing is what you read
  // once when picking a mandate up, and scroll past on every later visit.
  const [collapsed, setCollapsed] = useRemembered(
    'eligo.panel.briefing.collapsed',
    false,
  )
  const { data, loading } = useAsync<BriefingDTO[]>(
    () =>
      mandate.jobId
        ? api.jobBriefings(mandate.jobId).catch(() => [])
        : Promise.resolve([]),
    [mandate.jobId, key],
  )
  const rows = data ?? []

  const nameOf = useMemo(() => {
    const byId = new Map((managers ?? []).map((m) => [m.id, m.full_name]))
    return (id: string | null) => (id ? (byId.get(id) ?? null) : null)
  }, [managers])

  async function save() {
    const summary = text.trim()
    if (!summary || !mandate.jobId || busy) return
    setBusy(true)
    setError(null)
    try {
      await api.addBriefing(mandate.jobId, {
        summary,
        // Midday, so a date typed without a time does not drift across a
        // day boundary when it is read back in another timezone.
        occurred_at: new Date(`${when}T12:00:00`).toISOString(),
        manager_id: who || null,
      })
      setText('')
      setKey((k) => k + 1)
    } catch {
      setError('Nicht gespeichert — bitte erneut versuchen.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel className="px-6 py-5">
      <PanelHead
        tag="Briefing"
        tone="gold"
        title="Was der Kunde gesagt hat"
        note={`${mandate.ref} · ${rows.length} ${rows.length === 1 ? 'Eintrag' : 'Einträge'}`}
        collapsed={collapsed}
        onToggle={() => setCollapsed((shut) => !shut)}
      />

      {collapsed ? null : (
        <>
        {loading && rows.length === 0 && (
          <p className="font-mono text-[12px] text-cockpit-faint">lädt…</p>
        )}

        {!loading && rows.length === 0 && (
          <p className="mb-4 text-[13.5px] leading-relaxed text-cockpit-dim">
            Noch kein Briefing notiert. Das Suchprofil unten hält das Ergebnis des
            Gesprächs — hier steht, was tatsächlich gesagt wurde.
          </p>
        )}

        {rows.length > 0 && (
          <ul className="mb-5 space-y-3">
            {rows.map((row) => (
              <li
                key={row.id}
                className="border-l-2 border-gold-600/40 pl-3 text-[13.5px] leading-relaxed text-cockpit-dim"
              >
                <span className="mr-2 font-mono text-[12px] text-cockpit-faint">
                  {dateDe(row.occurred_at)}
                  {nameOf(row.manager_id) ? ` · ${nameOf(row.manager_id)}` : ''}
                </span>
                <span className="whitespace-pre-wrap text-cockpit-text">
                  {row.summary}
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="space-y-2 border-t border-cockpit-line pt-4">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="Nach dem Gespräch: was gesucht wird, was nicht geht, worauf es ankommt …"
            className="w-full rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 text-[13.5px] leading-relaxed text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none"
          />
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
              am
              <input
                type="date"
                value={when}
                onChange={(e) => setWhen(e.target.value)}
                className="rounded-md border border-cockpit-line bg-cockpit-inset px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
              />
            </label>
            <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
              mit
              <select
                value={who}
                onChange={(e) => setWho(e.target.value)}
                className="rounded-md border border-cockpit-line bg-cockpit-inset px-2 py-1 font-sans text-[13px] normal-case tracking-normal text-cockpit-text focus:border-cockpit-edge focus:outline-none"
              >
                <option value="">ohne Ansprechpartner</option>
                {(managers ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.full_name}
                  </option>
                ))}
              </select>
            </label>
            <Button
              tone="primary"
              onClick={() => void save()}
              disabled={busy || !text.trim()}
              className="ml-auto"
            >
              <MessageSquareQuote className="h-4 w-4" />
              {busy ? 'Speichert…' : 'Briefing notieren'}
            </Button>
          </div>
          {error && <p className="text-[12px] text-coral-400">{error}</p>}
        </div>
        </>
      )}
    </Panel>
  )
}
