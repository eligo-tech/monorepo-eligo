// The Kandidatenauswertung inside a process card: how this candidate measures
// against THIS mandate.
//
// Three rules the layout follows, from the recruiter's own document
// (data/examples/KandidatenInfo.txt):
//
//  1. Risks are never folded into prose. "Gehalt am oberen Rand" and "Team-Fit
//     im Erstgespräch prüfen" are the things a recruiter must say out loud
//     before the client does, so they get their own column opposite the
//     strengths rather than a sentence at the end of a paragraph.
//  2. The client text is kept apart and labelled. Section C is written for the
//     client's eyes; mixing it with internal notes is how an internal risk
//     ends up in a presentation.
//  3. The score carries its provenance. "8/10" without "CV + Gesprächs-
//     transkript (18.09.2026)" is an opinion with no source, which is exactly
//     what this product refuses to display.

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { cn } from '@/lib/cn'
import { scoreTone } from './ScoreBar'
import { Chip, Label } from './primitives'
import type { CandidateAssessment } from '../data/types'

const TONE_TEXT = {
  mint: 'text-mint-300',
  gold: 'text-gold-300',
  coral: 'text-coral-300',
} as const

/** "18.09.2026" — the day the assessment was made, in German order. */
function dateDe(iso: string): string {
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Europe/Berlin',
  })
}

function Bullets({
  title,
  items,
  tone,
}: {
  title: string
  items: string[]
  tone: 'mint' | 'coral'
}) {
  if (items.length === 0) return null
  return (
    <div className="min-w-0 flex-1 space-y-2">
      <Label>{title}</Label>
      <ul className="space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 text-[14px] leading-relaxed text-cockpit-dim">
            <span className={cn('mt-[7px] h-1 w-1 shrink-0 rounded-full', tone === 'mint' ? 'bg-mint-400' : 'bg-coral-400')} />
            <span className="min-w-0">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** "Grundlage: CV + Transkript (18.09.2026)".
 *
 *  The date is appended only when the basis line does not already carry one —
 *  the recruiter's own template writes it inside the sentence, and repeating
 *  it reads as two different dates at a glance. */
function provenance(assessment: CandidateAssessment): string | null {
  const { basis, assessedAt } = assessment
  const when = assessedAt ? dateDe(assessedAt) : null
  if (!basis) return when ? `Bewertet am ${when}` : null
  const alreadyDated = !!when && basis.includes(when)
  return `Grundlage: ${basis}${when && !alreadyDated ? ` · ${when}` : ''}`
}

export function AssessmentPanel({ assessment }: { assessment: CandidateAssessment }) {
  const [showClientText, setShowClientText] = useState(false)
  const { fitScore } = assessment
  const tone = fitScore === null ? 'gold' : scoreTone(fitScore * 10)
  // The Kurzfazit is the first paragraph; the rest is the argument behind it.
  const [headline, ...rest] = (assessment.verdict ?? '').split('\n\n')

  return (
    <div className="mt-6 border-t border-cockpit-line pt-5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <Label>Passung zum Mandat</Label>
        {fitScore !== null && (
          <span className={cn('font-mono text-[20px] font-semibold', TONE_TEXT[tone])}>
            {fitScore}
            <span className="text-[14px] text-cockpit-faint"> / 10</span>
          </span>
        )}
        {provenance(assessment) && (
          <span className="font-mono text-[12px] text-cockpit-faint">
            {provenance(assessment)}
          </span>
        )}
      </div>

      {headline && (
        <p className="mt-3 max-w-4xl text-[15px] leading-relaxed text-cockpit-text">
          {headline}
        </p>
      )}

      {(assessment.strengths.length > 0 || assessment.risks.length > 0) && (
        <div className="mt-5 flex flex-wrap gap-x-10 gap-y-5">
          <Bullets title="Stärken" items={assessment.strengths} tone="mint" />
          <Bullets title="Lücken / Risiken" items={assessment.risks} tone="coral" />
        </div>
      )}

      {assessment.technologies.length > 0 && (
        <div className="mt-5 space-y-2">
          <Label>Relevante Technologien</Label>
          <div className="flex flex-wrap gap-1.5">
            {assessment.technologies.map((tech) => (
              <Chip key={tech}>{tech}</Chip>
            ))}
          </div>
        </div>
      )}

      {(rest.length > 0 || assessment.clientSummary) && (
        <div className="mt-5 space-y-3">
          <button
            type="button"
            onClick={() => setShowClientText((open) => !open)}
            className="flex items-center gap-1.5 font-mono text-[12px] uppercase tracking-[0.08em] text-cockpit-faint transition-colors hover:text-cockpit-text"
          >
            {showClientText ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            Begründung & Kundentext
          </button>
          {showClientText && (
            <div className="max-w-4xl space-y-4">
              {rest.map((paragraph, i) => (
                <p key={i} className="text-[14px] leading-relaxed text-cockpit-dim">
                  {paragraph}
                </p>
              ))}
              {assessment.clientSummary && (
                <div className="rounded-xl border border-lav-600/50 bg-lav-800/25 p-4">
                  <Label className="text-lav-400">Für die Kundenvorstellung</Label>
                  <p className="mt-2 text-[14px] leading-relaxed text-cockpit-dim">
                    {assessment.clientSummary}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
