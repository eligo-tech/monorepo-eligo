// "Suchprofil · Ideales Kandidatenprofil"
//
// Half of this is the mandate record and half is not. The Muss-Kriterien, the
// region and the Gehaltsrahmen are real and editable (they are the matcher's
// hard filters — see the Mandat editor on the Jobs screen). Nice-to-have,
// Kultur, Seniorität and Verfügbarkeit have no column yet, so they are drawn
// as the design draws them and marked.
//
// The manager-feedback banner at the top is the design's argument for the
// whole panel: what the client said about the last profiles should visibly
// change what is searched for next.

import { useState } from 'react'
import { CheckCircle2, Plus } from 'lucide-react'

import { api } from '@/api/client'
import type { CriteriaSuggestionDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { Chip, Panel } from '../../ui/primitives'
import { DemoText, PanelHead } from './parts'
import type { Mandate } from '../../data/types'

const NICE_TO_HAVE = ['dbt', 'MLOps', 'Finanzbranche']
const CULTURE = 'Hands-on · Ownership · Startup-Mentalität · flache Hierarchien'

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-t border-cockpit-line/70 py-2 first:border-t-0">
      <span className="text-[13px] text-cockpit-dim">{label}</span>
      <span className="text-right text-[13px] font-semibold text-cockpit-text">
        {children}
      </span>
    </div>
  )
}

/**
 * Muss-Kriterien the title already names, as one-click chips.
 *
 * 63 of 76 mandates carry none, which makes `apply_hard_filters` a no-op for
 * most of the book: the recruiter sees a ranked list that looks filtered and
 * is not. Nothing here writes by itself — a hard criterion excludes people,
 * so a human picks the ones that are really non-negotiable.
 */
function CriteriaSuggestions({
  mandate,
  onAdded,
}: {
  mandate: Mandate
  onAdded?: () => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [added, setAdded] = useState<string[]>([])
  const [key, setKey] = useState(0)
  const { data } = useAsync<CriteriaSuggestionDTO[]>(
    () =>
      mandate.jobId
        ? api.criteriaSuggestions(mandate.jobId).catch(() => [])
        : Promise.resolve([]),
    [mandate.jobId, key],
  )
  const open = (data ?? []).filter((s) => !added.includes(s.skill))
  if (!mandate.jobId || open.length === 0) return null

  async function accept(skill: string) {
    if (!mandate.jobId) return
    setBusy(skill)
    try {
      await api.updateJob(mandate.jobId, {
        must_have_skills: [...mandate.mustHave, skill],
      })
      setAdded((prev) => [...prev, skill])
      setKey((k) => k + 1)
      onAdded?.()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="mt-2 space-y-1.5">
      <p className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-cockpit-faint">
        Vorschläge aus dem Titel
      </p>
      <div className="flex flex-wrap gap-1.5">
        {open.map((s) => (
          <button
            key={s.skill}
            type="button"
            disabled={busy !== null}
            onClick={() => void accept(s.skill)}
            title={`${s.evidence} · ${s.candidates} Kandidat(en) im Bestand führen ihn`}
            className="flex items-center gap-1 rounded-md border border-dashed border-gold-600/50 px-2 py-0.5 text-[12px] text-gold-300 transition-colors hover:border-gold-500 hover:bg-gold-500/10 disabled:opacity-40"
          >
            <Plus className="h-3 w-3" />
            {busy === s.skill ? 'fügt hinzu…' : s.skill}
            <span className="font-mono text-[11px] text-cockpit-faint">
              {s.candidates}
            </span>
          </button>
        ))}
      </div>
      <p className="text-[12px] leading-relaxed text-cockpit-faint">
        Aus dem Mandatstitel und dem Vokabular des eigenen Bestands — ein Klick
        macht daraus ein hartes Kriterium, das Kandidaten ausschließt.
      </p>
    </div>
  )
}

export function SuchprofilPanel({
  mandate,
  onChanged,
}: {
  mandate: Mandate
  onChanged?: () => void
}) {
  const band =
    mandate.salaryMin !== null && mandate.salaryMax !== null
      ? `${mandate.salaryMin.toLocaleString('de-DE')} – ${mandate.salaryMax.toLocaleString('de-DE')} €`
      : mandate.salaryMax !== null
        ? `bis ${mandate.salaryMax.toLocaleString('de-DE')} €`
        : null

  return (
    <Panel className="px-6 py-5">
      <PanelHead
        tag="Suchprofil"
        tone="lav"
        title="Ideales Kandidatenprofil"
        note={`aus dem Mandat ${mandate.ref} · ${mandate.title}`}
      />

      <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-mint-700/50 bg-mint-800/20 px-4 py-2.5 text-[13px] text-cockpit-dim">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mint-400" />
        <span>
          <DemoText source="Kein Feedback-zu-Suchprofil-Lauf angebunden">
            Manager-Feedback zu den letzten Profilen fließt hier ein und schärft die
            Muss-Kriterien.
          </DemoText>
        </span>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="space-y-2">
            <span className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-cockpit-faint">
              Musskriterien
            </span>
            <div className="flex flex-wrap gap-1.5">
              {mandate.mustHave.length > 0 ? (
                mandate.mustHave.map((skill) => (
                  <Chip key={skill} tone="gold">
                    {skill}
                  </Chip>
                ))
              ) : (
                <span className="text-[13px] text-cockpit-faint">
                  Keine hinterlegt — ohne sie filtert das Matching nicht.
                </span>
              )}
            </div>
            <CriteriaSuggestions mandate={mandate} onAdded={onChanged} />
          </div>

          <div className="space-y-2">
            <span className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-cockpit-faint">
              Nice-to-have
            </span>
            <div className="flex flex-wrap gap-1.5">
              {NICE_TO_HAVE.map((skill) => (
                <Chip key={skill}>
                  <DemoText source="Nice-to-have ist am Mandat noch kein Feld">
                    {skill}
                  </DemoText>
                </Chip>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <span className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-cockpit-faint">
            Kultur
          </span>
          <p className="text-[13px] text-cockpit-dim">
            <DemoText source="Kultur ist am Mandat noch kein Feld">{CULTURE}</DemoText>
          </p>
          <div className="mt-3">
            <Fact label="Seniorität">
              <DemoText source="Seniorität ist am Mandat noch kein Feld">
                Lead / Head
              </DemoText>
            </Fact>
            <Fact label="Region">
              {mandate.location ? (
                mandate.location
              ) : (
                <span className="text-cockpit-faint">nicht hinterlegt</span>
              )}
            </Fact>
            <Fact label="Gehaltsrahmen">
              {band ?? <span className="text-cockpit-faint">nicht hinterlegt</span>}
            </Fact>
            <Fact label="Verfügbarkeit">
              <DemoText source="Startdatum ist am Mandat noch kein Feld">ab Q3</DemoText>
            </Fact>
          </div>
        </div>
      </div>
    </Panel>
  )
}
