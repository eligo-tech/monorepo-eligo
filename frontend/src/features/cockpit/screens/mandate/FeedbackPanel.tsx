// "Feedback · Rückmeldungen zu Kandidaten"
//
// The design says where this comes from: "Von Kunde & Kandidaten aus den
// Prozessschritten (inkl. Interview)". That is not a new store — it is the
// notes already written on the process steps, read back per mandate. So the
// list is live, and adding feedback writes a note onto the step the candidate
// is actually on, which is where the recruiter would have put it anyway.
//
// Who said it is a judgement the record does not keep: the tracker's verdict
// is the client's (see backend `pipeline/steps.py`). The chooser therefore
// prefixes the note with the speaker rather than pretending to a column.

import { useState } from 'react'

import { ApiError, api } from '@/api/client'
import { Panel } from '../../ui/primitives'
import { Button, SelectInput, TextArea } from '../../ui/forms'
import { PanelHead, PanelTag } from './parts'
import type { Mandate, ProcessCard } from '../../data/types'

const WHO = [
  { value: 'Kunde', label: 'Kunde' },
  { value: 'Kandidat', label: 'Kandidat' },
]

interface Entry {
  who: string
  candidate: string
  text: string
  step: string
}

/** Every note on this mandate's steps, newest step first. */
function entries(mandate: Mandate): Entry[] {
  const out: Entry[] = []
  for (const card of mandate.cards) {
    for (const step of [...card.steps].reverse()) {
      if (!step.note?.trim()) continue
      const [prefix, ...rest] = step.note.split(':')
      const tagged = rest.length > 0 && ['Kunde', 'Kandidat'].includes(prefix.trim())
      out.push({
        who: tagged ? prefix.trim() : 'Notiz',
        candidate: card.candidateName,
        text: tagged ? rest.join(':').trim() : step.note,
        step: step.label,
      })
    }
  }
  return out
}

/** The step a note belongs on: the one in play, else the last one touched. */
function targetStep(card: ProcessCard) {
  return (
    card.steps.find((s) => s.state === 'current') ??
    [...card.steps].reverse().find((s) => s.state === 'done') ??
    card.steps[0]
  )
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
  const list = entries(mandate)

  const candidates = mandate.cards.map((c) => ({ value: c.id, label: c.candidateName }))
  const card = mandate.cards.find((c) => c.id === about) ?? mandate.cards[0]

  async function add() {
    if (!text.trim() || !card) return
    const step = targetStep(card)
    setBusy(true)
    setError(null)
    try {
      await api.setProcessStep(card.id, step.key, {
        note: `${who}: ${text.trim()}`,
      })
      setText('')
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
      <PanelHead tag="Feedback" tone="gold" title="Rückmeldungen zu Kandidaten" />
      <p className="-mt-2 mb-4 text-[13px] text-cockpit-dim">
        Von Kunde &amp; Kandidaten aus den Prozessschritten (inkl. Interview) — schärft
        die nächsten Kandidaten.
      </p>

      {list.length === 0 ? (
        <p className="text-[13px] italic text-cockpit-faint">
          Noch keine Rückmeldung notiert.
        </p>
      ) : (
        <ul className="space-y-2">
          {list.map((entry, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-2 text-[13px]">
              <PanelTag tone={entry.who === 'Kandidat' ? 'coral' : 'gold'}>
                {entry.who}
              </PanelTag>
              <span className="font-semibold text-cockpit-text">{entry.candidate}</span>
              <span className="font-mono text-[11px] text-cockpit-faint">
                {entry.step}
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
            placeholder="Feedback notieren …"
          />
          <div className="flex flex-wrap items-end justify-end gap-2">
            <SelectInput label="Von" value={who} onChange={setWho} options={WHO} />
            <SelectInput
              label="Zu"
              value={about}
              onChange={setAbout}
              options={candidates}
            />
            <Button tone="primary" onClick={add} disabled={busy || !text.trim()}>
              Feedback hinzufügen
            </Button>
          </div>
          {card && (
            <p className="text-right font-mono text-[11px] text-cockpit-faint">
              wird als Notiz an „{targetStep(card).label}“ gehängt
            </p>
          )}
          {error && <p className="text-[13px] text-coral-400">{error}</p>}
        </div>
      )}
    </Panel>
  )
}
