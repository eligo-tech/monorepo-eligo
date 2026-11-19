// The workspace's header icon (ELI-55) as an object URL, or null for the
// Eligo mark. Read from /branding (per workspace, in the database), fetched
// with the session token like the cover-sheet logo, so it is a blob URL the
// <img> shows — never a public link. Re-read when Einstellungen changes it.

import { useEffect, useState } from 'react'

import { api } from '@/api/client'

/** Fired by the branding panel after an upload or a removal. */
export const BRANDING_CHANGED = 'eligo:branding-changed'

export function useHeaderIcon(): string | null {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    let current: string | null = null
    // Only the newest read may set the icon: an upload's re-read can finish
    // before the first one, which would otherwise put the old icon back.
    let latest = 0
    const load = async () => {
      const mine = ++latest
      // Demo mode or an expired session: the Eligo mark, not an error.
      const branding = await api.branding().catch(() => null)
      const blob = branding?.has_header_icon ? await api.brandingHeaderIcon().catch(() => null) : null
      if (!live || mine !== latest) return
      const next = blob ? URL.createObjectURL(blob) : null
      if (current) URL.revokeObjectURL(current)
      current = next
      setUrl(next)
    }
    void load()
    const onChange = () => void load()
    window.addEventListener(BRANDING_CHANGED, onChange)
    return () => {
      live = false
      window.removeEventListener(BRANDING_CHANGED, onChange)
      if (current) URL.revokeObjectURL(current)
    }
  }, [])

  return url
}
