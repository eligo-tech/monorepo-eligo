import { describe, expect, it } from 'vitest'

import { t } from '@/i18n'

import type { CVFieldDTO } from '@/api/types'
import { buildReferencePatch, type MergeBase } from './referenceMerge'

const field = (name: string, value: string, extra: Partial<CVFieldDTO> = {}): CVFieldDTO => ({
  field: name,
  label: name,
  value,
  confidence: 0.9,
  needs_review: false,
  evidence: value,
  interpretation: false,
  ...extra,
})

const base: MergeBase = {
  updated_at: '2026-11-09T10:00:00Z',
  skills: ['Java', 'SQL'],
  focus_areas: ['Backend'],
  other_notes: 'Spricht fließend Englisch.',
  work_history: [{ title: 'Entwickler', company: 'Alte Firma GmbH' }],
  education: [{ degree: 'B.Sc. Informatik', institution: 'TU München' }],
}

const all = (fields: CVFieldDTO[]) => new Set(fields.map((f) => f.field))

describe('buildReferencePatch', () => {
  it('merges lists instead of replacing them — the PATCH replaces whole lists', () => {
    const fields = [
      field('skills', 'java; Kubernetes'),
      field('tasks', 'Microservices; Backend'),
    ]
    const patch = buildReferencePatch(base, fields, all(fields), 'zeugnis')

    expect(patch.skills).toEqual(['Java', 'SQL', 'Kubernetes'])
    expect(patch.focus_areas).toEqual(['Backend', 'Microservices'])
  })

  it('always sends the record version it merged into', () => {
    const fields = [field('skills', 'Go')]
    expect(buildReferencePatch(base, fields, all(fields), 'zeugnis').base_updated_at).toBe(
      base.updated_at,
    )
  })

  it('adds the position only when that employer is not already in the career history', () => {
    const fields = [
      field('employer', 'Muster Software GmbH'),
      field('role_title', 'Full-Stack-Entwickler'),
      field('period', '01.03.2019 – 31.12.2023'),
    ]
    const patch = buildReferencePatch(base, fields, all(fields), 'zeugnis')
    expect(patch.work_history).toEqual([
      ...base.work_history,
      {
        title: 'Full-Stack-Entwickler',
        company: 'Muster Software GmbH',
        location: '',
        start_date: '01.03.2019',
        end_date: '31.12.2023',
        highlights: [],
      },
    ])

    const known = [field('employer', 'alte firma gmbh')]
    expect(buildReferencePatch(base, known, all(known), 'zeugnis').work_history).toBeUndefined()
  })

  it('writes the assessment to the notes, the grade marked as an interpretation', () => {
    const fields = [
      field('employer', 'Muster Software GmbH'),
      field('assessment_quote', 'stets zu unserer vollsten Zufriedenheit'),
      field('assessment_grade', 'sehr gut', { interpretation: true, needs_review: true }),
      field('leaving_reason', 'auf eigenen Wunsch'),
    ]
    // Employer not ticked: it still names the Zeugnis in the note.
    const chosen = new Set(['assessment_quote', 'assessment_grade', 'leaving_reason'])
    const notes = buildReferencePatch(base, fields, chosen, 'zeugnis').other_notes!

    expect(notes.startsWith('Spricht fließend Englisch.\n')).toBe(true)
    expect(notes).toContain(`${t('Zeugnis')} Muster Software GmbH`)
    expect(notes).toContain('„stets zu unserer vollsten Zufriedenheit“')
    expect(notes).toContain(`sehr gut (${t('Interpretation')})`)
    expect(notes).toContain('auf eigenen Wunsch')
  })

  it('does not write the same note twice when a Zeugnis is confirmed again', () => {
    const fields = [field('leaving_reason', 'auf eigenen Wunsch')]
    const once = buildReferencePatch(base, fields, all(fields), 'zeugnis')
    const twice = buildReferencePatch(
      { ...base, other_notes: once.other_notes },
      fields,
      all(fields),
      'zeugnis',
    )
    expect(twice.other_notes).toBeUndefined()
  })

  it('a Zertifikat becomes a qualification, once', () => {
    const fields = [
      field('certificate_name', 'Certified Kubernetes Administrator (CKA)'),
      field('issuer', 'The Linux Foundation'),
      field('issued_on', '15.06.2022'),
    ]
    const patch = buildReferencePatch(base, fields, all(fields), 'zertifikat')
    expect(patch.education).toEqual([
      ...base.education!,
      {
        degree: 'Certified Kubernetes Administrator (CKA)',
        institution: 'The Linux Foundation',
        location: '',
        start_date: '',
        end_date: '15.06.2022',
      },
    ])
    const again = buildReferencePatch(
      { ...base, education: patch.education as MergeBase['education'] },
      fields,
      all(fields),
      'zertifikat',
    )
    expect(again.education).toBeUndefined()
  })

  it('keeps a legacy plain-text education entry, word for word', () => {
    const fields = [field('certificate_name', 'AWS Solutions Architect')]
    const patch = buildReferencePatch(
      { ...base, education: ['Abitur, Gymnasium Gersthofen'] },
      fields,
      all(fields),
      'zertifikat',
    )
    expect(patch.education).toEqual([
      { degree: 'Abitur, Gymnasium Gersthofen' },
      { degree: 'AWS Solutions Architect', institution: '', location: '', start_date: '', end_date: '' },
    ])
  })

  it('splits a period only between its dates, never inside an ISO date', () => {
    const iso = [field('employer', 'Neu AG'), field('period', '2019-03-01 – 2023-12-31')]
    expect(buildReferencePatch(base, iso, all(iso), 'zeugnis').work_history?.at(-1)).toMatchObject({
      start_date: '2019-03-01',
      end_date: '2023-12-31',
    })
    const open = [field('employer', 'Neu AG'), field('period', 'seit 03.2019')]
    expect(buildReferencePatch(base, open, all(open), 'zeugnis').work_history?.at(-1)).toMatchObject({
      start_date: '03.2019',
      end_date: '',
    })
  })

  it('treats "Alte Firma" and "Alte Firma GmbH" as the same employer', () => {
    const fields = [field('employer', 'Alte Firma')]
    expect(buildReferencePatch(base, fields, all(fields), 'zeugnis').work_history).toBeUndefined()
    const longer = [field('employer', 'Alte Firma Holding GmbH & Co. KG')]
    expect(
      buildReferencePatch(base, longer, all(longer), 'zeugnis').work_history,
    ).toBeUndefined()
    // A different company that merely shares a word is still different.
    const other = [field('employer', 'Firma Neu GmbH')]
    expect(buildReferencePatch(base, other, all(other), 'zeugnis').work_history).toHaveLength(2)
  })

  it('sends nothing that was not ticked', () => {
    const fields = [field('skills', 'Kubernetes'), field('tasks', 'Betrieb')]
    const patch = buildReferencePatch(base, fields, new Set(['tasks']), 'zeugnis')
    expect(patch.skills).toBeUndefined()
    expect(Object.keys(patch).sort()).toEqual(['base_updated_at', 'focus_areas'])
  })
})
