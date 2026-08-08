// The fixed command bar: wordmark, global search, system status, typeface switch,
// and the navigator cluster.
//
// It also carries the tenant + account controls. Those used to live in TopNav,
// which the cockpit replaces — dropping them would take organisation switching
// and sign-out with it.

import { Search } from 'lucide-react'
import { OrganizationSwitcher, UserButton } from '@clerk/clerk-react'
import { authEnabled } from '@/auth/config'
import { SegmentedControl, StatusChip } from './ui/primitives'
import { Navigator, type NavigatorProps } from './Navigator'
import type { CockpitStatus } from './data/types'
import type { Typeface } from './useTypeface'

const TYPEFACES: { key: Typeface; label: string }[] = [
  { key: 'jet', label: 'Jet' },
  { key: 'mono', label: 'Mono' },
  { key: 'heli', label: 'Heli' },
]

/** Circular gauge mark — the cockpit's own logo. */
function CockpitMark() {
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-full border border-mint-600 text-mint-400">
      <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" aria-hidden>
        <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.4" />
        <path d="M12 12 16 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="12" cy="12" r="1.6" fill="currentColor" />
      </svg>
    </span>
  )
}

export function CommandBar({
  status,
  query,
  onQueryChange,
  typeface,
  onTypefaceChange,
  nav,
}: {
  status: CockpitStatus
  query: string
  onQueryChange: (q: string) => void
  typeface: Typeface
  onTypefaceChange: (t: Typeface) => void
  nav: NavigatorProps
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-cockpit-line bg-cockpit-bg/85 backdrop-blur-md">
      <div className="flex flex-wrap items-center gap-3 px-6 py-3 2xl:flex-nowrap">
        {/* Wordmark */}
        <div className="flex shrink-0 items-center gap-3">
          <CockpitMark />
          <span className="text-[19px] font-semibold tracking-[0.12em] text-cockpit-text">
            COCKPIT
          </span>
          <span className="font-mono text-[13px] text-cockpit-faint">· Personalberatung</span>
        </div>

        {/* Global search */}
        <label className="relative flex min-w-[18rem] flex-1 items-center 2xl:max-w-[30rem]">
          <Search className="pointer-events-none absolute left-4 h-[17px] w-[17px] text-cockpit-faint" />
          <input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Kandidat, Mandat oder Firma suchen …"
            className="w-full rounded-xl border border-cockpit-line bg-cockpit-inset py-2.5 pl-11 pr-4 text-[15px] text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none"
          />
        </label>

        {/* System status */}
        <StatusChip tone="gold">
          Datenlauf fällig · {status.pendingChanges.value} Änderungen
        </StatusChip>
        {status.humanInTheLoop && <StatusChip tone="mint">Human-in-the-Loop aktiv</StatusChip>}

        {/* Tenant + account, or the mockup's static initials chip in demo mode */}
        <div className="flex shrink-0 items-center gap-2.5 rounded-xl border border-cockpit-line bg-cockpit-inset px-3 py-1.5">
          {authEnabled ? (
            <>
              <OrganizationSwitcher
                hidePersonal
                afterSelectOrganizationUrl="/#cockpit"
                afterCreateOrganizationUrl="/#cockpit"
                appearance={{ elements: { rootBox: 'flex items-center' } }}
              />
              <UserButton afterSignOutUrl="/" />
            </>
          ) : (
            <span className="font-mono text-[13px] text-cockpit-dim">{status.initials}</span>
          )}
          <span className="font-mono text-[13px] text-cockpit-dim">
            · Ansprache: <span className="text-cockpit-text">{status.address}</span>
          </span>
        </div>

        <SegmentedControl
          options={TYPEFACES}
          value={typeface}
          onChange={onTypefaceChange}
          size="sm"
          className="shrink-0"
        />

        {/* ml-auto keeps the cluster on the right edge once the bar wraps. */}
        <div className="ml-auto shrink-0">
          <Navigator {...nav} />
        </div>
      </div>
    </header>
  )
}
