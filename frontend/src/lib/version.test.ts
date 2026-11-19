import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CHECK_INTERVAL_MS,
  createVersionWatcher,
  isNewVersion,
  parseVersionId,
  shouldShowNotice,
} from './version'

describe('isNewVersion', () => {
  it('is true only for a different, non-empty id', () => {
    expect(isNewVersion('abc', 'def')).toBe(true)
    expect(isNewVersion('abc', 'abc')).toBe(false)
    expect(isNewVersion('abc', null)).toBe(false)
    expect(isNewVersion('abc', '')).toBe(false)
  })

  it('never fires without a build id of our own', () => {
    expect(isNewVersion('', 'def')).toBe(false)
  })
})

describe('parseVersionId', () => {
  it('reads the id of version.json', () => {
    expect(parseVersionId({ id: 'abc123' })).toBe('abc123')
  })

  it('returns null for anything else', () => {
    expect(parseVersionId(null)).toBeNull()
    expect(parseVersionId('abc')).toBeNull()
    expect(parseVersionId({ id: 42 })).toBeNull()
    expect(parseVersionId({ id: '  ' })).toBeNull()
    expect(parseVersionId({})).toBeNull()
  })
})

describe('shouldShowNotice', () => {
  it('shows a newer version until it is dismissed', () => {
    expect(shouldShowNotice('v1', 'v2', null)).toBe(true)
    expect(shouldShowNotice('v1', 'v2', 'v2')).toBe(false)
  })

  it('shows again when yet another version ships after a dismissal', () => {
    expect(shouldShowNotice('v1', 'v3', 'v2')).toBe(true)
  })

  it('shows nothing while no newer version is known', () => {
    expect(shouldShowNotice('v1', null, null)).toBe(false)
    expect(shouldShowNotice('v1', 'v1', null)).toBe(false)
  })
})

describe('createVersionWatcher', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  function setup(opts: { visible?: boolean; latest?: () => Promise<string | null> } = {}) {
    let visible = opts.visible ?? true
    const fetchLatest = vi.fn(opts.latest ?? (async () => 'v1'))
    const onNewVersion = vi.fn()
    const w = createVersionWatcher({
      current: 'v1',
      fetchLatest,
      onNewVersion,
      isVisible: () => visible,
    })
    return { w, fetchLatest, onNewVersion, setVisible: (v: boolean) => (visible = v) }
  }

  it('reports a different id from the server', async () => {
    const { w, onNewVersion } = setup({ latest: async () => 'v2' })
    await w.check()
    expect(onNewVersion).toHaveBeenCalledWith('v2')
  })

  it('stays quiet while the server still serves our build', async () => {
    const { w, onNewVersion } = setup()
    await w.check()
    expect(onNewVersion).not.toHaveBeenCalled()
  })

  it('fails silent on a network error', async () => {
    const { w, onNewVersion } = setup({
      latest: async () => {
        throw new TypeError('Failed to fetch')
      },
    })
    await expect(w.check()).resolves.toBeUndefined()
    expect(onNewVersion).not.toHaveBeenCalled()
  })

  it('polls on the interval while the tab is visible', async () => {
    const { w, fetchLatest } = setup()
    w.start()
    expect(fetchLatest).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(CHECK_INTERVAL_MS)
    expect(fetchLatest).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(CHECK_INTERVAL_MS)
    expect(fetchLatest).toHaveBeenCalledTimes(2)
    w.stop()
    await vi.advanceTimersByTimeAsync(CHECK_INTERVAL_MS * 3)
    expect(fetchLatest).toHaveBeenCalledTimes(2)
  })

  it('does not poll while the tab is hidden', async () => {
    const { w, fetchLatest, setVisible } = setup({ visible: false })
    w.start()
    await vi.advanceTimersByTimeAsync(CHECK_INTERVAL_MS * 3)
    expect(fetchLatest).not.toHaveBeenCalled()
    setVisible(true)
    await vi.advanceTimersByTimeAsync(CHECK_INTERVAL_MS)
    expect(fetchLatest).toHaveBeenCalledTimes(1)
    w.stop()
  })

  it('checks on return to the tab, but not twice in quick succession', async () => {
    const { w, fetchLatest } = setup()
    await w.onReturn()
    await w.onReturn()
    expect(fetchLatest).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(15_000)
    await w.onReturn()
    expect(fetchLatest).toHaveBeenCalledTimes(2)
  })

  it('ignores a return while the document is still hidden', async () => {
    const { w, fetchLatest } = setup({ visible: false })
    await w.onReturn()
    expect(fetchLatest).not.toHaveBeenCalled()
  })

  it('runs one request at a time', async () => {
    let release: (v: string) => void = () => {}
    const { w, fetchLatest } = setup({
      latest: () => new Promise<string>((r) => (release = r)),
    })
    const first = w.check()
    void w.check()
    expect(fetchLatest).toHaveBeenCalledTimes(1)
    release('v1')
    await first
  })
})
