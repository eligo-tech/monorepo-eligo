import { CalendarDays, SlidersHorizontal, Table2, ChevronDown, Plus } from 'lucide-react'
import { Breadcrumb } from '@/components/Breadcrumb'
import { PieChart } from './PieChart'
import {
  funnel as mockFunnel,
  dwell as mockDwell,
  createdJobs,
  feeShare,
} from '@/data/reporting'
import type { DwellStage, FunnelStage } from '@/data/types'
import { api } from '@/api/client'
import { toFunnel, toDwell } from '@/api/adapters'
import { useAsync } from '@/hooks/useAsync'

function Card({
  title,
  children,
  className = '',
}: {
  title: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={`rounded-2xl border border-line p-5 ${className}`}>
      <h3 className="text-lg font-bold tracking-tight text-ink">{title}</h3>
      <div className="mt-4">{children}</div>
    </div>
  )
}

function FunnelCard({ data }: { data: FunnelStage[] }) {
  const max = Math.max(...data.map((f) => f.value), 1)
  return (
    <Card title="Funnel">
      <div className="space-y-3">
        {data.map((f) => (
          <div key={f.label} className="flex items-center gap-4">
            <div className="w-28 text-[15px] text-ink-soft">{f.label}</div>
            <div className="h-6 flex-1 overflow-hidden rounded-md bg-slate-100">
              <div
                className="h-full rounded-md bg-gradient-to-r from-brand-400 to-brand-500"
                style={{ width: `${Math.max((f.value / max) * 100, 3)}%` }}
              />
            </div>
            <div className="w-12 text-right text-[15px] font-bold text-ink">{f.value}</div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function DwellCard({ data }: { data: DwellStage[] }) {
  return (
    <Card title="Verweildauer je Stufe">
      {/* Fixed-height plot area so percentage bar heights resolve. */}
      <div className="flex h-44 items-end justify-between gap-3">
        {data.map((d) => (
          <div key={d.label} className="flex h-full flex-1 flex-col items-center justify-end">
            <div className="mb-2 text-[12px] font-semibold text-brand-700">{d.caption}</div>
            <div
              className="w-full rounded-t-lg bg-gradient-to-b from-brand-400 to-brand-500"
              style={{ height: `${d.height * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between gap-3">
        {data.map((d) => (
          <div key={d.label} className="flex-1 text-center text-[12px] leading-tight text-ink-muted">
            {d.label}
          </div>
        ))}
      </div>
    </Card>
  )
}

function CreatedJobsCard() {
  return (
    <Card title="Erstellte Jobs">
      <div className="flex h-44 items-end justify-between gap-3">
        {createdJobs.map((j) => (
          <div key={j.label} className="flex h-full flex-1 flex-col items-center justify-end">
            <div
              className="w-full rounded-t-lg bg-gradient-to-b from-brand-300 to-brand-500"
              style={{ height: `${j.height * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between gap-3">
        {createdJobs.map((j) => (
          <div key={j.label} className="flex-1 text-center text-[12px] text-ink-muted">
            {j.label}
          </div>
        ))}
      </div>
    </Card>
  )
}

function FeeCard() {
  return (
    <Card title="Honorar erzielt">
      <div className="flex items-center gap-6">
        <PieChart data={feeShare} />
        <div className="flex-1 space-y-3">
          {feeShare.map((f) => (
            <div key={f.label} className="flex items-center gap-3">
              <span className="h-3 w-3 rounded-sm" style={{ background: f.color }} />
              <span className="flex-1 text-[15px] text-ink-soft">{f.label}</span>
              <span className="text-[15px] font-bold text-ink">{f.value}%</span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  )
}

export function ReportingView() {
  const { data } = useAsync(() => api.reportingOverview(), [])
  const funnelData = data ? toFunnel(data.funnel) : mockFunnel
  const dwellData = data ? toDwell(data.dwell) : mockDwell

  return (
    <div className="flex h-full flex-col overflow-hidden pt-[76px]">
      {/* Header */}
      <div className="flex items-center justify-between px-8 pt-6">
        <div className="flex items-center gap-3">
          <Breadcrumb items={['Start', 'Berichte', 'Verweildauer & Funnel-Analyse']} />
        </div>
        <div className="flex items-center gap-2.5">
          <button className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
            <Table2 className="h-4 w-4 text-ink-muted" /> Bewerbung <ChevronDown className="h-4 w-4" />
          </button>
          <button className="flex items-center gap-1.5 rounded-xl bg-ink px-4 py-2 text-[14px] font-semibold text-white hover:bg-ink-soft">
            <Plus className="h-4 w-4" /> Neuer Insight
          </button>
        </div>
      </div>

      {/* Filter row */}
      <div className="flex items-center gap-3 px-8 pt-5">
        <span className="text-[15px] font-bold text-ink">Verweildauer &amp; Funnel-Analyse</span>
        <button className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
          <CalendarDays className="h-4 w-4 text-ink-muted" /> Zeitraum
        </button>
        <span className="text-[14px] text-ink-faint">Zwischen</span>
        <button className="rounded-xl border border-line px-3.5 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
          1 Nov 2025 – 6 Jan 2026
        </button>
        <button className="flex items-center gap-2 rounded-xl border border-line px-3.5 py-2 text-[14px] font-medium text-ink-soft hover:bg-slate-50">
          <SlidersHorizontal className="h-4 w-4 text-ink-muted" /> Filter
        </button>
      </div>

      {/* Charts grid */}
      <div className="flex-1 overflow-y-auto px-8 pb-8 pt-5">
        <div className="grid grid-cols-2 gap-5">
          <FunnelCard data={funnelData} />
          <DwellCard data={dwellData} />
          <CreatedJobsCard />
          <FeeCard />
        </div>
      </div>
    </div>
  )
}