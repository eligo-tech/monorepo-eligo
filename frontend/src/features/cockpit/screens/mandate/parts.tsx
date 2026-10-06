// Shared bits of the job workspace.
//
// The design draws nine panels; the backend can fill three of them today. The
// rest are built as drawn and marked, because the cockpit's rule is that a
// figure we cannot vouch for must never look verified — not that it must be
// hidden. `DemoText` is the prose equivalent of the `°` a Figure carries.

import type { ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { cn } from '@/lib/cn'
import { ProvenanceMark } from '../../ui/primitives'

/** A value the record cannot yet supply, shown as the design shows it. */
export function DemoText({
  children,
  source = 'Demo-Wert — im Datensatz noch nicht erfasst',
  className,
}: {
  children: ReactNode
  source?: string
  className?: string
}) {
  return (
    <span className={className}>
      {children}
      <ProvenanceMark provenance="demo" source={source} />
    </span>
  )
}

/** The hint every not-yet-connected panel carries in its header. */
export const DEMO_HINT = 'Demo · noch nicht angebunden'

/** One labelled line of the Stammdaten block: 88px key, free-flowing value. */
export function StammRow({
  label,
  children,
  sub,
  tone,
}: {
  label: string
  children: ReactNode
  /** Second line under the value — register details, in mono. */
  sub?: ReactNode
  tone?: 'lav'
}) {
  return (
    <div className="border-t border-cockpit-line/70 py-1.5 first:border-t-0">
      <div className="flex gap-3 text-[12.5px]">
        <span className="w-[88px] shrink-0 pt-0.5 font-mono text-[10.5px] uppercase tracking-[0.04em] text-cockpit-faint">
          {label}
        </span>
        <span className={cn('min-w-0 flex-1 break-words', tone === 'lav' && 'text-lav-400')}>
          {children}
        </span>
      </div>
      {sub && (
        <div className="pl-[100px] font-mono text-[11px] leading-6 text-cockpit-faint">
          {sub}
        </div>
      )}
    </div>
  )
}

/** The design's small panel badge: a coloured word before the panel title. */
export function PanelTag({
  children,
  tone = 'mint',
}: {
  children: ReactNode
  tone?: 'mint' | 'gold' | 'coral' | 'lav'
}) {
  const TONES = {
    mint: 'border-mint-600/50 bg-mint-800/30 text-mint-300',
    gold: 'border-gold-600/50 bg-gold-800/30 text-gold-300',
    coral: 'border-coral-600/50 bg-coral-800/30 text-coral-300',
    lav: 'border-lav-600/50 bg-lav-800/30 text-lav-400',
  } as const
  return (
    <span
      className={cn(
        'rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em]',
        TONES[tone],
      )}
    >
      {children}
    </span>
  )
}

/** Panel heading: tag, title, an optional right-aligned note — and, when the
 *  panel can fold, the chevron that folds it.
 *
 *  Same control and same gesture as a process card, deliberately: a mandate
 *  is a column of panels, and a reader who learns to fold one should not
 *  have to work out how each of the others does it. Pass `onToggle` and the
 *  heading grows the button; leave it out and nothing changes.
 *
 *  The whole heading is the hit area, not just the chevron. */
export function PanelHead({
  tag,
  tone,
  title,
  note,
  collapsed,
  onToggle,
}: {
  tag: string
  tone?: 'mint' | 'gold' | 'coral' | 'lav'
  title: ReactNode
  note?: ReactNode
  collapsed?: boolean
  onToggle?: () => void
}) {
  const head = (
    <>
      <PanelTag tone={tone}>{tag}</PanelTag>
      <h3 className="text-[16px] font-semibold text-cockpit-text">{title}</h3>
      {note && (
        <span className="ml-auto font-mono text-[11px] text-cockpit-faint">{note}</span>
      )}
    </>
  )

  if (!onToggle) {
    return <div className="mb-4 flex flex-wrap items-center gap-3">{head}</div>
  }

  const label = collapsed ? 'ausklappen' : 'einklappen'
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      title={label}
      className={cn(
        'group flex w-full flex-wrap items-center gap-3 text-left',
        collapsed ? 'mb-0' : 'mb-4',
      )}
    >
      {head}
      <span
        className={cn(
          'shrink-0 rounded-lg border border-cockpit-line p-1.5 text-cockpit-faint transition-colors group-hover:border-cockpit-edge group-hover:text-cockpit-text',
          note ? '' : 'ml-auto',
        )}
      >
        {collapsed ? (
          <ChevronRight className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
        <span className="sr-only">{label}</span>
      </span>
    </button>
  )
}
