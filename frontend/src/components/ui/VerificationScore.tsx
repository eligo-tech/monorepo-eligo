import { cn } from '@/lib/cn'

/**
 * Verification confidence indicator.
 * The dot + colour encode how much of the record is verified against a real
 * source — the product's core trust signal. >=90 green, >=75 amber, else red.
 */
export function VerificationScore({ value }: { value: number }) {
  const tone =
    value >= 90 ? 'text-brand-600' : value >= 75 ? 'text-accent-600' : 'text-rose-500'
  const dot =
    value >= 90 ? 'bg-brand-500' : value >= 75 ? 'bg-accent-500' : 'bg-rose-500'
  return (
    <span className={cn('inline-flex items-center gap-2 text-sm font-semibold', tone)}>
      <span className={cn('h-2 w-2 rounded-full', dot)} />
      {value}%
    </span>
  )
}