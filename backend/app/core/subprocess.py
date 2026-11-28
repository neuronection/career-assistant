"""Bounded subprocess communication with a deterministic teardown.

``asyncio`` subprocess transports are only closed once the child has been
reaped *and* every pipe has reached EOF. A cancelled ``communicate()`` (a
watchdog timeout, a cancelled request) abandons the pipe readers, so the
transport survives until the garbage collector drops it — and when that
happens after the event loop was closed, ``BaseSubprocessTransport.__del__``
raises ``RuntimeError: Event loop is closed`` from an unraisable hook (a
``PytestUnraisableExceptionWarning`` in tests, a silent stderr traceback in
production).

:func:`communicate_and_reap` keeps the ``communicate()`` task alive across the
timeout/cancellation, kills the child, and lets that same task drain the pipes
and close the transport before the exception leaves the frame.
"""

from __future__ import annotations

import asyncio
import contextlib


async def communicate_and_reap(
    process: asyncio.subprocess.Process,
    *,
    timeout: float,
) -> tuple[bytes, bytes]:
    """``process.communicate()`` bounded by ``timeout``, always reaped.

    Raises :class:`TimeoutError` when the deadline passes; the child is killed
    and its transport closed before it propagates. Cancellation of the caller
    likewise kills and reaps the child first.
    """
    communication = asyncio.ensure_future(process.communicate())
    try:
        return await asyncio.wait_for(asyncio.shield(communication), timeout)
    except BaseException:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                process.kill()
        # ``communicate()`` was shielded from the cancellation above, so it is
        # still reading: it now drains the pipes to EOF and closes the
        # transport. Shield the wait too, so a second cancellation still lets
        # the teardown finish.
        with contextlib.suppress(BaseException):
            await asyncio.shield(communication)
        raise


__all__ = ["communicate_and_reap"]
