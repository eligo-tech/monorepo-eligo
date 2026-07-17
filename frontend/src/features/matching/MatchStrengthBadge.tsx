import { cn } from '@/lib/cn'
import type { MatchStrength } from '@/data/types'

const config: Record<MatchStrength, { label: string; cls: string }> = {
  'very-strong': { label: 'Sehr starker Match', cls: 'bg-brand-100 text-brand-700' },
  strong: { label: 'Starker Match', cls: 'bg-brand-50 text-brand-600' },
  moderate: { label: 'Solider Match', cls: 'bg-sky-50 text-sky-600' },
  weak: { label: 'Schwacher Match', cls: 'bg-amber-50 text-accent-600' },
}

export function MatchStrengthBadge({ strength }: { strength: MatchStrength }) {
  const { label, cls } = config[strength]
  return (
    <span className={cn('shrink-0 rounded-lg px-2.5 py-1 text-[13px] font-semibold', cls)}>
      {label}
    </span>
  )
}