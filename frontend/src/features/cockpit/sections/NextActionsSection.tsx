// "Nächste beste Aktionen" — the queue the cockpit wants the recruiter to work
// through, each tagged with what kind of work it is.

import { useState } from 'react'
import { MessageSquare, Flag, Phone, RefreshCw, ShieldCheck, Zap } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Panel, SectionHeader, Tag, type Tone } from '../ui/primitives'
import type { ActionCategory, NextAction } from '../data/types'

const CATEGORY: Record<
  ActionCategory,
  { label: string; tone: Tone; icon: React.ComponentType<{ className?: string }> }
> = {
  'business-dev': { label: 'Business Dev.', tone: 'gold', icon: Phone },
  abschluss: { label: 'Abschluss', tone: 'mint', icon: Flag },
  freigabe: { label: 'Freigabe', tone: 'lav', icon: ShieldCheck },
  datenlauf: { label: 'Datenlauf', tone: 'mint', icon: RefreshCw },
  feedback: { label: 'Feedback', tone: 'coral', icon: MessageSquare },
}

const ICON_TONE: Record<Tone, string> = {
  mint: 'border-mint-700 bg-mint-800/30 text-mint-400',
  gold: 'border-gold-600 bg-gold-800/30 text-gold-400',
  coral: 'border-coral-600 bg-coral-800/30 text-coral-400',
  lav: 'border-lav-600 bg-lav-800/30 text-lav-400',
}

export function NextActionsSection({ actions }: { actions: NextAction[] }) {
  // Local only: ticking an action off is a UI affordance until there's a task
  // endpoint to commit it against.
  const [done, setDone] = useState<Set<string>>(new Set())
  const open = actions.filter((a) => !done.has(a.id)).length

  const toggle = (id: string) =>
    setDone((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <section className="space-y-5">
      <SectionHeader
        id="section-04"
        title="Nächste beste Aktionen"
        tone="gold"
        icon={<Zap className="h-[15px] w-[15px]" />}
        hint={`${open} offen`}
      />

      <div className="space-y-3">
        {actions.map((action) => {
          const { label, tone, icon: Icon } = CATEGORY[action.category]
          const isDone = done.has(action.id)

          return (
            <Panel
              key={action.id}
              tone="raised"
              className={cn(
                'flex flex-wrap items-center gap-x-5 gap-y-3 px-6 py-4 transition-opacity',
                isDone && 'opacity-45',
              )}
            >
              <button
                type="button"
                onClick={() => toggle(action.id)}
                aria-pressed={isDone}
                aria-label={isDone ? 'Wieder öffnen' : 'Als erledigt markieren'}
                className={cn(
                  'h-[22px] w-[22px] shrink-0 rounded-full border-2 transition-colors',
                  isDone
                    ? 'border-mint-500 bg-mint-500'
                    : 'border-[#3a3d31] hover:border-mint-600',
                )}
              />

              <span className={cn('shrink-0 rounded-xl border p-2.5', ICON_TONE[tone])}>
                <Icon className="h-[18px] w-[18px]" />
              </span>

              <div className="min-w-[14rem] flex-1">
                <h3
                  className={cn(
                    'text-[16px] font-semibold text-cockpit-text',
                    isDone && 'line-through',
                  )}
                >
                  {action.title}
                </h3>
                <p className="mt-0.5 text-[14px] text-cockpit-dim">{action.detail}</p>
              </div>

              <Tag tone={tone}>{label}</Tag>
            </Panel>
          )
        })}
      </div>
    </section>
  )
}
