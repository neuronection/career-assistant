#!/usr/bin/env python
"""Operate the embedding-space lifecycle (plan 50 §3.4/§11, P2c.1).

Non-interactive subcommands: ``list``, ``status``, ``build``, ``backfill``,
``activate``, ``retire``, ``drop``. The service owns the transitions; this
script is a thin CLI over it (plan 51's HTTP actions wrap the same service).

* ``build`` creates a ``building`` space beside the active one and provisions
  its physical table. It never touches the active pointer.
* ``backfill`` enqueues the ordinary ``VECTOR_RECONCILE`` job with an explicit
  ``space_id`` (same handler/writer as a normal reconcile), so a long run is
  off the request path and shows up in ``background_jobs``. ``--wait`` waits
  for the first bounded batch; the continuation chain keeps running.
* ``activate`` checks the physical index + coverage gate, flips the pointer
  atomically, retires the old space and enqueues the one ``POSTING_REMAP``
  for the retired key.
* ``retire`` only accepts a non-active space. ``drop`` only accepts a retired
  space after the grace period, or ``--force --confirm <name>``. The active
  space can never be dropped.

Usage (the app's interpreter, e.g. ``uv run python``)::

    python scripts/vector_spaces.py list
    python scripts/vector_spaces.py build --name content --provider openai \
        --model text-embedding-3-small --dim 1536
    python scripts/vector_spaces.py backfill <space-id> --kinds posting,skill --wait
    python scripts/vector_spaces.py activate <space-id> --kinds posting,skill
    python scripts/vector_spaces.py retire <space-id>
    python scripts/vector_spaces.py drop <space-id> --force --confirm content

Exit codes: 0 success, 2 refused arguments/state/gate, 1 unexpected error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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


def _store():
    from app.core.database import sync_engine
    from app.storage.vector_store import VectorStoreService

    return VectorStoreService(sync_engine)


def _service(db=None):
    from app.services.vector_space_lifecycle import VectorSpaceLifecycleService

    return VectorSpaceLifecycleService(db, store=_store())


def _parser() -> argparse.ArgumentParser:
    from app.services.vector_composers import CHUNKER_VERSION, COMPOSER_VERSION
    from app.services.vector_reconcile_service import (
        DEFAULT_BATCH_SIZE,
        DEFAULT_BUDGET,
        DEFAULT_LIMIT,
        DEFAULT_SCAN_LIMIT,
        RECONCILE_KINDS,
    )
    from app.services.vector_space_lifecycle import SPACE_DROP_GRACE

    parser = argparse.ArgumentParser(description="Operate embedding-space lifecycles.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list every space with status, health and coverage")

    status = sub.add_parser("status", help="show one space by id or name")
    status.add_argument("space", help="space id or name")

    build = sub.add_parser("build", help="create a building space and provision its table")
    build.add_argument("--name", required=True, help="space name (e.g. content)")
    build.add_argument("--provider", required=True)
    build.add_argument("--model", required=True)
    build.add_argument("--dim", type=int, required=True)
    build.add_argument("--metric", default="cosine")
    build.add_argument("--no-normalize", dest="normalize", action="store_false")
    build.add_argument("--query-prefix", default=None)
    build.add_argument("--document-prefix", default=None)
    build.add_argument("--chunker-version", default=CHUNKER_VERSION)
    build.add_argument("--composer-version", default=COMPOSER_VERSION)
    build.add_argument(
        "--token-aware",
        action="store_true",
        help=(
            "build a token-aware v2 space using the effective embedding profile "
            "(admin override → curated → fallback) for this provider/model"
        ),
    )
    build.set_defaults(normalize=True)

    backfill = sub.add_parser("backfill", help="enqueue a bounded backfill of a building space")
    backfill.add_argument("space", help="space id or name")
    backfill.add_argument(
        "--kinds",
        default=",".join(RECONCILE_KINDS),
        help=f"comma-separated kinds (default: {','.join(RECONCILE_KINDS)})",
    )
    backfill.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    backfill.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    backfill.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    backfill.add_argument("--scan-limit", type=int, default=DEFAULT_SCAN_LIMIT)
    backfill.add_argument("--since", default=None, help="ISO timestamp — only rows updated since")
    backfill.add_argument("--force", action="store_true", help="re-embed unchanged content")
    backfill.add_argument(
        "--no-auto-continue",
        dest="auto_continue",
        action="store_false",
        help="do not enqueue the next bounded batch",
    )
    backfill.add_argument("--wait", action="store_true", help="wait for the first bounded batch")
    backfill.add_argument("--timeout", type=int, default=1800)
    backfill.set_defaults(auto_continue=True)

    activate = sub.add_parser("activate", help="flip a covered building space to active")
    activate.add_argument("space", help="space id or name")
    activate.add_argument("--coverage-gate", type=float, default=0.995)
    activate.add_argument(
        "--kinds",
        default=",".join(RECONCILE_KINDS),
        help="kinds that must have a passing coverage snapshot",
    )

    retire = sub.add_parser("retire", help="retire a non-active space")
    retire.add_argument("space", help="space id or name")

    drop = sub.add_parser("drop", help="drop a retired space after its grace period")
    drop.add_argument("space", help="space id or name")
    drop.add_argument("--force", action="store_true", help="skip the grace period")
    drop.add_argument(
        "--confirm",
        default=None,
        metavar="NAME",
        help="the typed space name required by --force",
    )
    drop.add_argument(
        "--grace-days",
        type=int,
        default=SPACE_DROP_GRACE.days,
        help=f"retention grace period (default: {SPACE_DROP_GRACE.days} days)",
    )
    return parser


def _format_space(entry: dict[str, Any]) -> str:
    coverage = entry.get("coverage") or {}
    percent = coverage.get("percent")
    physical = entry.get("physical") or {}
    table = entry.get("index_table") or "-"
    health = "linear" if table == "-" else ("ok" if physical.get("table_exists") else "missing")
    return (
        f"{entry['status']:<8} {entry['name']:<14} {entry['space_id']} "
        f"backend={entry.get('backend', '-'):<10} table={table:<14} "
        f"docs={entry.get('documents', 0):<6} records={entry.get('records', 0):<6} "
        f"coverage={'-' if percent is None else f'{percent:.2f}%':<8} "
        f"health={health} key={entry.get('space_key', '-')}"
    )


def _print_space(entry: dict[str, Any]) -> None:
    coverage = entry.get("coverage") or {}
    physical = entry.get("physical") or {}
    print(f"space_id:       {entry['space_id']}")
    print(f"name:           {entry['name']}")
    print(f"status:         {entry['status']}")
    print(f"space_key:      {entry.get('space_key')}")
    provider_model = f"{entry.get('provider')} / {entry.get('model')}"
    print(f"provider/model: {provider_model} (dim {entry.get('dim')})")
    print(f"backend:        {entry.get('backend')}")
    print(f"index_table:    {entry.get('index_table')}")
    print(f"physical:       {physical.get('detail')}")
    empty_documents = entry.get("documents_without_records")
    print(f"documents:      {entry.get('documents')} ({empty_documents} empty)")
    print(f"records:        {entry.get('records')}")
    print(
        "coverage:       "
        + (
            "never reconciled"
            if coverage.get("source") != "snapshot"
            else (
                f"{coverage.get('percent')}% "
                f"(embedded {coverage.get('embedded')}/{coverage.get('total')}, "
                f"missing {coverage.get('missing')}, stale {coverage.get('stale')}, "
                f"failed {coverage.get('failed')})"
            )
        )
    )
    print(f"backfill:       {entry.get('backfill_done')}/{entry.get('backfill_total')}")
    print(f"activated_at:   {entry.get('activated_at')}")
    print(f"retired_at:     {entry.get('retired_at')}")
    last = entry.get("last_reindex")
    if last:
        print(
            f"last_job:       {last.get('job_type')} {last.get('status')} "
            f"{last.get('stage') or ''} {last.get('error') or ''}".rstrip()
        )


def _entry_for(service, ref: str) -> dict[str, Any]:
    return service.status(ref)


def _backfill_payload(args, entry: dict[str, Any]) -> dict[str, Any]:
    from app.services.vector_reconcile_service import parse_kinds, parse_since

    payload: dict[str, Any] = {
        "space_id": entry["space_id"],
        "space": entry["name"],
        "limit": max(1, args.limit),
        "budget": max(0, args.budget),
        "batch_size": max(1, args.batch_size),
        "scan_limit": max(1, args.scan_limit),
        "force": bool(args.force),
        "auto_continue": bool(args.auto_continue),
    }
    kinds = parse_kinds(args.kinds)
    if kinds:
        payload["kinds"] = list(kinds)
    since = parse_since(args.since)
    if since is not None:
        payload["since"] = since.isoformat()
    return payload


async def _enqueue_backfill(payload: dict[str, Any]) -> str:
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


async def _run(args) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.enums import BackgroundJobStatus
    from app.services.vector_space_lifecycle import SpaceStateError

    if args.command == "list":
        for entry in _service().list_spaces():
            print(_format_space(entry))
        return 0

    if args.command == "status":
        _print_space(_service().status(args.space))
        return 0

    if args.command == "build":
        async with AsyncSessionLocal() as db:
            service = _service(db)
            tokenizer = chunk = None
            if args.token_aware:
                from app.services import embedding_profiles

                profile = await embedding_profiles.resolve_for(
                    db, args.provider, args.model
                )
                tokenizer, chunk = profile.tokenizer, profile.chunk
            built = await service.build_space(
                args.name,
                provider=args.provider,
                model=args.model,
                dim=args.dim,
                metric=args.metric,
                normalize=args.normalize,
                query_prefix=args.query_prefix,
                document_prefix=args.document_prefix,
                chunker_version=args.chunker_version,
                composer_version=args.composer_version,
                tokenizer=tokenizer,
                chunk=chunk,
            )
        print(json.dumps(built.as_dict(), indent=2, default=str))
        return 0

    if args.command == "backfill":
        service = _service()
        entry = _entry_for(service, args.space)
        if entry["status"] != "building":
            raise SpaceStateError(
                f"space {entry['name']!r} is {entry['status']!r}; backfill targets a building space"
            )
        payload = _backfill_payload(args, entry)
        job_id = await _enqueue_backfill(payload)
        print(f"enqueued vector_reconcile job {job_id} for space {entry['space_id']}")
        if not args.wait:
            return 0
        job = await _wait(job_id, max(1, args.timeout))
        if job is None:
            print(f"timed out waiting for {job_id}", file=sys.stderr)
            return 1
        print(f"status={job.status} error={job.error or ''}")
        if isinstance(job.result, dict):
            print(json.dumps(job.result, indent=2, default=str))
        return 0 if job.status == BackgroundJobStatus.SUCCEEDED.value else 1

    async with AsyncSessionLocal() as db:
        service = _service(db)
        if args.command == "activate":
            result = await service.activate_space(
                args.space,
                coverage_gate=args.coverage_gate,
                kinds=args.kinds,
            )
            print(json.dumps(result.as_dict(), indent=2, default=str))
            return 0
        if args.command == "retire":
            print(json.dumps(await service.retire_space(args.space), indent=2, default=str))
            return 0
        if args.command == "drop":
            from datetime import timedelta

            print(
                json.dumps(
                    await service.drop_space(
                        args.space,
                        force=args.force,
                        confirm=args.confirm,
                        grace=timedelta(days=max(0, args.grace_days)),
                    ),
                    indent=2,
                    default=str,
                )
            )
            return 0
    raise SystemExit(f"unknown command {args.command!r}")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    from app.services.vector_space_lifecycle import (
        SpaceCoverageError,
        SpaceLifecycleError,
        SpaceStateError,
    )
    from app.storage.vector_provisioning import VectorProvisioningError

    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (
        SpaceCoverageError,
        SpaceStateError,
        SpaceLifecycleError,
        VectorProvisioningError,
        ValueError,
    ) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
