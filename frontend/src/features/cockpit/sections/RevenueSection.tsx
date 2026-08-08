// "01 Umsatz & Potenzial" — the gauge, the IST + POTENZIAL = PROGNOSE strip, the
// year-goal bar, and the deals about to land.
//
// The section is a carousel: the revenue panel is slide one, and further KPI
// slides come from the same data array (see MOCK_COCKPIT.slides), so adding one
// is a data edit rather than a layout change.

import { useState } from 'react'
import { Carousel, Slide } from '../ui/Carousel'
import { Gauge } from '../ui/Gauge'
import { Chip, Figure, Label, Money, Panel, SectionHeader, SegmentedControl } from '../ui/primitives'
import type { KpiSlide, PeriodKey, RevenuePanel } from '../data/types'

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: 'jahr', label: 'Jahr' },
  { key: 'quartal', label: 'Quartal' },
  { key: 'monat', label: 'Monat' },
  { key: 'tag', label: 'Tag' },
]

export function RevenueSection({ slides }: { slides: KpiSlide[] }) {
  const [period, setPeriod] = useState<PeriodKey>('monat')

  return (
    <section className="space-y-5">
      <SectionHeader
        id="section-01"
        index="01"
        title="Umsatz & Potenzial"
        hint="‹ wischen · tippen ›"
      />

      <Carousel count={slides.length} ariaLabel="Kennzahlen-Panels">
        {slides.map((slide) => (
          <Slide key={slide.id}>
            <Panel className="relative overflow-hidden p-7">
              {/* Warm hairline along the top edge, as in the mockup. */}
              <span
                aria-hidden
                className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-gold-500/50 to-transparent"
              />
              {slide.kind === 'revenue' && slide.panels ? (
                <RevenueBody
                  panel={slide.panels[period]}
                  period={period}
                  onPeriodChange={setPeriod}
                />
              ) : (
                <PlaceholderBody title={slide.title} hint={slide.hint} />
              )}
            </Panel>
          </Slide>
        ))}
      </Carousel>
    </section>
  )
}

function RevenueBody({
  panel,
  period,
  onPeriodChange,
}: {
  panel: RevenuePanel
  period: PeriodKey
  onPeriodChange: (p: PeriodKey) => void
}) {
  const forecast = {
    value: panel.actual.value + panel.potential.value,
    // A sum is only as trustworthy as its weakest input.
    provenance:
      panel.actual.provenance === 'live' && panel.potential.provenance === 'live'
        ? ('live' as const)
        : ('demo' as const),
    source: 'IST + gewichtetes Potenzial',
  }
  const yearPct = panel.yearTarget.value
    ? Math.round((panel.yearActual.value / panel.yearTarget.value) * 100)
    : 0

  return (
    <div className="flex flex-col gap-8 xl:flex-row xl:items-start">
      <div className="flex flex-col items-center gap-6 xl:items-start">
        <SegmentedControl options={PERIODS} value={period} onChange={onPeriodChange} />
        <Gauge
          actual={panel.actual}
          potential={panel.potential}
          target={panel.target}
          caption={panel.caption}
          className="xl:ml-2"
        />
      </div>

      <div className="min-w-0 flex-1 space-y-6">
        {/* IST + POTENZIAL = PROGNOSE */}
        <div className="grid grid-cols-1 items-center gap-4 rounded-2xl border border-cockpit-line bg-cockpit-inset px-6 py-5 sm:grid-cols-3">
          <div className="space-y-2">
            <Label>Ist</Label>
            <Money figure={panel.actual} className="block text-[26px] text-cockpit-text" />
          </div>
          <div className="relative space-y-2 sm:pl-8">
            <span className="absolute -left-1 top-8 hidden font-mono text-[18px] text-cockpit-faint sm:block">
              +
            </span>
            <Label>Potenzial</Label>
            <span className="block text-[26px] text-gold-400">
              + <Money figure={panel.potential} />
            </span>
          </div>
          <div className="relative space-y-2 sm:pl-8">
            <span className="absolute -left-1 top-8 hidden font-mono text-[18px] text-cockpit-faint sm:block">
              =
            </span>
            <Label>Prognose</Label>
            <Money figure={forecast} className="block text-[26px] text-mint-400" />
          </div>
        </div>

        {/* Year goal */}
        <div>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-[15px] text-cockpit-dim">Jahresziel</span>
            <span className="font-mono text-[14px] text-cockpit-dim">
              <Money figure={panel.yearActual} className="text-cockpit-text" /> /{' '}
              <Money figure={panel.yearTarget} /> · {yearPct}%
            </span>
          </div>
          <div className="mt-2 h-[6px] overflow-hidden rounded-full bg-[#26281f]">
            <div
              className="h-full rounded-full bg-mint-400"
              style={{ width: `${Math.min(100, yearPct)}%` }}
            />
          </div>
        </div>

        {/* Kurz vor Abschluss */}
        <div>
          <div className="flex items-baseline gap-3">
            <Label>Kurz vor Abschluss</Label>
            <span className="text-[13px] text-cockpit-faint">fließt in den Umsatz</span>
          </div>

          <div className="mt-3 divide-y divide-cockpit-line">
            {panel.closing.map((deal) => (
              <div key={deal.id} className="flex flex-wrap items-start gap-x-4 gap-y-2 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-[15px] text-cockpit-text">
                    <span className="font-mono">{deal.candidateRef}</span>
                    <span className="text-cockpit-faint"> · </span>
                    <span className="font-mono">{deal.mandateRef}</span>
                    <span className="text-cockpit-faint"> · </span>
                    {deal.client}
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <Chip tone="mint">{deal.timing}</Chip>
                    <span className="font-mono text-[13px] text-cockpit-faint">
                      Chance <Figure figure={deal.chance} suffix="%" />
                    </span>
                    {deal.note && <Chip tone="mint">{deal.note}</Chip>}
                  </div>
                </div>
                <Money figure={deal.fee} className="shrink-0 text-[17px] text-cockpit-text" />
              </div>
            ))}
          </div>

          <p className="mt-3 text-[14px] text-cockpit-dim">
            Weitere Pipeline +<Money figure={panel.pipelineTotal} /> möglich · gewichtet{' '}
            <Money figure={panel.pipelineWeighted} className="text-cockpit-text" />
          </p>
        </div>
      </div>
    </div>
  )
}

function PlaceholderBody({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex min-h-[420px] flex-col items-center justify-center gap-3 text-center">
      <h3 className="text-[20px] font-semibold text-cockpit-dim">{title}</h3>
      <p className="max-w-sm text-[14px] text-cockpit-faint">{hint}</p>
      <span className="mt-2 rounded-md border border-cockpit-line px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.1em] text-cockpit-faint">
        noch keine Daten
      </span>
    </div>
  )
}
