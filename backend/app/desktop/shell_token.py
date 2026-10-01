"""Per-boot token marking requests made by the desktop shell window.

pywebview evaluates JavaScript through the page's own JS context, and
WebKitGTK (plus WebView2) applies the page CSP to it — the bridge
push (`__caDesktopBridge.onNotify`) and the toast-activation focus would
be blocked by the strict web CSP (`script-src 'self'`).

The shell therefore loads the SPA with `?shell=<token>`; the security
headers middleware swaps in a desktop CSP variant (adds 'unsafe-eval' to
script-src) for that document only. Browsers never know the token, so the
web deployment keeps the strict CSP. The token lives in memory for the
process lifetime and is regenerated on every boot.
"""

import hmac

from nx_auth.shell import generate_shell_secret

QUERY_PARAM = "shell"

_token: str | None = None


def issue() -> str:
    """Generate (or regenerate) this boot's shell token.

    Generation is the kit's (`nx_auth.shell.generate_shell_secret`,
    ADR-0028 — one §11 mechanism family-wide); this module keeps the
    per-process holder and the CSP-marker matching.
    """
    global _token
    _token = generate_shell_secret()
    return _token


def matches(value: str | None) -> bool:
    """True when `value` is this boot's shell token."""
    if _token is None or value is None:
        return False
    return hmac.compare_digest(value, _token)


def current() -> str | None:
    """This boot's shell token (None before `issue()`).

    The one secret serves both desktop gates (identity-auth §11): the
    `X-Shell-Token` request gate and the `?shell=` CSP marker — callers
    share it through this getter instead of rotating it."""
    return _token


def reset() -> None:
    """Forget the token (shell shutdown)."""
    global _token
    _token = None
