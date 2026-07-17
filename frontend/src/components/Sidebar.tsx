import {
  LayoutGrid,
  Bell,
  Inbox,
  CheckSquare,
  StickyNote,
  List,
  Calendar,
  Briefcase,
  Users,
  Building2,
  Contact,
  FileText,
  BarChart3,
  Search,
} from 'lucide-react'
import { Logo } from './Logo'
import { cn } from '@/lib/cn'

interface NavItem {
  label: string
  icon: React.ComponentType<{ className?: string }>
  active?: boolean
}

const workspace: NavItem[] = [
  { label: 'Inbox', icon: Inbox },
  { label: 'Aufgaben', icon: CheckSquare },
  { label: 'Notizen', icon: StickyNote },
  { label: 'Listen', icon: List },
  { label: 'Kalender', icon: Calendar },
]

const records: NavItem[] = [
  { label: 'Jobs', icon: Briefcase },
  { label: 'Kandidaten', icon: Users, active: true },
  { label: 'Unternehmen', icon: Building2 },
  { label: 'Kontakte', icon: Contact },
  { label: 'Vermittlungen', icon: FileText },
]

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-3 pb-2 pt-5 text-[11px] font-semibold uppercase tracking-wider text-sidebar-muted">
      {children}
    </p>
  )
}

function NavRow({ item, activeKey }: { item: NavItem; activeKey: string }) {
  const Icon = item.icon
  const active = item.label === activeKey
  return (
    <button
      className={cn(
        'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[14px] font-medium transition-colors',
        active
          ? 'bg-sidebar-active text-white'
          : 'text-sidebar-text hover:bg-sidebar-hover hover:text-white',
      )}
    >
      <Icon className="h-[18px] w-[18px]" />
      {item.label}
    </button>
  )
}

/** Persistent dark navigation rail. `activeKey` highlights the current record. */
export function Sidebar({ activeKey = 'Kandidaten' }: { activeKey?: string }) {
  return (
    <aside className="flex w-[264px] shrink-0 flex-col rounded-card bg-sidebar px-4 pb-5 pt-5">
      <div className="px-1.5">
        <Logo />
      </div>

      {/* Search */}
      <div className="mt-5 flex items-center gap-2 rounded-xl bg-sidebar-hover px-3 py-2.5 text-sm text-sidebar-muted">
        <Search className="h-4 w-4" />
        <span className="flex-1">Suchen…</span>
        <kbd className="rounded-md bg-sidebar-active px-1.5 py-0.5 text-[11px] font-medium text-sidebar-text">
          ⌘K
        </kbd>
      </div>

      {/* Top-level */}
      <nav className="mt-4 space-y-1">
        <NavRow item={{ label: 'Dashboard', icon: LayoutGrid }} activeKey={activeKey} />
        <NavRow item={{ label: 'Benachrichtigungen', icon: Bell }} activeKey={activeKey} />
      </nav>

      <div className="flex-1 overflow-y-auto">
        <SectionLabel>Arbeitsbereich</SectionLabel>
        <nav className="space-y-1">
          {workspace.map((i) => (
            <NavRow key={i.label} item={i} activeKey={activeKey} />
          ))}
        </nav>

        <SectionLabel>Datensätze</SectionLabel>
        <nav className="space-y-1">
          {records.map((i) => (
            <NavRow key={i.label} item={i} activeKey={activeKey} />
          ))}
        </nav>

        <SectionLabel>Werkzeuge</SectionLabel>
        <nav className="space-y-1">
          <NavRow item={{ label: 'Berichte', icon: BarChart3 }} activeKey={activeKey} />
        </nav>
      </div>
    </aside>
  )
}