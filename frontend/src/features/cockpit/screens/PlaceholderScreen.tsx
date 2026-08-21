// A section that exists in the navigation but not yet in the product.
//
// Listed rather than hidden on purpose: the nav is where the intended shape of
// the CRM is legible (Firma → Manager → Job), and a section that is coming is
// more honest than one that silently isn't there. It says what it will hold, so
// nobody mistakes it for something broken.

import type { ReactNode } from 'react'
import { Panel, SectionHeader } from '../ui/primitives'

export function PlaceholderScreen({
  title,
  lead,
  anchor,
  children,
}: {
  title: string
  lead: string
  anchor: string
  children?: ReactNode
}) {
  return (
    <div className="space-y-8">
      <header id={anchor} className="scroll-mt-24">
        <h1 className="text-[44px] font-semibold leading-tight tracking-tight text-cockpit-text">
          {title}
        </h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-cockpit-dim">{lead}</p>
      </header>

      <section className="space-y-5">
        <SectionHeader index="01" title="Noch nicht gebaut" tone="gold" />
        <Panel className="p-6">
          <div className="max-w-2xl space-y-3 text-[14px] leading-relaxed text-cockpit-dim">
            {children}
          </div>
        </Panel>
      </section>
    </div>
  )
}
