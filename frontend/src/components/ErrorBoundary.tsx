// A render error must not take the whole page with it.
//
// Without a boundary React unmounts the entire tree on any uncaught render
// error, which leaves only the dark body background: a black page, no
// message, no way out but a refresh. Two of these are mounted — one around
// the whole app (main.tsx), one around the active cockpit screen
// (CockpitShell.tsx), so a crash in one screen keeps the command bar and
// navigation working, and moving to another screen recovers.

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RotateCw } from 'lucide-react'

import { t } from '@/i18n'

interface Props {
  children: ReactNode
  /** When this changes, a caught error is cleared and the children render
   *  again — the screen name, so navigating away is the way out. */
  resetKey?: string
}

interface State {
  error: Error | null
  resetKey?: string
}

/** The next state when the reset key may have changed, or null for "no
 *  change". Pure, so it can be tested without a DOM. */
export function boundaryStateFor(state: State, resetKey: string | undefined): State | null {
  if (state.resetKey === resetKey) return null
  return { error: null, resetKey }
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  static getDerivedStateFromProps(props: Props, state: State): State | null {
    return boundaryStateFor(state, props.resetKey)
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // There is no frontend error reporting yet (GlitchTip covers the
    // backend only); the console is where this is visible today.
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (this.state.error) return <ErrorFallback error={this.state.error} />
    return this.props.children
  }
}

export function ErrorFallback({ error }: { error: Error }) {
  return (
    <div className="mx-auto my-16 max-w-xl px-6">
      <div className="rounded-2xl border border-coral-500/40 bg-cockpit-surface p-6 text-cockpit-text shadow-panel">
        <div className="flex items-center gap-2.5">
          <AlertTriangle className="h-5 w-5 text-coral-400" aria-hidden />
          <h2 className="font-sans text-[17px] font-semibold">
            {t('Diese Ansicht konnte nicht angezeigt werden')}
          </h2>
        </div>
        <p className="mt-2 font-sans text-[14px] text-cockpit-dim">
          {t('Ein Fehler in der Oberfläche. Wechsle die Ansicht oder lade die Seite neu.')}
        </p>
        <pre className="mt-4 overflow-x-auto whitespace-pre-wrap rounded-lg bg-cockpit-inset p-3 font-mono text-[12px] text-cockpit-faint">
          {error.message}
        </pre>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-4 inline-flex items-center gap-2 rounded-lg border border-cockpit-line px-3 py-1.5 font-mono text-[13px] text-cockpit-text hover:border-cockpit-edge"
        >
          <RotateCw className="h-3.5 w-3.5" aria-hidden />
          {t('Neu laden')}
        </button>
      </div>
    </div>
  )
}
