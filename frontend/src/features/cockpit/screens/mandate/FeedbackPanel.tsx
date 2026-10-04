// "Feedback · Rückmeldungen zu den Kandidaten"
//
// Every line here is about ONE CANDIDATE: what the client said after a
// presentation, what the candidate said after an interview. The speaker is
// only where it came from — the row used to lead with that speaker ("Kunde ·
// AnonymGE · Feedback Kunde · …") and read as feedback about the client,
// which it never is. The step is called "Feedback Kunde" because it is the
// round in which the client gives theirs.
//
// A row per remark. This used to write into the process step's `note`, which
// is a single field: the second remark on a step silently replaced the first
// and nothing said so. It now goes to `manager_interactions` as
// `interaction_type: "feedback"` with the candidate on it — the same
// append-only store the briefing uses, read back per mandate.
//
// The notes already written onto steps are still shown, below the new ones
// and marked as what they are. They were somebody's work; a change of store
// is not a reason to make them disappear.
//
// Who said it has no column: the tracker's verdict is the client's (see
// backend `pipeline/steps.py`). The chooser prefixes the text with the
// speaker rather than pretending to one.

import { useMemo, useState } from 'react'

import { ApiError, api } from '@/api/client'
import type { BriefingDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { Panel } from '../../ui/primitives'
import { Button, SelectInput, TextArea } from '../../ui/forms'
import { PanelHead, PanelTag } from './parts'
import type { Mandate } from '../../data/types'

const WHO = [
  { value: 'Kunde', label: 'Kunde' },
  { value: 'Kandidat', label: 'Kandidat' },
]

interface Entry {
  who: string
  candidate: string
  text: string
  /** Where it came from: a date for a recorded remark, a step for a note. */
  origin: string
}

const dateDe = (iso: string) =>
  new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })

/** "Kunde: fachlich überzeugend" → who + what, without inventing a column. */
function split(text: string): { who: string; text: string } {
  const [prefix, ...rest] = text.split(':')
  return rest.length > 0 && ['Kunde', 'Kandidat'].includes(prefix.trim())
    ? { who: prefix.trim(), text: rest.join(':').trim() }
    : { who: 'Notiz', text }
}

/** Notes left on this mandate's steps, from before feedback had its own
 *  store. Read-only history, newest step first. */
function fromSteps(mandate: Mandate): Entry[] {
  const out: Entry[] = []
  for (const card of mandate.cards) {
    for (const step of [...card.steps].reverse()) {
      if (!step.note?.trim()) continue
      out.push({
        ...split(step.note),
        candidate: card.candidateName,
        origin: `Notiz an „${step.label}“`,
      })
    }
  }
  return out
}

export function FeedbackPanel({
  mandate,
  onChanged,
}: {
  mandate: Mandate
  onChanged?: () => void
}) {
  const [who, setWho] = useState('Kunde')
  const [about, setAbout] = useState(mandate.cards[0]?.id ?? '')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [key, setKey] = useState(0)

  const { data } = useAsync<BriefingDTO[]>(
    () =>
      mandate.jobId
        ? api.jobFeedback(mandate.jobId).catch(() => [])
        : Promise.resolve([]),
    [mandate.jobId, key],
  )

  const nameOf = useMemo(() => {
    const byId = new Map(
      mandate.cards
        .filter((c) => c.candidateId)
        .map((c) => [c.candidateId as string, c.candidateName]),
    )
    return (id: string | null) => (id ? (byId.get(id) ?? 'Kandidat') : 'Kandidat')
  }, [mandate.cards])

  const recorded: Entry[] = (data ?? []).map((row) => ({
    ...split(row.summary ?? ''),
    candidate: nameOf(row.candidate_id),
    origin: dateDe(row.occurred_at),
  }))
  const list = [...recorded, ...fromSteps(mandate)]

  const candidates = mandate.cards.map((c) => ({
    value: c.id,
    label: c.candidateName,
  }))
  const card = mandate.cards.find((c) => c.id === about) ?? mandate.cards[0]

  async function add() {
    const body = text.trim()
    if (!body || !card?.candidateId || !mandate.jobId || busy) return
    setBusy(true)
    setError(null)
    try {
      await api.addFeedback(mandate.jobId, {
        summary: `${who}: ${body}`,
        candidate_id: card.candidateId,
      })
      setText('')
      setKey((k) => k + 1)
      onChanged?.()
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `Konnte nicht gespeichert werden (HTTP ${e.status}).`
          : 'Konnte nicht gespeichert werden.',
      )
    }
    setBusy(false)
  }

  return (
    <Panel className="px-6 py-5">
      <PanelHead
        tag="Feedback"
        tone="gold"
        title="Rückmeldungen zu den Kandidaten"
        note={`${list.length} ${list.length === 1 ? 'Eintrag' : 'Einträge'}`}
      />
      <p className="-mt-2 mb-4 text-[13px] text-cockpit-dim">
        Was über die vorgestellten Kandidaten gesagt wurde — vom Kunden und von den
        Kandidaten selbst, aus den Prozessschritten (inkl. Interview). Schärft die
        nächsten Vorschläge.
      </p>

      {list.length === 0 ? (
        <p className="text-[13px] italic text-cockpit-faint">
          Noch keine Rückmeldung notiert.
        </p>
      ) : (
        <ul className="space-y-2">
          {list.map((entry, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-2 text-[13px]">
              <span className="font-semibold text-cockpit-text">{entry.candidate}</span>
              <PanelTag tone={entry.who === 'Kandidat' ? 'coral' : 'gold'}>
                {entry.who === 'Notiz' ? 'Notiz' : `von ${entry.who}`}
              </PanelTag>
              <span className="font-mono text-[11px] text-cockpit-faint">
                {entry.origin}
              </span>
              <span className="min-w-0 flex-1 text-cockpit-dim">— {entry.text}</span>
            </li>
          ))}
        </ul>
      )}

      {mandate.cards.length > 0 && (
        <div className="mt-4 space-y-3">
          <TextArea
            value={text}
            onChange={setText}
            placeholder="Rückmeldung zu diesem Kandidaten notieren …"
          />
          <div className="flex flex-wrap items-end justify-end gap-2">
            <SelectInput
              label="Gesagt von"
              value={who}
              onChange={setWho}
              options={WHO}
            />
            <SelectInput
              label="Über Kandidat"
              value={about}
              onChange={setAbout}
              options={candidates}
            />
            <Button
              tone="primary"
              onClick={add}
              disabled={busy || !text.trim() || !card?.candidateId}
            >
              Feedback hinzufügen
            </Button>
          </div>
          {/* Said out loud, because the old behaviour was the opposite and
              silent: nothing is replaced, every remark stays. */}
          <p className="text-right font-mono text-[11px] text-cockpit-faint">
            wird als eigener Eintrag gespeichert — bestehende bleiben stehen
          </p>
          {error && <p className="text-[13px] text-coral-400">{error}</p>}
        </div>
      )}
    </Panel>
  )
}
