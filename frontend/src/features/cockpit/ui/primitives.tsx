// Small cockpit primitives: surfaces, section chrome, chips, and figures.
// Larger widgets (Gauge, ProcessStepper, ScoreBar, Carousel) have their own files.

import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import type { Figure as FigureModel, Provenance } from '../data/types'

/** The standard dark card surface. */
export function Panel({
  children,
  className,
  tone = 'surface',
}: {
  children: ReactNode
  className?: string
  tone?: 'surface' | 'raised' | 'inset'
}) {
  return (
    <div
      className={cn(
        'rounded-panel border border-cockpit-line',
        tone === 'surface' && 'bg-cockpit-surface shadow-panel',
        tone === 'raised' && 'bg-cockpit-raised',
        tone === 'inset' && 'bg-cockpit-inset',
        className,
      )}
    >
      {children}
    </div>
  )
}

const BADGE_TONES = {
  mint: 'border-mint-700 bg-mint-800/40 text-mint-400',
  gold: 'border-gold-600 bg-gold-800/40 text-gold-400',
  coral: 'border-coral-600 bg-coral-800/40 text-coral-400',
  lav: 'border-lav-600 bg-lav-800/40 text-lav-400',
} as const

export type Tone = keyof typeof BADGE_TONES

/**
 * Numbered section header: mono index badge, title, right-hand hint, hairline.
 * Pass `id` to give the section a stable anchor for deep links.
 */
export function SectionHeader({
  index,
  title,
  hint,
  tone = 'mint',
  icon,
  id,
}: {
  index?: string
  title: string
  hint?: ReactNode
  tone?: Tone
  icon?: ReactNode
  id?: string
}) {
  return (
    <div id={id} className="scroll-mt-24">
      <div className="flex items-baseline gap-4">
        {index && (
          <span
            className={cn(
              'rounded-md border px-2 py-0.5 font-mono text-[13px] font-medium',
              BADGE_TONES[tone],
            )}
          >
            {index}
          </span>
        )}
        {icon && (
          <span className={cn('rounded-md border p-1.5', BADGE_TONES[tone])}>{icon}</span>
        )}
        <h2 className="text-[22px] font-semibold tracking-tight text-cockpit-text">{title}</h2>
        {hint && (
          <span className="ml-auto font-mono text-[13px] text-cockpit-faint">{hint}</span>
        )}
      </div>
      <div className="mt-3 h-px bg-cockpit-line" />
    </div>
  )
}

/** Mono pill used for skills, sub-labels and metadata. */
export function Chip({
  children,
  tone,
  className,
}: {
  children: ReactNode
  tone?: Tone
  className?: string
}) {
  return (
    <span
      className={cn(
        'rounded-md border px-2 py-0.5 font-mono text-[12px] leading-5',
        tone
          ? BADGE_TONES[tone]
          : 'border-cockpit-line bg-white/[0.03] text-cockpit-dim',
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Uppercase category tag on the right of an action row. */
export function Tag({ children, tone }: { children: ReactNode; tone: Tone }) {
  return (
    <span
      className={cn(
        'rounded-md border px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.08em]',
        BADGE_TONES[tone],
      )}
    >
      {children}
    </span>
  )
}

/** Small all-caps mono label, as above IST / POTENZIAL / PROGNOSE. */
export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        'font-mono text-[11px] uppercase tracking-[0.14em] text-cockpit-faint',
        className,
      )}
    >
      {children}
    </span>
  )
}

/**
 * Marks a figure the backend cannot yet vouch for.
 *
 * The product invariant is that every displayed claim is evidence-backed; this
 * degree sign is how a demo number says so out loud instead of passing itself off
 * as verified. Live values render nothing.
 */
export function ProvenanceMark({
  provenance,
  source,
}: {
  provenance: Provenance
  source?: string
}) {
  if (provenance === 'live') return null
  return (
    <sup
      title={source ?? 'Demo-Wert — nicht gegen eine Quelle geprüft'}
      className="ml-0.5 cursor-help select-none align-super font-mono text-[0.7em] text-cockpit-faint"
      aria-label="Demo-Wert, nicht verifiziert"
    >
      °
    </sup>
  )
}

const de = (n: number) => n.toLocaleString('de-DE')

/** Formats a Figure and appends its provenance mark. */
export function Figure({
  figure,
  format = de,
  prefix,
  suffix,
  className,
}: {
  figure: FigureModel
  format?: (n: number) => string
  prefix?: string
  suffix?: string
  className?: string
}) {
  return (
    <span className={cn('font-mono', className)}>
      {prefix}
      {format(figure.value)}
      {suffix}
      <ProvenanceMark provenance={figure.provenance} source={figure.source} />
    </span>
  )
}

/** €-prefixed figure with the mockup's thin space between symbol and number. */
export function Money({
  figure,
  className,
  compact = false,
}: {
  figure: FigureModel
  className?: string
  compact?: boolean
}) {
  const format = compact
    ? (n: number) => (Math.abs(n) >= 1000 ? `${Math.round(n / 1000)}k` : de(n))
    : de
  return <Figure figure={figure} format={format} prefix="€ " className={className} />
}

/** Segmented control — Jahr / Quartal / Monat / Tag, and the typeface switch. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
  className,
}: {
  options: { key: T; label: string }[]
  value: T
  onChange: (v: T) => void
  size?: 'sm' | 'md'
  className?: string
}) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1 rounded-xl border border-cockpit-line bg-cockpit-inset',
        size === 'md' ? 'p-1.5' : 'p-1',
        className,
      )}
    >
      {options.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          aria-pressed={key === value}
          className={cn(
            'rounded-lg transition-colors',
            size === 'md' ? 'px-5 py-2 text-[15px]' : 'px-2.5 py-1 font-mono text-[12px]',
            key === value
              ? 'bg-white/[0.07] text-cockpit-text shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
              : 'text-cockpit-dim hover:text-cockpit-text',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  )
}


/**
 * Renders body copy with record references (#K-0731, #A-238) picked out in mono,
 * the way the mockup's signal lines read.
 */
export function WithRefs({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/(#[A-Z]-\d+)/g)
  return (
    <span className={className}>
      {parts.map((part, i) =>
        /^#[A-Z]-\d+$/.test(part) ? (
          <span key={i} className="font-mono text-cockpit-text">
            {part}
          </span>
        ) : (
          part
        ),
      )}
    </span>
  )
}
