// Ticked proposals from a Zeugnis or Zertifikat → one candidate PATCH.
//
// The PATCH replaces whole lists. Sending `skills: ['Kubernetes']` would
// erase every skill the CV brought in, so each list is merged into what the
// record holds right now, and `base_updated_at` makes the server refuse the
// write if somebody changed the record in between.
//
// Pure on purpose: what lands on the record is decided here, and tested here.

import { t } from '@/i18n'

import type {
  CVFieldDTO,
  CandidateDTO,
  CandidateUpdatePayload,
  EducationDTO,
  WorkRoleDTO,
} from '@/api/types'

export type MergeBase = Pick<CandidateDTO, 'updated_at' | 'skills' | 'work_history'> & {
  focus_areas?: string[] | null
  other_notes?: string | null
  education?: EducationDTO[] | string[] | null
}

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')

const splitList = (value: string) =>
  value
    .split(';')
    .map((x) => x.trim())
    .filter(Boolean)

/** Append what is not already there (case- and punctuation-insensitive). */
function mergeList(current: string[], added: string[]): string[] | undefined {
  const seen = new Set(current.map(norm))
  const fresh = added.filter((x) => {
    const key = norm(x)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
  return fresh.length ? [...current, ...fresh] : undefined
}

/** "01.03.2019 – 31.12.2023" → ["01.03.2019", "31.12.2023"].
 *  A bare hyphen is not a separator — it is inside every ISO date — and an
 *  open period ("seit 03.2019") has a start and no end. Same rule as the
 *  server's `_RANGE_SPLIT`. */
function splitPeriod(period: string): [string, string] {
  const [start = '', end = ''] = period.split(/\s+-\s+|\s*[–—]\s*|\s+bis\s+(?:zum\s+)?/i)
  return [start.replace(/^(?:seit|ab)\s+/i, '').trim(), end.trim()]
}

/** Legal forms and filler that do not tell two employers apart. */
const LEGAL = new Set(['gmbh', 'ag', 'se', 'kg', 'co', 'mbh', 'ug', 'ohg', 'kgaa', 'ev', 'inc', 'ltd', 'llc', 'holding'])

const companyTokens = (name: string) =>
  name
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((w) => w && !LEGAL.has(w))

/** "Alte Firma" and "Alte Firma GmbH & Co. KG" are one employer; "Firma
 *  Neu" is not. One name must be the other's leading words, legal form aside
 *  — anything fuzzier is for the recruiter in the editor, not a guess here. */
function sameEmployer(a: string, b: string): boolean {
  const [x, y] = [companyTokens(a), companyTokens(b)]
  const [short, long] = x.length <= y.length ? [x, y] : [y, x]
  return short.length > 0 && short.every((w, i) => long[i] === w)
}

export function buildReferencePatch(
  base: MergeBase,
  fields: CVFieldDTO[],
  chosen: Set<string>,
  kind: 'zeugnis' | 'zertifikat',
): CandidateUpdatePayload {
  const value = (name: string) => fields.find((f) => f.field === name)?.value ?? ''
  const picked = (name: string) => chosen.has(name) && value(name) !== ''
  const patch: CandidateUpdatePayload = {}

  if (picked('skills')) {
    const merged = mergeList(base.skills ?? [], splitList(value('skills')))
    if (merged) patch.skills = merged
  }

  if (kind === 'zeugnis') {
    if (picked('tasks')) {
      const merged = mergeList(base.focus_areas ?? [], splitList(value('tasks')))
      if (merged) patch.focus_areas = merged
    }

    // One position per Zeugnis — added only if the CV did not already bring
    // that employer in. Matching is on the name; anything fuzzier is the
    // recruiter's call in the editor, not a guess here.
    if (picked('employer')) {
      const employer = value('employer')
      const known = (base.work_history ?? []).some(
        (r) => r.company && sameEmployer(r.company, employer),
      )
      if (!known) {
        const [start, end] = picked('period') ? splitPeriod(value('period')) : ['', '']
        const role: WorkRoleDTO = {
          title: picked('role_title') ? value('role_title') : '',
          company: employer,
          location: '',
          start_date: start,
          end_date: end,
          highlights: [],
        }
        patch.work_history = [...(base.work_history ?? []), role]
      }
    }

    // What a Zeugnis says about the person goes into the notes, attributed to
    // the Zeugnis it came from. The grade is labelled as what it is.
    const source = `${t('Zeugnis')} ${value('employer') || t('ohne Arbeitgeber')}`
    const lines: string[] = []
    if (picked('assessment_quote')) {
      lines.push(`${source} · ${t('Leistungsbeurteilung')}: „${value('assessment_quote')}“`)
    }
    if (picked('assessment_grade')) {
      lines.push(
        `${source} · ${t('Gesamtnote')}: ${value('assessment_grade')} (${t('Interpretation')})`,
      )
    }
    if (picked('leaving_reason')) {
      lines.push(`${source} · ${t('Beendigung')}: ${value('leaving_reason')}`)
    }
    const current = base.other_notes ?? ''
    const fresh = lines.filter((line) => !current.includes(line))
    if (fresh.length) {
      patch.other_notes = [current, ...fresh].filter(Boolean).join('\n')
    }
  }

  if (kind === 'zertifikat' && picked('certificate_name')) {
    const name = value('certificate_name')
    const education = base.education ?? []
    const known = education.some((e) =>
      norm(typeof e === 'string' ? e : (e.degree ?? '')) === norm(name),
    )
    if (!known) {
      const entry: EducationDTO = {
        degree: name,
        institution: picked('issuer') ? value('issuer') : '',
        location: '',
        start_date: '',
        end_date: picked('issued_on') ? value('issued_on') : '',
      }
      // Legacy rows hold plain strings. The PATCH takes one shape per list,
      // so an old string entry is carried over as its degree, word for word.
      patch.education = [
        ...education.map((e) => (typeof e === 'string' ? { degree: e } : e)),
        entry,
      ]
    }
  }

  if (Object.keys(patch).length) patch.base_updated_at = base.updated_at
  return patch
}
