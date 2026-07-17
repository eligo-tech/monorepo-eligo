import { cn } from '@/lib/cn'

interface AvatarProps {
  initials: string
  tone?: string
  size?: 'sm' | 'md' | 'lg'
}

const sizes = {
  sm: 'h-9 w-9 text-xs',
  md: 'h-11 w-11 text-sm',
  lg: 'h-12 w-12 text-base',
}

/** Circular initials avatar used in lists, cards and headers. */
export function Avatar({ initials, tone = 'bg-brand-500', size = 'md' }: AvatarProps) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white',
        sizes[size],
        tone,
      )}
    >
      {initials}
    </span>
  )
}