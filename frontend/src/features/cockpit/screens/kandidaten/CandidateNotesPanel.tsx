// Gesprächsnotizen on a candidate (ELI-9).
//
// The manager side of this has existed since ELI-10. The candidate side did
// not exist at all: `manager_interactions.candidate_id` has been on the table
// since it was created and not one of the 366 imported notes ever filled it,
// so everything a recruiter knew from talking to a candidate lived in a CV
// field, a transcript, or somebody's head.
//
// Three kinds, which is what the recruiters asked for — a call, a message,
// and a call that went unanswered. The last is not an afterthought: "NA" is
// the single commonest kind on the manager side, and knowing you have tried
// four times is the thing that decides whether you try again.

import { t } from '@/i18n'
import { date as fmtDate } from '@/i18n/format'

import { useCallback, useEffect, useState } from 'react'
import { CalendarPlus, MessageSquare } from 'lucide-react'

import { api } from '@/api/client'
import type { ManagerInteractionDTO } from '@/api/types'
import { Button } from '../../ui/forms'
import { InteractionComposer } from '../../ui/InteractionComposer'
import { Chip } from '../../ui/primitives'
import {
  CANDIDATE_INTERACTION_KINDS,
  interactionLabel,
} from '../../ui/interactionKinds'

export function CandidateNotesPanel({ candidateId }: { candidateId: string }) {
  const [rows, setRows] = useState<ManagerInteractionDTO[] | null>(null)
  const [composing, setComposing] = useState(false)
  const [failed, setFailed] = useState(false)

  const load = useCallback(async () => {
    try {
      setRows(await api.candidateInteractions(candidateId))
      setFailed(false)
    } catch {
      // Not an empty list. "Nothing written down yet" and "we could not ask"
      // read the same on screen and mean opposite things, and the first one
      // is an invitation to write the note twice.
      setRows(null)
      setFailed(true)
    }
  }, [candidateId])

  useEffect(() => {
    setComposing(false)
    void load()
  }, [load])

  if (failed) {
    return (
      <p className="text-[13px] text-coral-400">
        {t('Notizen konnten nicht geladen werden.')}
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {composing ? (
        <div className="-mx-6 border-y border-cockpit-line">
          <InteractionComposer
            kinds={CANDIDATE_INTERACTION_KINDS}
            onCancel={() => setComposing(false)}
            onSave={async (entry) => {
              const row = await api.logCandidateInteraction(candidateId, entry)
              // Prepend and re-sort rather than refetch: the list is ordered
              // by when the conversation happened, so a note filed for last
              // Tuesday would otherwise appear to vanish.
              setRows((prev) =>
                [row, ...(prev ?? [])].sort((a, b) =>
                  b.occurred_at.localeCompare(a.occurred_at),
                ),
              )
              setComposing(false)
            }}
          />
        </div>
      ) : (
        <Button onClick={() => setComposing(true)}>
          <CalendarPlus className="h-4 w-4" /> {t('Notiz hinzufügen')}
        </Button>
      )}

      {rows !== null && rows.length === 0 && !composing && (
        <p className="text-[13px] text-cockpit-faint">
          {t('Noch keine Gesprächsnotiz zu dieser Person.')}
        </p>
      )}

      <ul className="space-y-3">
        {(rows ?? []).map((row) => (
          <li key={row.id} className="flex gap-3">
            <div className="w-20 shrink-0 pt-0.5">
              <p className="font-mono text-[11px] text-cockpit-faint">
                {fmtDate(row.occurred_at)}
              </p>
            </div>
            <div className="min-w-0 flex-1">
              <Chip>{interactionLabel(row.interaction_type)}</Chip>
              {row.summary && (
                <p className="mt-1.5 whitespace-pre-wrap text-[13.5px] leading-relaxed text-cockpit-dim">
                  {row.summary}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>

      {rows !== null && rows.length > 0 && (
        <p className="flex items-center gap-1.5 font-mono text-[11px] text-cockpit-faint">
          <MessageSquare className="h-3 w-3" />
          {t('{count} Notizen', { count: rows.length })}
        </p>
      )}
    </div>
  )
}
