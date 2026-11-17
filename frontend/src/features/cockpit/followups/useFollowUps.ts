// Wiedervorlagen (ELI-44): fetching, refreshing and the calendar download —
// the side-effecting half; the pure half is `ui/followUps.ts`.

import { t } from '@/i18n'

import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '@/api/client'
import type { FollowUpDTO, FollowUpSubject } from '@/api/types'
import { useRefreshOnFocus } from '@/hooks/useRefreshOnFocus'
import { FOLLOW_UPS_CHANGED, announceFollowUpsChanged, followUpIcs } from '../ui/followUps'

/** Open follow-ups — the workspace's, or one person's. `rows` is null while
 *  loading; `failed` says the call did not answer, which is not "none". */
export function useOpenFollowUps(subject?: FollowUpSubject) {
  const managerId = subject && 'managerId' in subject ? subject.managerId : undefined
  const candidateId = subject && 'candidateId' in subject ? subject.candidateId : undefined
  const [rows, setRows] = useState<FollowUpDTO[] | null>(null)
  const [failed, setFailed] = useState(false)
  // Only the latest request may answer: two quick "Erledigt" clicks fire two
  // loads, and an older one landing last would bring a closed row back.
  const latest = useRef(0)

  const load = useCallback(() => {
    const mine = ++latest.current
    api
      .followUps({ managerId, candidateId })
      .then((found) => {
        if (mine !== latest.current) return
        setRows(found)
        setFailed(false)
      })
      .catch(() => mine === latest.current && setFailed(true))
  }, [managerId, candidateId])

  useEffect(() => {
    // Another person: never show the previous one's rows meanwhile.
    setRows(null)
    load()
    return () => {
      latest.current++
    }
  }, [load])
  useEffect(() => {
    const onChange = () => load()
    window.addEventListener(FOLLOW_UPS_CHANGED, onChange)
    return () => window.removeEventListener(FOLLOW_UPS_CHANGED, onChange)
  }, [load])
  useRefreshOnFocus(load)

  return { rows, failed, reload: load }
}

/** The calendar title: what it is and who it is about. */
export const calendarTitle = (row: FollowUpDTO) =>
  t('Wiedervorlage — {name}', { name: row.person_name })

/** Hand the follow-up to the recruiter's own calendar as an .ics file. */
export function downloadFollowUpIcs(row: FollowUpDTO): void {
  const blob = new Blob([followUpIcs(row, calendarTitle(row))], { type: 'text/calendar' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `wiedervorlage-${row.due_date}.ics`
  a.click()
  // Not at once: Firefox and Safari cancel a download whose URL is gone.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Mark done, then tell every list. */
export async function completeFollowUp(row: FollowUpDTO): Promise<void> {
  await api.updateFollowUp(row.id, { status: 'done' })
  announceFollowUpsChanged()
}
