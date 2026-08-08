// The arrow cluster in the top-right corner of every mockup.
//
// ←/→ switch screen, ↑/↓ jump to the previous/next section of the current screen,
// the centre dot returns to the top. Bound to the keyboard arrows too, which is
// what makes the surface feel like a cockpit rather than a web page.

import { useEffect } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from 'lucide-react'
import { cn } from '@/lib/cn'

export interface NavigatorProps {
  onPrevScreen: () => void
  onNextScreen: () => void
  onPrevSection: () => void
  onNextSection: () => void
  onReset: () => void
  canPrevScreen: boolean
  canNextScreen: boolean
}

const BTN =
  'flex h-7 w-7 items-center justify-center rounded-md border border-cockpit-line bg-cockpit-inset text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text disabled:opacity-30 disabled:hover:border-cockpit-line disabled:hover:text-cockpit-dim'

export function Navigator({
  onPrevScreen,
  onNextScreen,
  onPrevSection,
  onNextSection,
  onReset,
  canPrevScreen,
  canNextScreen,
}: NavigatorProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Never hijack arrows while the recruiter is typing in the search field.
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) {
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return

      const handler = {
        ArrowLeft: onPrevScreen,
        ArrowRight: onNextScreen,
        ArrowUp: onPrevSection,
        ArrowDown: onNextSection,
      }[e.key]

      if (handler) {
        e.preventDefault()
        handler()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onPrevScreen, onNextScreen, onPrevSection, onNextSection])

  return (
    <div className="flex flex-col items-center gap-1" aria-label="Navigation">
      <button type="button" className={BTN} onClick={onPrevSection} aria-label="Abschnitt zurück">
        <ArrowUp className="h-3.5 w-3.5" />
      </button>

      <div className="flex items-center gap-1">
        <button
          type="button"
          className={BTN}
          onClick={onPrevScreen}
          disabled={!canPrevScreen}
          aria-label="Vorheriger Bereich"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </button>

        <button
          type="button"
          className={cn(BTN, 'text-[10px]')}
          onClick={onReset}
          aria-label="Zum Anfang"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
        </button>

        <button
          type="button"
          className={cn(BTN, canNextScreen && 'border-coral-600 text-coral-400')}
          onClick={onNextScreen}
          disabled={!canNextScreen}
          aria-label="Nächster Bereich"
        >
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>

      <button type="button" className={BTN} onClick={onNextSection} aria-label="Abschnitt weiter">
        <ArrowDown className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
