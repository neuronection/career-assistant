import { apiRequestHeaders } from '@/api/client'

let signaled = false

export function signalShellRendered(): void {
  if (signaled) return
  signaled = true
  const send = () => {
    // Raw fetch, not axios: this fires at SPA mount — before the desktop
    // exchange has run — and must already carry the §11 shell gate
    // header (the gate covers every /api/ route) plus the §10 CSRF echo
    // whenever a cookie jar from a previous session exists. Without
    // them the beacon 403s, `spa_rendered` never sets, and the Linux
    // renderer sentinel false-relaunches a healthy WebKit into
    // software mode.
    void (async () => {
      await fetch('/api/v1/shell/rendered', {
        method: 'POST',
        headers: await apiRequestHeaders('/api/v1/shell/rendered', 'POST'),
      })
    })()
  }
  requestAnimationFrame(() => requestAnimationFrame(send))
}
