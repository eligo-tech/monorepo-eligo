import { ChevronRight } from 'lucide-react'

/** Start › A › B breadcrumb. Last item is emphasised. */
export function Breadcrumb({ items, count }: { items: string[]; count?: number }) {
  return (
    <div className="flex items-center gap-1.5 text-[15px]">
      {items.map((item, i) => {
        const last = i === items.length - 1
        return (
          <span key={item} className="flex items-center gap-1.5">
            {i > 0 && <ChevronRight className="h-4 w-4 text-ink-faint" />}
            <span className={last ? 'font-semibold text-ink' : 'text-ink-muted'}>{item}</span>
          </span>
        )
      })}
      {count !== undefined && (
        <span className="ml-1 rounded-md bg-slate-100 px-2 py-0.5 text-[13px] font-medium text-ink-muted">
          {count}
        </span>
      )}
    </div>
  )
}