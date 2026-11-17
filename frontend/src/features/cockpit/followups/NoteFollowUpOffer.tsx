// After a call is logged or a note is saved (ELI-44, ELI-48): offer the
// Wiedervorlage. If the text names a date — "Anfang Februar wieder melden" —
// it is offered for one click; if not — "hey, grad gesprochen" — the offer
// still comes, with a week out and the note as the to-do, both editable. The
// date is read by the backend's deterministic reader against the NOTE's day;
// nothing is created unless the recruiter confirms.

import { t } from '@/i18n'

import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { FollowUpSubject, FollowUpSuggestionDTO } from '@/api/types'
import { FollowUpOffer } from '../ui/FollowUpOffer'
import type { FollowUpFields } from '../ui/FollowUpForm'
import { announceFollowUpsChanged, defaultFollowUpDate, localIsoDate, textFromNote } from '../ui/followUps'

/** The note just saved: its row id, text and when it happened. */
export interface SavedNote {
  id: string
  summary: string | null
  occurred_at: string
}

export function NoteFollowUpOffer({
  subject,
  note,
  onClose,
}: {
  subject: FollowUpSubject
  note: SavedNote
  onClose: () => void
}) {
  // null while the date is being read: the offer waits rather than flicker
  // from "no date" to "Anfang Februar".
  const [suggestions, setSuggestions] = useState<FollowUpSuggestionDTO[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    const text = note.summary?.trim()
    if (!text) {
      setSuggestions([])
      return
    }
    setSuggestions(null)
    // The note's day where the recruiter is: "nächste Woche" in a note
    // filed for last Tuesday means the week after that Tuesday.
    api
      .suggestFollowUps(text, localIsoDate(new Date(note.occurred_at)))
      .then((r) => live && setSuggestions(r.suggestions))
      // No date read is not no offer: the dateless one still comes.
      .catch(() => live && setSuggestions([]))
    return () => {
      live = false
    }
  }, [note.id, note.summary, note.occurred_at])

  const create = (fields: FollowUpFields) =>
    api.createFollowUp({
      ...('managerId' in subject ? { manager_id: subject.managerId } : { candidate_id: subject.candidateId }),
      ...fields,
      source_interaction_id: note.id,
      origin: 'note',
    })

  const confirm = async (s: FollowUpSuggestionDTO) => {
    setBusy(true)
    setError(null)
    try {
      await create({ due_date: s.due_date, due_time: null, text: textFromNote(note.summary ?? '') || s.phrase })
      announceFollowUpsChanged()
      onClose()
    } catch {
      setError(t('Nicht gespeichert — bitte erneut versuchen.'))
    } finally {
      setBusy(false)
    }
  }

  // The form shows its own error and stays open when this rejects.
  const save = async (fields: FollowUpFields) => {
    await create(fields)
    announceFollowUpsChanged()
    onClose()
  }

  if (suggestions === null) return null
  return (
    <FollowUpOffer
      suggestions={suggestions}
      fallbackDate={defaultFollowUpDate()}
      noteText={textFromNote(note.summary ?? '')}
      onConfirm={(s) => void confirm(s)}
      onSave={save}
      onDismiss={onClose}
      busy={busy}
      error={error}
    />
  )
}
