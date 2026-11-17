// After a note is saved (ELI-44): if its text names a date — "Anfang Februar
// wieder melden" — offer the Wiedervorlage for one click. The date is read by
// the backend's deterministic reader against the NOTE's day; nothing is
// created unless the recruiter confirms.

import { t } from '@/i18n'

import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { FollowUpSubject, FollowUpSuggestionDTO } from '@/api/types'
import { FollowUpOffer } from '../ui/FollowUpOffer'
import { announceFollowUpsChanged, localIsoDate, textFromNote } from '../ui/followUps'

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
  const [suggestions, setSuggestions] = useState<FollowUpSuggestionDTO[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setSuggestions([])
    const text = note.summary?.trim()
    if (!text) return
    // The note's day where the recruiter is: "nächste Woche" in a note
    // filed for last Tuesday means the week after that Tuesday.
    api
      .suggestFollowUps(text, localIsoDate(new Date(note.occurred_at)))
      .then((r) => live && setSuggestions(r.suggestions))
      // No offer is the honest fallback: the note is saved either way.
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [note.id, note.summary, note.occurred_at])

  const confirm = async (s: FollowUpSuggestionDTO) => {
    setBusy(true)
    setError(null)
    try {
      await api.createFollowUp({
        ...('managerId' in subject ? { manager_id: subject.managerId } : { candidate_id: subject.candidateId }),
        due_date: s.due_date,
        text: textFromNote(note.summary ?? '') || s.phrase,
        source_interaction_id: note.id,
        origin: 'note',
      })
      announceFollowUpsChanged()
      onClose()
    } catch {
      setError(t('Nicht gespeichert — bitte erneut versuchen.'))
    } finally {
      setBusy(false)
    }
  }

  return <FollowUpOffer suggestions={suggestions} onConfirm={(s) => void confirm(s)} onDismiss={onClose} busy={busy} error={error} />
}
