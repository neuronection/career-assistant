"""Per-boot token marking requests made by the desktop shell window.

pywebview evaluates JavaScript through the page's own JS context, and
WebKitGTK (plus WebView2) applies the page CSP to it — the plan-36 bridge
push (`__caDesktopBridge.onNotify`) and the toast-activation focus would
be blocked by the strict web CSP (`script-src 'self'`).

The shell therefore loads the SPA with `?shell=<token>`; the security
headers middleware swaps in a desktop CSP variant (adds 'unsafe-eval' to
script-src) for that document only. Browsers never know the token, so the
web deployment keeps the strict CSP. The token lives in memory for the
process lifetime and is regenerated on every boot.
"""

import hmac
import secrets

QUERY_PARAM = "shell"

_token: str | None = None


def issue() -> str:
    """Generate (or regenerate) this boot's shell token."""
    global _token
    _token = secrets.token_urlsafe(16)
    return _token


def matches(value: str | None) -> bool:
    """True when `value` is this boot's shell token."""
    if _token is None or value is None:
        return False
    return hmac.compare_digest(value, _token)


def reset() -> None:
    """Forget the token (shell shutdown)."""
    global _token
    _token = None
