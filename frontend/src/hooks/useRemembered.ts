import { useEffect, useState } from 'react'

/** A boolean the browser remembers — a closed panel stays closed.
 *
 *  Lifted out of `MandateDrawer`, which had it first, when the process cards
 *  needed the same thing: a collapse that forgets itself on reload is a
 *  collapse you stop using.
 *
 *  Storage can throw in a private window, so the DEFAULT survives that rather
 *  than the screen.
 */
export function useRemembered(key: string, fallback: boolean) {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored === null ? fallback : stored === 'true'
    } catch {
      return fallback
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(key, String(value))
    } catch {
      /* private window — the choice simply does not persist */
    }
  }, [key, value])
  return [value, setValue] as const
}
