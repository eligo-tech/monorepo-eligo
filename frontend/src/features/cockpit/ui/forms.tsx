// Cockpit form and overlay primitives.
//
// Every input in the cockpit is a dark inset field with a mono uppercase label —
// one place to change so no screen hand-rolls its own. Overlay shells (Drawer,
// Modal) own the backdrop, Escape handling and scroll lock.

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'

/** Shared field chrome: dark inset, hairline that brightens on focus. */
export const FIELD =
  'w-full rounded-lg border border-cockpit-line bg-cockpit-inset px-2.5 py-1.5 text-[14px] text-cockpit-text placeholder:text-cockpit-faint outline-none transition-colors focus:border-mint-600'

export function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
      {children}
    </span>
  )
}

/** Section label above a group of fields. */
export function GroupLabel({ children }: { children: ReactNode }) {
  return (
    <h4 className="mb-2.5 font-mono text-[12px] uppercase tracking-[0.12em] text-cockpit-dim">
      {children}
    </h4>
  )
}

export function TextInput({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: 'text' | 'email' | 'number'
}) {
  return (
    <label className="block min-w-0">
      <FieldLabel>{label}</FieldLabel>
      <input
        type={type}
        inputMode={type === 'number' ? 'numeric' : undefined}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={cn(FIELD, type === 'number' && 'font-mono')}
      />
    </label>
  )
}

export function SelectInput({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <label className="block min-w-0">
      <FieldLabel>{label}</FieldLabel>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={FIELD}>
        {options.map((o) => (
          // Dark surface for the native dropdown list, which ignores Tailwind.
          <option key={o.value} value={o.value} className="bg-cockpit-surface">
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function TextArea({
  value,
  onChange,
  rows = 4,
  placeholder,
  className,
}: {
  value: string
  onChange: (v: string) => void
  rows?: number
  placeholder?: string
  className?: string
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      rows={rows}
      placeholder={placeholder}
      className={cn(FIELD, 'leading-relaxed', className)}
    />
  )
}

/** Bare input for dense grids (role/education cards) — placeholder as the label. */
export function MiniInput({
  value,
  onChange,
  placeholder,
  span2,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  span2?: boolean
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={cn(FIELD, 'text-[13px]', span2 && 'col-span-2')}
    />
  )
}

const BTN_BASE =
  'flex items-center gap-1.5 rounded-xl px-4 py-2 text-[14px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40'

const BTN_TONES = {
  primary: 'border border-mint-600 bg-mint-800/40 text-mint-300 hover:bg-mint-800/70',
  ghost: 'border border-cockpit-line text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text',
  danger: 'border border-coral-600 bg-coral-800/25 text-coral-300 hover:bg-coral-800/50',
} as const

export function Button({
  children,
  onClick,
  tone = 'ghost',
  disabled,
  className,
  title,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  tone?: keyof typeof BTN_TONES
  disabled?: boolean
  className?: string
  title?: string
  type?: 'button' | 'submit'
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(BTN_BASE, BTN_TONES[tone], className)}
    >
      {children}
    </button>
  )
}

/** Editable list of short strings (skills, languages). */
export function TagInput({
  tags,
  onChange,
  placeholder,
}: {
  tags: string[]
  onChange: (v: string[]) => void
  placeholder?: string
}) {
  const [input, setInput] = useState('')
  const add = () => {
    const v = input.trim()
    if (v && !tags.includes(v)) onChange([...tags, v])
    setInput('')
  }
  return (
    <div className="rounded-lg border border-cockpit-line bg-cockpit-inset p-2 transition-colors focus-within:border-mint-600">
      <div className="flex flex-wrap gap-1.5">
        {tags.map((t, i) => (
          <span
            key={`${t}-${i}`}
            className="flex items-center gap-1 rounded-md border border-cockpit-line bg-white/[0.04] px-2 py-0.5 font-mono text-[12px] text-cockpit-dim"
          >
            {t}
            <button
              type="button"
              onClick={() => onChange(tags.filter((_, j) => j !== i))}
              className="text-cockpit-faint transition-colors hover:text-coral-400"
              aria-label={`${t} entfernen`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              add()
            } else if (e.key === 'Backspace' && !input && tags.length) {
              onChange(tags.slice(0, -1))
            }
          }}
          onBlur={add}
          placeholder={placeholder}
          className="min-w-[130px] flex-1 bg-transparent px-1 text-[13px] text-cockpit-text outline-none placeholder:text-cockpit-faint"
        />
      </div>
    </div>
  )
}

/** Dashed "add another" affordance under a repeatable list. */
export function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-cockpit-line py-2 font-mono text-[12px] text-cockpit-faint transition-colors hover:border-mint-600 hover:text-mint-400"
    >
      {label}
    </button>
  )
}

/** Locks background scroll and closes on Escape — shared by Drawer and Modal. */
function useOverlay(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [onClose])
}

/** Right-hand sliding panel. */
export function Drawer({
  onClose,
  wide,
  children,
}: {
  onClose: () => void
  wide?: boolean
  children: ReactNode
}) {
  useOverlay(onClose)
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        aria-label="Schließen"
        onClick={onClose}
        className="absolute inset-0 bg-black/65 backdrop-blur-[2px]"
      />
      <div
        className={cn(
          'relative flex h-full w-full flex-col border-l border-cockpit-line bg-cockpit-bg transition-[max-width] duration-300',
          wide ? 'max-w-[1600px]' : 'max-w-[1180px]',
        )}
      >
        {children}
      </div>
    </div>
  )
}

/** Centred dialog. */
export function Modal({
  onClose,
  children,
  className,
}: {
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  useOverlay(onClose)
  const ref = useRef<HTMLDivElement>(null)
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-6 backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (!ref.current?.contains(e.target as Node)) onClose()
      }}
    >
      <div
        ref={ref}
        className={cn(
          'flex max-h-[85vh] w-full flex-col overflow-hidden rounded-panel border border-cockpit-line bg-cockpit-surface shadow-panel',
          className ?? 'max-w-2xl',
        )}
      >
        {children}
      </div>
    </div>
  )
}

/** Icon-only close button for overlay headers. */
export function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="Schließen"
      className="rounded-xl border border-cockpit-line p-2 text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
    >
      <X className="h-5 w-5" />
    </button>
  )
}
