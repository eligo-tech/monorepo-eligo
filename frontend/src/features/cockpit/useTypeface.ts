// The Jet · Mono · Heli switch from the command bar.
//
// Writes a data attribute on <html>; index.css maps it to the --font-ui /
// --font-mono vars that Tailwind's font-sans and font-mono resolve through, so
// no component has to know which face is active.

import { useEffect, useState } from 'react'

export type Typeface = 'jet' | 'mono' | 'heli'

const STORAGE_KEY = 'eligo.cockpit.typeface'
const isTypeface = (v: string | null): v is Typeface =>
  v === 'jet' || v === 'mono' || v === 'heli'

export function useTypeface(): [Typeface, (t: Typeface) => void] {
  const [typeface, setTypeface] = useState<Typeface>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return isTypeface(stored) ? stored : 'jet'
  })

  useEffect(() => {
    document.documentElement.dataset.typeface = typeface
    localStorage.setItem(STORAGE_KEY, typeface)
  }, [typeface])

  return [typeface, setTypeface]
}
