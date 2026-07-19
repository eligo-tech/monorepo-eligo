import { Users, Target, KanbanSquare, PresentationIcon } from 'lucide-react'
import { OrganizationSwitcher, UserButton } from '@clerk/clerk-react'
import { cn } from '@/lib/cn'
import { authEnabled } from '@/auth/config'

export type Tab = 'Kandidaten' | 'Matching' | 'Pipeline' | 'Reporting'

const tabs: { key: Tab; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: 'Kandidaten', icon: Users },
  { key: 'Matching', icon: Target },
  { key: 'Pipeline', icon: KanbanSquare },
  { key: 'Reporting', icon: PresentationIcon },
]

interface TopNavProps {
  active: Tab
  onChange: (t: Tab) => void
  lang: 'DE' | 'EN'
  onLangChange: (l: 'DE' | 'EN') => void
}

/** Floating pill nav with the four primary product tabs + language switch. */
export function TopNav({ active, onChange, lang, onLangChange }: TopNavProps) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-4 z-20 flex items-center justify-center gap-3 px-6">
      <div className="pointer-events-auto flex items-center gap-1 rounded-2xl bg-white p-1.5 shadow-pill">
        {tabs.map(({ key, icon: Icon }) => {
          const isActive = key === active
          return (
            <button
              key={key}
              onClick={() => onChange(key)}
              className={cn(
                'flex items-center gap-2 rounded-xl px-4 py-2.5 text-[15px] font-semibold transition-all',
                isActive
                  ? 'text-brand-600 ring-2 ring-accent-500'
                  : 'text-ink-soft hover:bg-slate-50',
              )}
            >
              <Icon className="h-[18px] w-[18px]" />
              {key}
            </button>
          )
        })}
      </div>

      {/* Tenant (organization) + account + language switch, pinned right */}
      <div className="pointer-events-auto absolute right-6 flex items-center gap-3">
        {authEnabled && (
          <div className="flex items-center gap-2 rounded-xl bg-white px-2.5 py-1.5 shadow-pill">
            <OrganizationSwitcher
              hidePersonal
              afterSelectOrganizationUrl="/#Kandidaten"
              afterCreateOrganizationUrl="/#Kandidaten"
              appearance={{ elements: { rootBox: 'flex items-center' } }}
            />
            <UserButton afterSignOutUrl="/" />
          </div>
        )}
        <div className="flex items-center rounded-xl bg-white p-1 shadow-pill">
          {(['DE', 'EN'] as const).map((l) => (
            <button
              key={l}
              onClick={() => onLangChange(l)}
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors',
                lang === l ? 'bg-slate-100 text-ink' : 'text-ink-faint hover:text-ink-soft',
              )}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}