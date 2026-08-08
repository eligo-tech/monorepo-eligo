// Scroll-snap carousel behind the 01 panel — the four dots in the mockup.
// Native scroll-snap does the paging, so trackpad swipe, shift-scroll and the
// dots all work without a gesture library.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Carousel({
  count,
  children,
  ariaLabel,
}: {
  count: number
  children: ReactNode
  ariaLabel: string
}) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(0)

  // Derive the active dot from scroll position rather than tracking it
  // separately, so swiping and dot clicks can never disagree.
  const onScroll = useCallback(() => {
    const el = trackRef.current
    if (!el) return
    const index = Math.round(el.scrollLeft / el.clientWidth)
    setActive(Math.max(0, Math.min(count - 1, index)))
  }, [count])

  const goTo = (index: number) => {
    const el = trackRef.current
    if (!el) return
    el.scrollTo({ left: index * el.clientWidth, behavior: 'smooth' })
  }

  useEffect(() => {
    const el = trackRef.current
    if (!el) return
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [onScroll])

  return (
    <div>
      <div
        ref={trackRef}
        role="group"
        aria-label={ariaLabel}
        className="no-scrollbar flex snap-x snap-mandatory overflow-x-auto"
      >
        {children}
      </div>

      <div className="mt-4 flex items-center justify-center gap-2">
        {Array.from({ length: count }, (_, i) => (
          <button
            key={i}
            type="button"
            onClick={() => goTo(i)}
            aria-label={`Panel ${i + 1} von ${count}`}
            aria-current={i === active}
            className={cn(
              'h-1.5 rounded-full transition-all',
              i === active ? 'w-7 bg-mint-500' : 'w-1.5 bg-[#2e3128] hover:bg-[#41453a]',
            )}
          />
        ))}
      </div>
    </div>
  )
}

/** One full-width slide inside a Carousel. */
export function Slide({ children }: { children: ReactNode }) {
  return <div className="w-full shrink-0 snap-start">{children}</div>
}
