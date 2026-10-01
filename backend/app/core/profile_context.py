"""Request-scoped identity context (identity-auth §15).

`ProfileBindingMiddleware` (plan 16 P3b) stashes the verified user and
the bound profile here; service-layer scoping reads the context instead
of threading ids through every signature. Never trust a raw header —
only the middleware writes these.
"""

from contextvars import ContextVar, Token

_active_profile_id: ContextVar[str | None] = ContextVar("active_profile_id", default=None)
_active_user_id: ContextVar[str | None] = ContextVar("active_user_id", default=None)


def set_active_profile(profile_id: str | None) -> Token[str | None]:
    return _active_profile_id.set(profile_id)


def reset_active_profile(token: Token[str | None]) -> None:
    _active_profile_id.reset(token)


def active_profile_id() -> str | None:
    return _active_profile_id.get()


def set_active_user(user_id: str | None) -> Token[str | None]:
    return _active_user_id.set(user_id)


def reset_active_user(token: Token[str | None]) -> None:
    _active_user_id.reset(token)


def active_user_id() -> str | None:
    return _active_user_id.get()
