import { useEffect, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: Error | null
}

export interface AsyncOptions {
  /**
   * Keep the data already on screen while a re-run is in flight, and keep it
   * if that re-run fails.
   *
   * The default blanks everything on each `deps` change, which is right for
   * a load the user asked for — a list that still shows the old filter's
   * rows while the new ones load is lying. It is wrong for a refresh the
   * user did not ask for: coming back to the tab would clear the pool to a
   * spinner and, if the network happened to be down for that one second,
   * replace a perfectly good list with an error.
   *
   * With this set, a failed background refresh shows the error hint beside
   * the data it could not replace, which is the honest reading of "I could
   * not check whether this is still current".
   */
  keepPrevious?: boolean
}

/**
 * Run an async loader on mount (and when `deps` change), tracking
 * loading/error/data. Used to bind views to the live API.
 */
export function useAsync<T>(
  loader: () => Promise<T>,
  deps: unknown[] = [],
  options: AsyncOptions = {},
): AsyncState<T> {
  const { keepPrevious = false } = options
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: true,
    error: null,
  })

  useEffect(() => {
    let alive = true
    setState((prev) =>
      keepPrevious && prev.data !== null
        ? { ...prev, loading: true }
        : { data: null, loading: true, error: null },
    )
    loader()
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch(
        (error: Error) =>
          alive &&
          setState((prev) => ({
            data: keepPrevious ? prev.data : null,
            loading: false,
            error,
          })),
      )
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}
