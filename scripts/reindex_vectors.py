#!/usr/bin/env python
"""Enqueue a vector backfill/reconcile run (plan 50 P1d).

Thin enqueue, never a second writer: the ``VECTOR_RECONCILE`` handler owns
composing, classification, the embedding budget and the coverage snapshots,
so every script run is a ``background_jobs`` row the runs surface can show.
The embed calls are attributed to the system path (no admin budget is
charged).

Usage (interpreter with the app's dependencies, e.g. ``uv run python``):

    # everything, one bounded pass (the worker must be running):
    python scripts/reindex_vectors.py

    # postings only, re-embed unchanged content, wait for the result:
    python scripts/reindex_vectors.py --kinds posting --force --wait

    # the final delta pass before a space cutover (rows touched in 24h):
    python scripts/reindex_vectors.py --since 2026-11-02T00:00:00Z --wait

A run scans a bounded keyset batch per kind (``--scan-limit`` source rows),
classifies each source and spends at most ``--budget`` embed units (and
``--limit`` documents). A partial batch enqueues one follow-up with the same
options plus its cursor unless ``--no-auto-continue`` is given, so the job
chain resumes the backfill without loading the whole corpus. Whatever is left
is still missing/stale for the next run, so an unchanged corpus costs zero
embedding calls. ``--wait`` waits for the first job only; the continuation
chain keeps running in the worker (use ``--no-auto-continue`` for one batch).

Exit codes: 0 enqueued (or the finished run succeeded), 2 refused arguments,
1 unexpected error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_CANDIDATES = (REPO_ROOT / "backend", REPO_ROOT)
BACKEND_DIR = next(
    (candidate for candidate in _BACKEND_CANDIDATES if (candidate / "app" / "models").is_dir()),
    REPO_ROOT / "backend",
)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

def _parser() -> argparse.ArgumentParser:
    from app.services.vector_reconcile_service import (
        DEFAULT_BATCH_SIZE,
        DEFAULT_BUDGET,
        DEFAULT_LIMIT,
        DEFAULT_SCAN_LIMIT,
        RECONCILE_KINDS,
    )

    parser = argparse.ArgumentParser(
        description="Enqueue a resumable, budget-capped vector backfill/reconcile run."
    )
    parser.add_argument(
        "--kinds",
        default=",".join(RECONCILE_KINDS),
        help=f"comma-separated source kinds (default: {','.join(RECONCILE_KINDS)})",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="documents per run")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="embed units per run")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=DEFAULT_SCAN_LIMIT,
        help="source rows per keyset batch (the scan never loads the whole corpus)",
    )
    parser.add_argument("--since", default=None, help="ISO timestamp — only rows updated since")
    parser.add_argument("--force", action="store_true", help="re-embed even unchanged content")
    parser.add_argument(
        "--no-auto-continue",
        dest="auto_continue",
        action="store_false",
        help="do not enqueue the next bounded batch automatically",
    )
    parser.add_argument("--wait", action="store_true", help="poll until the queued run finishes")
    parser.add_argument("--timeout", type=int, default=1800, help="wait timeout in seconds")
    return parser


async def _enqueue(payload: dict[str, Any]) -> str:
    from app.core.database import AsyncSessionLocal
    from app.models.enums import BackgroundJobType
    from app.services.job_worker import enqueue

    async with AsyncSessionLocal() as db:
        job = await enqueue(db, BackgroundJobType.VECTOR_RECONCILE.value, payload)
        return str(job.id)


async def _wait(job_id: str, timeout: int) -> Any:
    from uuid import UUID

    from app.core.database import AsyncSessionLocal
    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobStatus

    terminal = (
        BackgroundJobStatus.SUCCEEDED.value,
        BackgroundJobStatus.FAILED.value,
        BackgroundJobStatus.CANCELLED.value,
    )
    deadline = time.monotonic() + timeout
    async with AsyncSessionLocal() as db:
        while time.monotonic() < deadline:
            job = await db.get(BackgroundJob, UUID(job_id))
            if job is not None and job.status in terminal:
                return job
            await asyncio.sleep(2.0)
    return None


def _summarize(result: dict[str, Any]) -> str:
    kinds = ", ".join(
        f"{entry['kind']} {entry['embedded']}/{entry['total']}"
        for entry in result.get("kinds") or []
    )
    return (
        f"scanned={result.get('scanned')} embedded={result.get('embedded')} "
        f"skipped={result.get('skipped')} deferred={result.get('deferred')} "
        f"failed={result.get('failed')} orphans={result.get('orphans_removed')} "
        f"cancelled={result.get('cancelled')} budget_exhausted={result.get('budget_exhausted')} "
        f"[{kinds}]"
    )


async def main(argv: list[str] | None = None) -> int:
    from app.models.enums import BackgroundJobStatus, BackgroundJobType
    from app.services.vector_reconcile_service import parse_kinds, parse_since

    args = _parser().parse_args(argv)
    try:
        kinds = parse_kinds(args.kinds)
        since = parse_since(args.since)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    payload: dict[str, Any] = {
        "limit": max(1, args.limit),
        "budget": max(0, args.budget),
        "batch_size": max(1, args.batch_size),
        "scan_limit": max(1, args.scan_limit),
        "force": bool(args.force),
        "auto_continue": bool(args.auto_continue),
    }
    if kinds:
        payload["kinds"] = list(kinds)
    if since is not None:
        payload["since"] = since.isoformat()
    job_id = await _enqueue(payload)
    print(f"enqueued {BackgroundJobType.VECTOR_RECONCILE.value} job {job_id}")
    if not args.wait:
        return 0
    job = await _wait(job_id, max(1, args.timeout))
    if job is None:
        print(f"timed out waiting for {job_id}", file=sys.stderr)
        return 1
    print(f"status={job.status} error={job.error or ''}")
    if isinstance(job.result, dict):
        print(_summarize(job.result))
    return 0 if job.status == BackgroundJobStatus.SUCCEEDED.value else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
