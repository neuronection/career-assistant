"""Career's SSE wire adapter for the family flow-event builders (plan 25 A3).

Career's transport mapping (ai-features §5) is SSE *named events*: the
event name rides the ``event:`` line and the payload carries no in-band
name key. The vendored family builders (``ai/flow_events.py``) return
``{"event": <name>, ...fields}``; ``sse_pair`` splits that into career's
``(name, payload)`` emit convention, so the wire payload matches the
previous inline literals field for field. Payload dicts where career's
dialect differs from the §5 fields (node ids/labels, the main-chat
``flow_started`` stage/found extras) stay inline at their emitters.
"""

from typing import Any


def sse_pair(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Split a builder event into career's (name, payload) SSE convention."""
    return event.pop("event"), event
