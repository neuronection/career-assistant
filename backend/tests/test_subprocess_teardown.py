"""Bounded subprocess communication never leaves an open transport.

Regression for the CI ``PytestUnraisableExceptionWarning`` on
``BaseSubprocessTransport.__del__`` (``RuntimeError: Event loop is closed``):
a cancelled ``communicate()`` used to abandon the pipe readers, so the
transport was only reaped by the GC — possibly after the session event loop
closed. :func:`app.core.subprocess.communicate_and_reap` kills and reaps the
child, then lets ``communicate()`` drain the pipes and close the transport
before the exception leaves the frame.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.core.subprocess import communicate_and_reap


async def _spawn_sleeper() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def test_timeout_reaps_the_child_and_closes_the_transport() -> None:
    process = await _spawn_sleeper()
    transport = process._transport
    assert transport is not None and not transport.is_closing()

    with pytest.raises(TimeoutError):
        await communicate_and_reap(process, timeout=0.05)

    assert process.returncode is not None, "the child was reaped, not abandoned"
    assert transport.is_closing(), (
        "the subprocess transport must be closed before the loop can close — "
        "an open transport is what triggers BaseSubprocessTransport.__del__ "
        "after loop shutdown"
    )


async def test_cancellation_reaps_the_child_and_closes_the_transport() -> None:
    process = await _spawn_sleeper()
    transport = process._transport
    assert transport is not None and not transport.is_closing()

    pending = asyncio.create_task(communicate_and_reap(process, timeout=60))
    await asyncio.sleep(0.05)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert process.returncode is not None
    assert transport.is_closing()
