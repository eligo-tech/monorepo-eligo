import { cn } from '@/lib/cn'

/**
 * Tiny indicator of where the current view's data comes from:
 * live API, demo/mock fallback (backend unreachable), or loading.
 */
export function DataSourceBadge({ state }: { state: 'live' | 'demo' | 'loading' }) {
  const config = {
    live: { dot: 'bg-brand-500', text: 'text-brand-600', label: 'Live-API' },
    demo: { dot: 'bg-accent-500', text: 'text-accent-600', label: 'Demo-Daten' },
    loading: { dot: 'bg-ink-faint animate-pulse', text: 'text-ink-muted', label: 'Lädt…' },
  }[state]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-[12px] font-semibold',
        config.text,
      )}
      title={
        state === 'demo'
          ? 'Backend nicht erreichbar — Fallback auf Demo-Daten. Starte das Backend mit ./run.sh.'
          : undefined
      }
    >
      <span className={cn('h-2 w-2 rounded-full', config.dot)} />
      {config.label}
    </span>
  )
}