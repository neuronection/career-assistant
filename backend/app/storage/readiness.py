"""Readiness probes for the ``/ready`` endpoint (plan 64 §1.4 / ADR-0062 §9).

Readiness is the **hard** gate: the datastore is reachable **and at this
release's migration head**. Liveness (``/health``) answers "is the process
up"; readiness answers "should traffic reach me yet" — the migrate job has
completed, the schema matches the running code, and required object storage
is available (checked in ``app.main``, reusing the storage health probe).

A soft signal (Redis, queue age, optional storage) never flips readiness.
Any hard-check failure is a ``503``, never a degraded ``200``.
"""

from __future__ import annotations

from app.core.config import settings

# Bound a hung/unreachable database so the probe answers inside a
# provider's probe window (compose healthcheck timeout is 5-10 s).
_CONNECT_TIMEOUT_SECONDS = 3


def database_at_head(url: str | None = None) -> tuple[bool, str]:
    """``(ready, detail)``: is the datastore reachable and at Alembic head?

    Details are operator-facing tokens (``unreachable: …``, ``not-migrated``,
    ``at <rev>`` / ``behind: <rev> -> <head>``); the boolean is the only
    signal readiness flips on.
    """
    from sqlalchemy import create_engine, text

    from app.local import head_revision
    from app.storage.datastore_guard import _sync_url

    source = url if url is not None else settings.database_url
    try:
        target = head_revision()
    except Exception:  # a broken/unreadable local alembic chain
        return False, "no-head"

    connect_args: dict[str, object] = {}
    if source.startswith("postgresql"):
        connect_args["connect_timeout"] = _CONNECT_TIMEOUT_SECONDS
    engine = create_engine(_sync_url(source), pool_pre_ping=False, connect_args=connect_args)
    try:
        with engine.connect() as connection:
            row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception as exc:
        detail = type(exc).__name__
        orig = getattr(exc, "orig", None)
        if orig is not None:
            detail = type(orig).__name__
        return False, f"unreachable: {detail}"
    finally:
        engine.dispose()

    revision = str(row[0]) if row and row[0] is not None else None
    if revision is None:
        return False, "not-migrated"
    if revision != target:
        return False, f"behind: {revision} -> {target}"
    return True, f"at {target}"
