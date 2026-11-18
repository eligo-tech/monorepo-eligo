// A person's open Wiedervorlagen (ELI-44) — on the manager page (Leads and
// Managers are one record) and on the candidate. Visible until done: the
// list is the open ones, and "Erledigt" is the only way off it.

import { t } from '@/i18n'

import { useState } from 'react'
import { BellPlus } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type { FollowUpDTO, FollowUpSubject } from '@/api/types'
import { Button } from '../ui/forms'
import { FollowUpForm, type FollowUpFields } from '../ui/FollowUpForm'
import { FollowUpRows } from '../ui/FollowUpList'
import { announceFollowUpsChanged, localIsoDate } from '../ui/followUps'
import { completeFollowUp, downloadFollowUpIcs, readDateFromText, useOpenFollowUps } from './useFollowUps'
import { isAdmin, useMe } from '../useMe'

const subjectIds = (subject: FollowUpSubject) =>
  'managerId' in subject ? { manager_id: subject.managerId } : { candidate_id: subject.candidateId }

export function PersonFollowUps({ subject, compact }: { subject: FollowUpSubject; compact?: boolean }) {
  const { rows, failed } = useOpenFollowUps(subject)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<FollowUpDTO | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const today = localIsoDate()
  // ELI-27: deleting is an admin's job; everyone else marks it done.
  const admin = isAdmin(useMe())

  const act = async (row: FollowUpDTO, run: () => Promise<unknown>) => {
    setBusyId(row.id)
    setError(null)
    try {
      await run()
      announceFollowUpsChanged()
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? t('Nur Administratoren dürfen Daten löschen.')
          : t('Nicht gespeichert — bitte erneut versuchen.'),
      )
    } finally {
      setBusyId(null)
    }
  }

  const create = async (f: FollowUpFields) => {
    await api.createFollowUp({ ...subjectIds(subject), ...f, origin: 'manual' })
    setAdding(false)
    announceFollowUpsChanged()
  }
  const save = async (row: FollowUpDTO, f: FollowUpFields) => {
    await api.updateFollowUp(row.id, f)
    setEditing(null)
    announceFollowUpsChanged()
  }

  const open = rows ?? []
  return (
    <div className={compact ? 'space-y-2' : 'space-y-2 border-b border-cockpit-line px-6 py-4'}>
      <div className="flex items-center gap-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
          {t('Wiedervorlagen')} · {open.length}
        </p>
        {!adding && (
          <Button onClick={() => setAdding(true)} className="ml-auto px-3 py-1.5 text-[13px]">
            <BellPlus className="h-4 w-4" />
            {t('Wiedervorlage')}
          </Button>
        )}
      </div>
      {failed && <p className="text-[13px] text-coral-400">{t('Wiedervorlagen konnten nicht geladen werden.')}</p>}
      {adding && (
        <FollowUpForm defaultDate={today} readDate={readDateFromText} onSave={create} onCancel={() => setAdding(false)} />
      )}
      {editing && (
        <FollowUpForm
          key={editing.id}
          initial={editing}
          defaultDate={today}
          onSave={(f) => save(editing, f)}
          onCancel={() => setEditing(null)}
        />
      )}
      {rows !== null && open.length === 0 && !adding && (
        <p className="text-[13px] text-cockpit-faint">{t('Keine offene Wiedervorlage.')}</p>
      )}
      <FollowUpRows
        rows={open}
        today={today}
        busyId={busyId}
        onDone={(row) => {
          if (editing?.id === row.id) setEditing(null)
          void act(row, () => completeFollowUp(row))
        }}
        onCalendar={downloadFollowUpIcs}
        onEdit={(row) => setEditing(row)}
        onDelete={
          admin
            ? (row) => {
                // Removes it for everyone — so it asks first.
                if (window.confirm(t('Wiedervorlage für alle löschen?'))) void act(row, () => api.deleteFollowUp(row.id))
              }
            : undefined
        }
      />
      {error && <p className="text-[12px] text-coral-400">{error}</p>}
    </div>
  )
}
