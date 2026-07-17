/** eligo-tech wordmark used in the sidebar header. */
export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500 shadow-sm">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none">
          <path
            d="M6 7.5h11M6 12h9M6 16.5h11"
            stroke="white"
            strokeWidth="2.2"
            strokeLinecap="round"
          />
        </svg>
      </span>
      <span className="text-[17px] font-semibold tracking-tight text-white">
        eligo<span className="text-brand-300">-tech</span>
      </span>
    </div>
  )
}