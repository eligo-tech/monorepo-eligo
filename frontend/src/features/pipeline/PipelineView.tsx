import {
  Search,
  Table2,
  ChevronDown,
  Plus,
  Briefcase,
  MapPin,
  Building,
  Mail,
  FileText,
  CheckSquare,
  Clock,
} from 'lucide-react'
import { Breadcrumb } from '@/components/Breadcrumb'
import { Avatar } from '@/components/ui/Avatar'
import { LinkedInMark } from '@/components/ui/LinkedInMark'
import { pipelineColumns as mockColumns } from '@/data/pipeline'
import type { PipelineCard as Card } from '@/data/types'
import { api } from '@/api/client'
import { toPipelineColumns } from '@/api/adapters'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'

const jobTabs = ['Pipeline', 'Details', 'Werbung', 'Matching', 'Inbound', 'Aufgaben', 'Kundenportal']

function KanbanCard({ card }: { card: Card }) {
  return (
    <div className="rounded-2xl border border-line bg-white p-4 shadow-kanban">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Avatar initials={card.initials} tone={card.avatar} size="sm" />
          <span className="font-semibold text-ink">{card.name}</span>
        </div>
        {card.linkedin && <LinkedInMark />}
      </div>

      <div className="mt-3 space-y-1.5 text-[14px] text-ink-soft">
        <div className="flex items-center gap-2">
          <Briefcase className="h-4 w-4 text-ink-faint" /> {card.title}
        </div>
        <div className="flex items-center gap-2">
          <MapPin className="h-4 w-4 text-ink-faint" /> {card.location}
        </div>
        <div className="flex items-center gap-2">
          <Building className="h-4 w-4 text-ink-faint" /> {card.company}
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-line pt-3 text-ink-faint">
        <div className="flex items-center gap-3">
          <Mail className="h-[15px] w-[15px]" />
          <FileText className="h-[15px] w-[15px]" />
          <CheckSquare className="h-[15px] w-[15px]" />
          <span className="flex items-center gap-1 text-[13px]">
            <Clock className="h-[15px] w-[15px]" /> {card.sla}
          </span>
        </div>
        <span className="h-2.5 w-2.5 rounded-full bg-accent-500" />
      </div>
    </div>
  )
}

function Column({
  title,
  dotColor,
  cards,
}: {
  title: string
  dotColor: string
  cards: Card[]
}) {
  return (
    <div className="w-[320px] shrink-0">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className={cn('h-2.5 w-2.5 rounded-full', dotColor)} />
          <span className="font-semibold text-ink">{title}</span>
          <span className="text-[15px] text-ink-muted">{cards.length}</span>
        </div>
        <button className="text-ink-faint hover:text-ink-soft">
          <Plus className="h-4 w-4" />
        </button>
      </div>
      <div className="space-y-3">
        {cards.map((c) => (
          <KanbanCard key={c.id} card={c} />
        ))}
      </div>
    </div>
  )
}

export function PipelineView() {
  const { data } = useAsync(async () => {
    const [board, cands] = await Promise.all([api.board(), api.candidates()])
    const byId = new Map(cands.map((c) => [c.id, c]))
    return toPipelineColumns(board, byId)
  }, [])
  // Live board may contain empty stages; keep only populated columns, else demo.
  const columns = data && data.some((c) => c.cards.length) ? data : mockColumns
  const total = columns.reduce((n, c) => n + c.cards.length, 0)

  return (
    <div className="flex h-full flex-col overflow-hidden pt-[76px]">
      <div className="px-8 pt-6">
        <div className="flex items-center gap-3">
          <Breadcrumb items={['Start', 'Jobs', 'Trade Republic', 'Finance Director']} />
        </div>

        {/* Job sub-tabs */}
        <div className="mt-4 flex items-center gap-6 border-b border-line">
          {jobTabs.map((t, i) => (
            <button
              key={t}
              className={
                i === 0
                  ? '-mb-px border-b-2 border-brand-500 pb-3 text-[15px] font-semibold text-ink'
                  : 'pb-3 text-[15px] text-ink-muted hover:text-ink-soft'
              }
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 px-8 pt-5">
        <div className="flex flex-1 items-center gap-2.5 rounded-xl border border-line bg-white px-3.5 py-2.5 text-[15px] text-ink-faint">
          <Search className="h-[18px] w-[18px]" />
          <span>Kandidaten &amp; Erfahrungen suchen…</span>
        </div>
        <button className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2.5 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
          <Table2 className="h-4 w-4 text-ink-muted" /> Ansicht <ChevronDown className="h-4 w-4" />
        </button>
      </div>

      {/* Board */}
      <div className="flex-1 overflow-auto px-8 pb-8 pt-5">
        <button className="mb-4 flex items-center gap-2 text-[15px] font-semibold text-ink">
          <ChevronDown className="h-4 w-4 text-ink-muted" /> In Bearbeitung
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[13px] font-medium text-ink-muted">
            {total}
          </span>
        </button>

        <div className="flex gap-5">
          {columns.map((col) => (
            <Column key={col.id} title={col.title} dotColor={col.dotColor} cards={col.cards} />
          ))}
        </div>

        <button className="mt-6 flex items-center gap-2 text-[15px] font-semibold text-ink-muted">
          <ChevronDown className="h-4 w-4" /> Abgelehnt
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[13px] font-medium text-ink-muted">
            3
          </span>
        </button>
      </div>
    </div>
  )
}