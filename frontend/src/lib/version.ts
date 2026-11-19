// "Neue Version verfügbar" — telling an open tab that a newer build is live.
//
// We deploy several times a day, and a tab opened before a deploy keeps the
// old bundle until somebody reloads it. ELI-57 ("Unternehmen anlegen nicht
// möglich") was exactly that: the create form of a stale bundle never sent
// the request the backend now expects, and nothing on screen said why.
//
// The build embeds its id (`__BUILD_ID__`, see vite.config.ts) and writes the
// same id to `/version.json`. A tab compares the two on return and on a
// timer. It never reloads by itself — the recruiter may be half-way through a
// note — it only offers to.

/** How often a visible tab asks. One tiny static file per tab per interval. */
export const CHECK_INTERVAL_MS = 5 * 60_000

/** Alt-tabbing fires focus and visibilitychange in a burst; collapse it. */
export const MIN_GAP_MS = 10_000

export const VERSION_URL = '/version.json'

/** True when the server serves a build other than the one running here. */
export function isNewVersion(current: string, latest: string | null): boolean {
  if (!current || !latest) return false
  return latest !== current
}

/** The id inside a parsed `/version.json`, or null for anything else. */
export function parseVersionId(body: unknown): string | null {
  if (typeof body !== 'object' || body === null) return null
  const id = (body as { id?: unknown }).id
  if (typeof id !== 'string' || id.trim() === '') return null
  return id
}

/** Show the notice for a newer build unless THAT build was dismissed — so a
 *  dismissal holds for the session, and yet another deploy brings it back. */
export function shouldShowNotice(
  current: string,
  latest: string | null,
  dismissed: string | null,
): boolean {
  return isNewVersion(current, latest) && latest !== dismissed
}

/** Fetch the live build id; null on any non-OK answer. Throws on network
 *  errors — the watcher swallows them. */
export async function fetchLatestVersionId(): Promise<string | null> {
  const res = await fetch(VERSION_URL, { cache: 'no-store' })
  if (!res.ok) return null
  return parseVersionId(await res.json())
}

export interface VersionWatcherOptions {
  current: string
  fetchLatest: () => Promise<string | null>
  onNewVersion: (id: string) => void
  isVisible: () => boolean
  intervalMs?: number
  minGapMs?: number
}

export interface VersionWatcher {
  /** Ask once, now. Never rejects. */
  check(): Promise<void>
  /** The tab came back (focus / visibilitychange): ask, unless just asked. */
  onReturn(): Promise<void>
  start(): void
  stop(): void
}

/** The polling logic without the DOM, so it can run under fake timers. */
export function createVersionWatcher(opts: VersionWatcherOptions): VersionWatcher {
  const intervalMs = opts.intervalMs ?? CHECK_INTERVAL_MS
  const minGapMs = opts.minGapMs ?? MIN_GAP_MS
  let inFlight: Promise<void> | null = null
  let lastAt = -Infinity
  let timer: ReturnType<typeof setInterval> | null = null

  function check(): Promise<void> {
    if (inFlight) return inFlight
    lastAt = Date.now()
    inFlight = (async () => {
      try {
        const latest = await opts.fetchLatest()
        if (latest && isNewVersion(opts.current, latest)) opts.onNewVersion(latest)
      } catch {
        // Offline, a deploy in progress, a captive portal: say nothing.
      } finally {
        inFlight = null
      }
    })()
    return inFlight
  }

  return {
    check,
    async onReturn() {
      if (!opts.isVisible()) return
      if (Date.now() - lastAt < minGapMs) return
      await check()
    },
    start() {
      if (timer !== null) return
      timer = setInterval(() => {
        if (opts.isVisible()) void check()
      }, intervalMs)
    },
    stop() {
      if (timer !== null) clearInterval(timer)
      timer = null
    },
  }
}
