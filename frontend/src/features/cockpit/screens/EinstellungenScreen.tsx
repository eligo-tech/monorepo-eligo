// "Einstellungen · Datenquellen" — how a workspace onboards its own book.
//
// Until this screen, connecting a customer's ATS meant an operator running a
// script with that customer's password in their shell. Here the workspace
// types it once; it is encrypted on the server and never comes back.
//
// Two things the copy has to be honest about, because both are deliberate:
//
//  * Pressing "Import anfordern" does NOT import. It queues the request and
//    the scheduled runner performs it — hundreds of outbound calls do not
//    belong inside a click, and collection stays a logged, scheduled activity.
//  * Without a server-side key no credential can be stored at all. The form
//    says that up front rather than accepting a password and refusing it.

import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Database, Loader2, Trash2 } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { SourceCapabilitiesDTO, TenantSourceDTO } from '@/api/types'
import { Button, TextInput } from '../ui/forms'
import { Chip, Panel, SectionHeader } from '../ui/primitives'

const KIND_LABEL: Record<string, string> = {
  aifind: 'aiFind (ATS)',
}

function dateTimeDe(iso: string): string {
  return new Date(iso).toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Berlin',
  })
}

/** "446 Kandidaten · 75 Jobs" from whatever the importer reported. */
function summaryLine(result: Record<string, number | string>): string | null {
  const parts = Object.entries(result)
    .filter(([, v]) => typeof v === 'number' && v > 0)
    .map(([k, v]) => `${v} ${k}`)
  return parts.length > 0 ? parts.join(' · ') : null
}

export function EinstellungenScreen() {
  const [caps, setCaps] = useState<SourceCapabilitiesDTO | null>(null)
  const [sources, setSources] = useState<TenantSourceDTO[] | null>(null)
  const [username, setUsername] = useState('')
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [capabilities, rows] = await Promise.all([
        api.sourceCapabilities(),
        api.tenantSources(),
      ])
      setCaps(capabilities)
      setSources(rows)
      const existing = rows.find((r) => r.kind === 'aifind')
      if (existing) setUsername((u) => u || existing.username)
    } catch {
      setSources([])
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const describe = (e: unknown) =>
    e instanceof ApiError
      ? e.status === 503
        ? 'Der Server kann noch keine Zugangsdaten speichern (ELIGO_SECRET_KEY fehlt).'
        : `Fehlgeschlagen (HTTP ${e.status}).`
      : 'Fehlgeschlagen — keine Antwort vom Server.'

  async function save() {
    if (!username.trim()) return setError('Benutzername darf nicht leer sein.')
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await api.saveTenantSource('aifind', {
        username: username.trim(),
        ...(secret ? { secret } : {}),
      })
      setSecret('')
      setNotice('Quelle gespeichert.')
      await reload()
    } catch (e) {
      setError(describe(e))
    }
    setBusy(false)
  }

  async function requestImport() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.requestImport('aifind')
      setNotice(result.detail)
      await reload()
    } catch (e) {
      setError(describe(e))
    }
    setBusy(false)
  }

  async function disconnect() {
    setBusy(true)
    setError(null)
    try {
      await api.deleteTenantSource('aifind')
      setSecret('')
      setNotice('Quelle getrennt.')
      await reload()
    } catch (e) {
      setError(describe(e))
    }
    setBusy(false)
  }

  const source = sources?.find((s) => s.kind === 'aifind')
  const blocked = caps !== null && !caps.secrets_configured

  return (
    <div className="space-y-8">
      <header id="section-einstellungen" className="scroll-mt-24">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-lav-400">
          Workspace
        </span>
        <h1 className="mt-1.5 text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          Einstellungen
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">
          Dieser Workspace und seine Daten gehören nur Ihnen — den Markt teilen
          sich alle, Kandidaten, Mandate und Ansprechpartner nicht.
        </p>
      </header>

      <section className="space-y-5">
        <SectionHeader
          id="section-quellen"
          index="01"
          title="Datenquellen"
          hint="Eigene Datenbank anbinden"
        />

        <Panel className="px-6 py-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-md border border-cockpit-line p-2 text-cockpit-faint">
              <Database className="h-5 w-5" />
            </span>
            <div>
              <h3 className="text-[16px] font-semibold text-cockpit-text">
                {KIND_LABEL.aifind}
              </h3>
              <p className="text-[13px] text-cockpit-dim">
                Firmen, Ansprechpartner, Mandate und Kandidaten aus Ihrem
                bestehenden System.
              </p>
            </div>
            {source && (
              <Chip tone={source.status === 'active' ? 'mint' : 'gold'} className="ml-auto">
                {source.status === 'active' ? 'verbunden' : 'pausiert'}
              </Chip>
            )}
          </div>

          {blocked ? (
            <p className="mt-4 rounded-xl border border-coral-600/50 bg-coral-800/20 px-4 py-3 text-[13px] text-coral-300">
              Der Server hat keinen Schlüssel für Zugangsdaten hinterlegt
              (ELIGO_SECRET_KEY). Bis dahin lassen sich keine Quellen verbinden —
              Passwörter im Klartext zu speichern wäre die schlechtere Antwort.
            </p>
          ) : (
            <>
              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <TextInput
                  label="Benutzername"
                  value={username}
                  onChange={setUsername}
                  type="email"
                  placeholder="name@firma.de"
                />
                <TextInput
                  label={source?.has_secret ? 'Passwort (nur zum Ändern)' : 'Passwort'}
                  value={secret}
                  onChange={setSecret}
                  type="password"
                  placeholder={source?.has_secret ? '•••••••• gespeichert' : ''}
                />
              </div>

              <p className="mt-3 text-[12px] leading-relaxed text-cockpit-faint">
                Das Passwort wird verschlüsselt gespeichert und nie wieder
                ausgeliefert — auch nicht an diesen Workspace. Der Import läuft als
                geplanter Lauf, nicht im Klick: Hunderte Abrufe gehören nicht in
                eine Browser-Anfrage, und so bleibt jede Datenerhebung protokolliert.
              </p>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button tone="primary" onClick={save} disabled={busy}>
                  {source ? 'Zugang aktualisieren' : 'Quelle verbinden'}
                </Button>
                {source?.has_secret && (
                  <Button onClick={requestImport} disabled={busy}>
                    Import anfordern
                  </Button>
                )}
                {source && (
                  <Button onClick={disconnect} disabled={busy} className="ml-auto">
                    <Trash2 className="h-4 w-4" /> Trennen
                  </Button>
                )}
              </div>
            </>
          )}

          {(error || notice) && (
            <p
              className={`mt-3 text-[13px] ${error ? 'text-coral-400' : 'text-mint-300'}`}
            >
              {error ?? notice}
            </p>
          )}

          {source && (
            <dl className="mt-5 space-y-1.5 border-t border-cockpit-line pt-4 font-mono text-[12px] text-cockpit-faint">
              {source.import_requested_at && (
                <div className="flex items-center gap-2 text-gold-300">
                  <Loader2 className="h-3.5 w-3.5" />
                  Import angefordert {dateTimeDe(source.import_requested_at)} — wartet
                  auf den nächsten Datenlauf.
                </div>
              )}
              {source.last_run_at && !source.last_error && (
                <div className="flex items-center gap-2 text-mint-300">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Zuletzt {dateTimeDe(source.last_run_at)}
                  {summaryLine(source.last_result)
                    ? ` · ${summaryLine(source.last_result)}`
                    : ''}
                </div>
              )}
              {source.last_error && (
                <div className="text-coral-400">
                  Letzter Lauf {source.last_run_at ? dateTimeDe(source.last_run_at) : ''}{' '}
                  fehlgeschlagen: {source.last_error}
                </div>
              )}
            </dl>
          )}
        </Panel>
      </section>
    </div>
  )
}
