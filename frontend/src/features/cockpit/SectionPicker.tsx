// Section navigation.
//
// Replaces the arrow-cluster Navigator. Arrows required you to know the screen
// order and to page through screens you did not want; a named list says where
// you can go and takes you there in one action.

import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/cn'

export interface SectionOption<K extends string> {
  key: K
  label: string
  /** Screens that exist in the nav but have no implementation yet. */
  placeholder?: boolean
}

export function SectionPicker<K extends string>({
  options,
  value,
  onChange,
}: {
  options: SectionOption<K>[]
  value: K
  onChange: (key: K) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const current = options.find((o) => o.key === value)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-2.5 rounded-xl border border-cockpit-line bg-cockpit-inset px-3 py-2 text-[14px] transition-colors hover:border-cockpit-edge"
      >
        <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
          Section
        </span>
        <span className="text-cockpit-text">{current?.label ?? '—'}</span>
        <ChevronDown
          className={cn(
            'h-4 w-4 text-cockpit-faint transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <ul
          role="listbox"
          className="absolute right-0 z-50 mt-1 min-w-[15rem] overflow-hidden rounded-xl border border-cockpit-line bg-cockpit-surface shadow-panel"
        >
          {options.map((option) => (
            <li key={option.key}>
              <button
                type="button"
                role="option"
                aria-selected={option.key === value}
                onClick={() => {
                  onChange(option.key)
                  setOpen(false)
                }}
                className={cn(
                  'flex w-full items-center gap-2.5 px-3 py-2 text-left text-[14px] transition-colors hover:bg-white/[0.04]',
                  option.key === value ? 'text-cockpit-text' : 'text-cockpit-dim',
                )}
              >
                <Check
                  className={cn(
                    'h-4 w-4 shrink-0',
                    option.key === value ? 'text-mint-400' : 'text-transparent',
                  )}
                />
                {option.label}
                {option.placeholder && (
                  <span className="ml-auto font-mono text-[11px] text-cockpit-faint">
                    bald
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
