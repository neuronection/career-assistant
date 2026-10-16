"""Reference T2 connector (plan 32 Phase 5): fetch postings through the
host's polite runtime, dedupe against extension-owned state and emit the
fresh rows. ~30 lines — the whole authoring story.

The sandbox's entire SDK is the vendored ``capability`` module: net via
``net_fetch`` (host-mediated, scoped to the manifest's declared domains on
every hop), persistence via ``state_get``/``state_set``, results via
``items_emit`` (every row is schema-validated host-side). No sockets, no
files, no environment — the audit wall denies them.
"""

import json

from capability import items_emit, net_fetch, progress, state_get, state_set


def fetch(config, state):
    """One sync tick: ``config`` is the instance config, ``state`` the
    host-round-tripped sync cursor (opaque to us)."""
    response = net_fetch(config["url"], headers={"Accept": "application/json"})
    rows = json.loads(response["body"])
    progress(percent=50, message_key="fetch.fetched")
    seen = set(state_get("seen") or [])
    fresh = [row for row in rows if row["external_id"] not in seen]
    items_emit(fresh)
    state_set("seen", sorted(seen | {row["external_id"] for row in fresh}))
    progress(percent=100, message_key="fetch.done")
    return {"next_state": {"fetched": len(rows)}, "stats": {"fresh": len(fresh)}}
