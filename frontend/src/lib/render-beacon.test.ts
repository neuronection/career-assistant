import { afterEach, describe, expect, it, vi } from 'vitest'

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

async function loadBeacon() {
  vi.resetModules()
  // A bound profile in the fresh module registry keeps apiRequestHeaders
  // from firing the real priming GET (jsdom has no server).
  const client = await import('@/api/client')
  client.setActiveProfile('profile-1')
  return await import('./render-beacon')
}

function stubFramesAndFetch() {
  const fetchMock = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    cb(0)
    return 0
  })
  return fetchMock
}

describe('signalShellRendered', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.sessionStorage.removeItem('nx_shell')
    document.cookie = 'nx_csrf=; Max-Age=0; path=/'
  })

  it('posts once after two animation frames', async () => {
    const fetchMock = stubFramesAndFetch()
    const { signalShellRendered } = await loadBeacon()
    signalShellRendered()
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/v1/shell/rendered')
    expect(init.method).toBe('POST')
  })

  it('signals only once per page load', async () => {
    const fetchMock = stubFramesAndFetch()
    const { signalShellRendered } = await loadBeacon()
    signalShellRendered()
    signalShellRendered()
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not post before frames fire', async () => {
    const fetchMock = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('fetch', fetchMock)
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      frames.push(cb)
      return frames.length
    })
    const { signalShellRendered } = await loadBeacon()
    signalShellRendered()
    expect(fetchMock).not.toHaveBeenCalled()
    frames[0](0)
    frames[1](0)
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('rides the shell-gate + CSRF headers (§11/§10)', async () => {
    // client.ts captures the shell token at module load — set it before
    // the beacon (and its client import) are evaluated.
    window.sessionStorage.setItem('nx_shell', 'boot-secret')
    document.cookie = 'nx_csrf=csrf-token; path=/'
    const fetchMock = stubFramesAndFetch()
    const { signalShellRendered } = await loadBeacon()
    signalShellRendered()
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers['X-Shell-Token']).toBe('boot-secret')
    expect(headers['X-CSRF-Token']).toBe('csrf-token')
  })
})
