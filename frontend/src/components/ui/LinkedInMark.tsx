/** Small LinkedIn glyph shown next to sourced candidates.
 *  When an `href` is given it becomes a real link to the profile; the click is
 *  stopped from bubbling so it doesn't also trigger a surrounding row action. */
export function LinkedInMark({ href }: { href?: string }) {
  const glyph = (
    <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] bg-[#0a66c2] text-[9px] font-bold leading-none text-white">
      in
    </span>
  )
  if (!href) return glyph
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      title="LinkedIn-Profil öffnen"
      className="inline-flex shrink-0 transition-opacity hover:opacity-80"
    >
      {glyph}
    </a>
  )
}
