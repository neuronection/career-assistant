"""In-process SSE hub for live notification delivery (plan 36).

The REST endpoints stay source of truth; this hub only pushes hints
(new inbox rows, unread-count changes) to connected SPAs and the desktop
webview. Single-process by design (the desktop shell runs the server
in-process; self-host runs one API worker) — the same trade-off as the
plan-13 chat stream.
"""

import asyncio
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

_MAX_QUEUE = 100

_subscribers: dict[UUID, set[asyncio.Queue]] = {}


def subscribe(user_id: UUID) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
    _subscribers.setdefault(user_id, set()).add(queue)
    return queue


def unsubscribe(user_id: UUID, queue: asyncio.Queue) -> None:
    queues = _subscribers.get(user_id)
    if queues is not None:
        queues.discard(queue)
        if not queues:
            _subscribers.pop(user_id, None)


def publish(user_id: UUID, event: str, data: dict) -> None:
    """Drop-oldest publish; SSE is a hint, never a queue of record."""
    for queue in list(_subscribers.get(user_id, ())):
        payload = {"event": event, "data": data}
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:  # pragma: no cover — drop-oldest above
            pass


def subscriber_count(user_id: UUID) -> int:
    return len(_subscribers.get(user_id, ()))
