import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { mandatesFromCards } from '../data/adapters'
import { MOCK_COCKPIT } from '../data/mock'
import { MandateHead } from '../sections/ProcessSection'
import { MandateGraph } from './MandateGraph'
import { ProcessCardPanel } from './ProcessCardPanel'
import { ScoreBar } from './ScoreBar'

// ELI-24. The process view showed "#K-6a36 · Nesim Celik · IT-Administrator",
// under it "#A-c34c · Linde + Wiemann", and above the mandate
// "#A-c34c · IT-Administrator …". Those short ids are a uuid prefix — nobody
// says them out loud, nobody searches for them — so they are gone from what
// a recruiter sees. The fields stay in the data model.
const REF = /#[AK]-/

const card = MOCK_COCKPIT.processes[0]
const mandate = mandatesFromCards(MOCK_COCKPIT.processes)[0]

describe('record refs are not shown', () => {
  it('the data still carries them', () => {
    expect(card.candidateRef).toMatch(REF)
    expect(mandate.ref).toMatch(REF)
  })

  it('not in a process card header, nor its mandate line', () => {
    const html = renderToStaticMarkup(<ProcessCardPanel card={card} onMandateClick={() => undefined} />)
    expect(html).toContain(card.candidateName)
    expect(html).toContain(card.client)
    expect(html).not.toMatch(REF)
    // No separator left dangling where the ref was.
    expect(html).not.toMatch(/<h3[^>]*>\s*<span[^>]*> · <\/span>/)
  })

  it('not in a process card without a mandate link', () => {
    const html = renderToStaticMarkup(<ProcessCardPanel card={card} />)
    expect(html).not.toMatch(REF)
  })

  it('not above the mandate', () => {
    const html = renderToStaticMarkup(<MandateHead mandate={mandate} />)
    // The title alone — no "#A-… · " and no separator left in front of it.
    expect(html).toContain(`font-semibold text-cockpit-text">${mandate.title}</span>`)
    expect(html).not.toMatch(REF)
  })

  it('not in the mandate graph', () => {
    const html = renderToStaticMarkup(<MandateGraph mandate={mandate} />)
    expect(html).not.toMatch(REF)
  })

  it('not in the Jobscoring list', () => {
    const html = renderToStaticMarkup(<ScoreBar row={MOCK_COCKPIT.jobScores[0]} />)
    expect(html).toContain(MOCK_COCKPIT.jobScores[0].title)
    expect(html).not.toMatch(REF)
  })
})
