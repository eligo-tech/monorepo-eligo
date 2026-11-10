import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { t } from '@/i18n'

import { ErrorBoundary, ErrorFallback, boundaryStateFor } from './ErrorBoundary'

// Without a boundary, any render error unmounts the whole React tree and
// leaves the dark body background — the same black page the workspace
// switch produced, with nothing to say what happened or how to get out.
//
// There is no DOM test environment here, so the boundary's decisions are
// pure functions and tested as such; the fallback is rendered to markup.
describe('ErrorBoundary', () => {
  it('catches a render error into state', () => {
    const error = new Error('boom')
    expect(ErrorBoundary.getDerivedStateFromError(error)).toEqual({ error })
  })

  it('clears the error when the reset key changes — moving to another screen recovers', () => {
    const crashed = { error: new Error('boom'), resetKey: 'kandidaten' }
    expect(boundaryStateFor(crashed, 'markt')).toEqual({ error: null, resetKey: 'markt' })
  })

  it('keeps the error while the reset key is the same', () => {
    const crashed = { error: new Error('boom'), resetKey: 'kandidaten' }
    expect(boundaryStateFor(crashed, 'kandidaten')).toBeNull()
  })

  it('shows what broke and a way out, instead of nothing', () => {
    const html = renderToStaticMarkup(<ErrorFallback error={new Error('x is undefined')} />)
    expect(html).toContain(t('Diese Ansicht konnte nicht angezeigt werden'))
    expect(html).toContain(t('Neu laden'))
    expect(html).toContain('x is undefined')
  })

  it('renders its children when nothing went wrong', () => {
    const html = renderToStaticMarkup(
      <ErrorBoundary>
        <p>fine</p>
      </ErrorBoundary>,
    )
    expect(html).toBe('<p>fine</p>')
  })
})
