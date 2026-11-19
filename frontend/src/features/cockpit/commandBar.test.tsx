import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { CommandBar } from './CommandBar'
import { MOCK_COCKPIT } from './data/mock'
import { WorkspaceMark } from './ui/WorkspaceMark'

// ELI-55 "UI": the header loses "· Personalberatung", the "Human-in-the-Loop
// aktiv" pill, the clock mark and the Jet · Mono · Heli switch. The workspace's
// own icon stands left of "Cockpit"; without one, the Eligo mark.

function bar(headerIconUrl: string | null = null): string {
  return renderToStaticMarkup(
    <CommandBar
      status={{ ...MOCK_COCKPIT.status, humanInTheLoop: true }}
      me={null}
      query=""
      onQueryChange={() => {}}
      onOpenRecord={() => {}}
      headerIconUrl={headerIconUrl}
      screens={[{ key: 'cockpit', label: 'Cockpit' }]}
      screen="cockpit"
      onScreenChange={() => {}}
    />,
  )
}

describe('CommandBar (ELI-55)', () => {
  it('drops the tagline, the pill and the typeface switch', () => {
    const html = bar()
    expect(html).toContain('COCKPIT')
    expect(html).not.toContain('Personalberatung')
    expect(html).not.toContain('Human-in-the-Loop')
    for (const face of ['>Jet<', '>Mono<', '>Heli<']) expect(html).not.toContain(face)
  })

  it('shows the Eligo mark when the workspace has no icon', () => {
    const html = bar()
    expect(html).toContain('data-mark="eligo"')
    expect(html).not.toContain('<img')
  })

  it("shows the workspace's own icon when it has one", () => {
    const html = bar('blob:icon')
    expect(html).toContain('data-mark="workspace"')
    expect(html).toContain('src="blob:icon"')
    expect(html).not.toContain('data-mark="eligo"')
  })
})

describe('WorkspaceMark', () => {
  it('is the Eligo mark for null', () => {
    expect(renderToStaticMarkup(<WorkspaceMark iconUrl={null} />)).toContain('data-mark="eligo"')
  })
})
