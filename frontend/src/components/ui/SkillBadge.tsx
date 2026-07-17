import { cn } from '@/lib/cn'
import type { SkillTone } from '@/data/types'

const tones: Record<SkillTone, string> = {
  purple: 'bg-violet-50 text-violet-600',
  coral: 'bg-rose-50 text-rose-500',
  mint: 'bg-brand-50 text-brand-600',
  sky: 'bg-sky-50 text-sky-600',
  neutral: 'bg-slate-100 text-ink-muted',
}

export function SkillBadge({ label, tone }: { label: string; tone: SkillTone }) {
  return (
    <span className={cn('rounded-md px-2 py-0.5 text-xs font-medium', tones[tone])}>{label}</span>
  )
}

/** Small grey "+N" counter chip. */
export function CountChip({ n }: { n: number }) {
  return (
    <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-ink-muted">
      +{n}
    </span>
  )
}