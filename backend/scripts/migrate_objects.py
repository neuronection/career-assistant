"""Copy career's legacy upload tree into the configured object store.

Family tooling for plan 55 P4 (see ``docs/dev/storage.md``). Career's mapping
is database-driven because the pre-contract layout encodes ownership in the
row, not in the path:

* `<upload_dir>/<document-id><ext>` -> `tenants/<user>/documents/<id><ext>`
* `<upload_dir>/derived/<document-id>/page-<n>.png`
  -> `tenants/<user>/cv_pages/<id>-p<n>.png`
* `<upload_dir>/exports/career-assistant-export-<job-id>.zip`
  -> `tenants/<user>/exports/<job-id>.zip` (only when the job row still
  exists; an export without a stable owner is regenerable, never guessed)

Documents and CV pages also backfill the database: `documents.object_key` and
the `pages[].image_path` keys inside `documents.extraction`. Exports update the
job result's `export_key` and drop the legacy `export_path`.

Usage (run from ``backend/`` with the project environment active):

    python scripts/migrate_objects.py --dry-run
    python scripts/migrate_objects.py --apply
    python scripts/migrate_objects.py --verify
    python scripts/migrate_objects.py --backfill-db

The manifest defaults to `<data_dir>/migrations/object-storage-manifest.json`.
Desktop never runs this tool. The target store comes from the resolved
`CAREER_*` settings, so point the process at the destination (a staging local
root or the object backend) without changing the running app's configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import AsyncSessionLocal
from app.models.background_job_model import BackgroundJob
from app.models.document_model import Document
from app.services.profile.document_storage import (
    document_key,
    export_key,
    legacy_document_path,
    legacy_page_path,
    page_key,
)
from app.storage.bootstrap import resolve_storage_config, storage_entrypoint
from app.storage.object_storage import (
    BACKEND_LOCAL,
    ENTRYPOINT_DESKTOP,
    build_store,
)
from app.storage.object_storage_migrate import (
    STATUS_MISSING,
    STATUS_SKIPPED,
    STATUS_VERIFIED,
    Manifest,
    ManifestError,
    ManifestTargetMismatch,
    MigrationEntry,
    TargetNotEmpty,
    VerifyRequired,
    bind_target,
    check_binding,
    load_manifest,
    merge_entries,
    new_manifest,
    plan_entries,
    rebind_manifest,
    require_verified,
    save_manifest,
    target_descriptor,
)
from app.storage.object_storage_migrate import (
    apply as apply_entries,
)
from app.storage.object_storage_migrate import (
    verify as verify_entries,
)

HOST = "career-assistant"
_EXPORT_NAME = re.compile(
    r"^career-assistant-export-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.zip$"
)
_PAGE_NAME = re.compile(r"^page-(\d+)\.png$")
_PROBLEM_STATUSES = {"failed", "missing", "unreadable", "collision", "skipped"}
_BLOCKING_STATUSES = {"failed", "missing", "unreadable", "collision"}


def default_manifest_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / "migrations" / "object-storage-manifest.json"


@dataclass
class Planned:
    entries: list[MigrationEntry]
    media: dict[str, str] = field(default_factory=dict)
    unstable: set[str] = field(default_factory=set)


async def load_rows(session: AsyncSession) -> tuple[list[Document], list[BackgroundJob]]:
    documents = list((await session.scalars(select(Document))).all())
    query = select(BackgroundJob).where(BackgroundJob.job_type == "data_export")
    exports = list((await session.scalars(query)).all())
    return documents, exports


def build_plan(
    settings: Settings,
    documents: list[Document],
    exports: list[BackgroundJob],
) -> Planned:
    """Map every known legacy file to its key, using the service key helpers."""
    root = Path(settings.upload_root)
    mapping: dict[str, str] = {}
    media: dict[str, str] = {}
    expected: list[tuple[str, str]] = []
    unstable: set[str] = set()

    for document in documents:
        source = legacy_document_path(document, root)
        key = document_key(document.user_id, document.id, document.filename)
        relative = source.relative_to(root).as_posix()
        mapping[relative] = key
        media[key] = document.mime or "application/octet-stream"
        expected.append((relative, key))

        pages_dir = legacy_page_path(document.id, 0, root).parent
        if pages_dir.is_dir():
            for page_file in sorted(pages_dir.glob("page-*.png")):
                match = _PAGE_NAME.match(page_file.name)
                if match is None:
                    continue
                index = int(match.group(1))
                page_relative = page_file.relative_to(root).as_posix()
                page_object = page_key(document.user_id, document.id, index)
                mapping[page_relative] = page_object
                media[page_object] = "image/png"
                expected.append((page_relative, page_object))

    jobs = {job.id: job for job in exports if job.user_id is not None}
    exports_dir = root / "exports"
    if exports_dir.is_dir():
        for archive in sorted(exports_dir.glob("*.zip")):
            relative = archive.relative_to(root).as_posix()
            match = _EXPORT_NAME.match(archive.name)
            job = jobs.get(uuid.UUID(match.group(1))) if match is not None else None
            if job is None:
                unstable.add(relative)
                continue
            assert job.user_id is not None  # jobs dict filters unowned rows
            key = export_key(job.user_id, job.id)
            mapping[relative] = key
            media[key] = "application/zip"
            expected.append((relative, key))

    entries = plan_entries(root, lambda relative: mapping.get(relative))
    planned_sources = {entry.source for entry in entries}
    for relative, key in expected:
        if relative in planned_sources:
            continue
        entries.append(
            MigrationEntry(
                source=relative,
                key=key,
                status=STATUS_MISSING,
                error="source file is missing",
            )
        )
    for entry in entries:
        if entry.source in unstable:
            entry.key = ""
            entry.status = STATUS_SKIPPED
            entry.error = "no stable owner/job row; the export is regenerable"
    return Planned(entries=entries, media=media, unstable=unstable)


def _report(manifest: Manifest, label: str) -> None:
    counts = manifest.counts()
    print(
        f"{label}: {counts['total']} entries — "
        f"copied {counts['copied']}, verified {counts['verified']}, "
        f"pending {counts['pending']}, failed {counts['failed']}, "
        f"missing {counts['missing']}, unreadable {counts['unreadable']}, "
        f"collision {counts['collision']}, skipped {counts['skipped']}"
    )
    problems = [entry for entry in manifest.entries if entry.status in _PROBLEM_STATUSES]
    for entry in problems[:20]:
        print(f"  {entry.status}: {entry.source} — {entry.error}")
    if len(problems) > 20:
        print(f"  … {len(problems) - 20} more")


def _looks_like_object_key(value: str) -> bool:
    """A pre-migration key already stored in a row (never rewrite blindly)."""
    return value.startswith(("tenants/", "sha256/"))


def _is_legacy_page_path(value: str) -> bool:
    """Only the pre-contract page locations are eligible for a rewrite."""
    normalized = value.replace("\\", "/")
    return (
        normalized.startswith(("uploads/derived/", "derived/")) or "/uploads/derived/" in normalized
    )


async def backfill(session: AsyncSession, manifest: Manifest) -> dict[str, int]:
    """Rewrite document keys/extraction pages and legacy export paths.

    Only objects verified in the manifest are written; a document whose
    source object is not verified keeps its legacy read path. Idempotent: a
    second run changes nothing.
    """
    verified = manifest.keys({STATUS_VERIFIED})
    updated_documents = 0
    rewritten_pages = 0
    preserved_pages = 0
    updated_exports = 0

    documents = list((await session.scalars(select(Document))).all())
    for document in documents:
        key = document_key(document.user_id, document.id, document.filename)
        if key not in verified:
            continue
        changed = False
        if document.object_key != key:
            document.object_key = key
            changed = True
        extraction = document.extraction
        if isinstance(extraction, dict) and isinstance(extraction.get("pages"), list):
            pages = []
            for page in extraction["pages"]:
                if isinstance(page, dict) and page.get("image_path"):
                    image_path = page["image_path"]
                    if isinstance(image_path, str) and _looks_like_object_key(image_path):
                        # Already a key (possibly verified by another run);
                        # never replace or null it from a best-effort mapping.
                        pages.append(page)
                        continue
                    if not isinstance(image_path, str) or not _is_legacy_page_path(image_path):
                        # An unrecognised value is not silently treated as a
                        # legacy path; leave it and report it.
                        preserved_pages += 1
                        pages.append(page)
                        continue
                    index = page.get("index")
                    candidate = (
                        page_key(document.user_id, document.id, index)
                        if isinstance(index, int)
                        else None
                    )
                    if candidate is not None and candidate in verified:
                        if candidate != image_path:
                            page = {**page, "image_path": candidate}
                            rewritten_pages += 1
                            changed = True
                    else:
                        # No verified object for this legacy page: leave the
                        # value in place and report it; the API scrubber still
                        # hides it until a later migration run.
                        preserved_pages += 1
                pages.append(page)
            if changed:
                document.extraction = {**extraction, "pages": pages}
        if changed:
            session.add(document)
            updated_documents += 1

    query = select(BackgroundJob).where(BackgroundJob.job_type == "data_export")
    exports = list((await session.scalars(query)).all())
    for job in exports:
        if job.user_id is None:
            continue
        key = export_key(job.user_id, job.id)
        if key not in verified:
            continue
        result = dict(job.result or {})
        if result.get("export_key") != key or "export_path" in result:
            result.pop("export_path", None)
            result["export_key"] = key
            job.result = result
            session.add(job)
            updated_exports += 1

    await session.commit()
    return {
        "documents": updated_documents,
        "pages": rewritten_pages,
        "pages_unmigrated": preserved_pages,
        "exports": updated_exports,
    }


async def _plan_or_load(
    session: AsyncSession,
    settings: Settings,
    manifest_path: Path,
    *,
    force: bool,
    store,
    rebind: bool,
) -> tuple[Manifest, dict[str, str]]:
    source = Path(settings.upload_root)
    documents, exports = await load_rows(session)
    planned = build_plan(settings, documents, exports)
    if manifest_path.exists():
        try:
            manifest = load_manifest(manifest_path)
        except ManifestError as exc:
            if not force:
                raise SystemExit(
                    f"corrupt manifest {manifest_path}: {exc}. "
                    "Move it aside or pass --force to start a fresh ledger."
                ) from exc
            print(f"ignoring corrupt manifest (--force): {exc}")
            manifest = new_manifest(HOST, source, path=manifest_path)
            bind_target(manifest, store)
        else:
            if rebind:
                rebind_manifest(manifest, store, host=HOST, source_root=source)
            else:
                check_binding(manifest, store, host=HOST, source_root=source)
    else:
        manifest = new_manifest(HOST, source, path=manifest_path)
        bind_target(manifest, store)
    merge_entries(manifest, planned.entries)
    manifest.path = str(manifest_path)
    return manifest, planned.media


def _refuse_self_copy(settings: Settings, store) -> None:
    if store.backend != BACKEND_LOCAL:
        return
    source = Path(settings.upload_root).resolve()
    target = Path(getattr(store, "root", source)).resolve()
    if source == target:
        raise SystemExit(
            f"source and target are the same local root ({source}); nothing to copy. "
            "Set CAREER_OBJECT_STORAGE_LOCAL_ROOT to a staging directory or run this "
            "process with the target object backend configured."
        )
    if source in target.parents or target in source.parents:
        raise SystemExit(
            f"source ({source}) and target ({target}) roots are nested; use "
            "separate directory trees so a copy can never read its own output."
        )


async def run_async(
    args: argparse.Namespace,
    settings: Settings,
    *,
    session_factory=None,
) -> int:
    if storage_entrypoint(settings) == ENTRYPOINT_DESKTOP:
        raise SystemExit(
            "desktop is local-only: there is no bucket to migrate to. "
            "migrate-objects never runs on a desktop build."
        )
    factory = session_factory or AsyncSessionLocal
    manifest_path = Path(args.manifest) if args.manifest else default_manifest_path(settings)
    config = resolve_storage_config(settings)
    store = build_store(config)
    print(f"target: {target_descriptor(store).label()}")
    try:
        if args.verify:
            try:
                manifest = load_manifest(manifest_path)
            except FileNotFoundError:
                raise SystemExit(f"no manifest at {manifest_path}; run --apply first") from None
            except ManifestError as exc:
                raise SystemExit(f"corrupt manifest {manifest_path}: {exc}") from exc
            source = Path(settings.upload_root)
            try:
                if args.rebind:
                    rebind_manifest(manifest, store, host=HOST, source_root=source)
                    save_manifest(manifest_path, manifest)
                else:
                    check_binding(manifest, store, host=HOST, source_root=source)
            except ManifestTargetMismatch as exc:
                raise SystemExit(str(exc)) from exc
            summary = verify_entries(store, manifest, host=HOST, source_root=source)
            _report(manifest, "verify")
            if summary["blocking"]:
                print(
                    f"blocking: {summary['blocking']} entry/entries — {summary['blocking_entries']}"
                )
            return 0 if summary["blocking"] == 0 else 1

        if args.backfill_db:
            try:
                manifest = load_manifest(manifest_path)
            except FileNotFoundError:
                raise SystemExit(
                    f"no manifest at {manifest_path}; run --apply and --verify first"
                ) from None
            except ManifestError as exc:
                raise SystemExit(f"corrupt manifest {manifest_path}: {exc}") from exc
            source = Path(settings.upload_root)
            try:
                if args.rebind:
                    rebind_manifest(manifest, store, host=HOST, source_root=source)
                    save_manifest(manifest_path, manifest)
                else:
                    check_binding(manifest, store, host=HOST, source_root=source)
                require_verified(manifest)
            except (ManifestTargetMismatch, VerifyRequired) as exc:
                raise SystemExit(str(exc)) from exc
            async with factory() as session:
                counts = await backfill(session, manifest)
            print(
                "backfill: documents {documents}, extraction pages {pages}, "
                "unmigrated pages {pages_unmigrated}, exports {exports}".format(**counts)
            )
            return 0

        try:
            async with factory() as session:
                manifest, media = await _plan_or_load(
                    session,
                    settings,
                    manifest_path,
                    force=args.force,
                    store=store,
                    rebind=args.rebind,
                )
        except ManifestTargetMismatch as exc:
            raise SystemExit(str(exc)) from exc
        _refuse_self_copy(settings, store)
        source = Path(settings.upload_root)
        if not args.dry_run:
            save_manifest(manifest_path, manifest)
        try:
            summary = apply_entries(
                store,
                manifest,
                dry_run=args.dry_run,
                force=args.force,
                content_type_for=lambda entry: media.get(entry.key),
                host=HOST,
                source_root=source,
            )
        except TargetNotEmpty as exc:
            raise SystemExit(str(exc)) from exc
        _report(manifest, "dry run" if args.dry_run else "apply")
        print(
            f"this run: copied {summary['copied']}, remaining {summary['remaining']}, "
            f"pending {summary['pending']}, foreign {summary['foreign']}"
        )
        print(f"manifest: {manifest_path}")
        if args.dry_run:
            print(f"would copy {summary['planned']} object(s)")
            if summary["foreign"]:
                print(
                    f"warning: target prefix has {summary['foreign']} foreign object(s); "
                    "--apply will require --force"
                )
        blocked = any(entry.status in _BLOCKING_STATUSES for entry in manifest.entries)
        return 1 if summary["failed"] or blocked else 0
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate career's legacy uploads into the configured object store."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="plan and report only")
    action.add_argument("--apply", action="store_true", help="copy into the target store")
    action.add_argument("--verify", action="store_true", help="re-read the target and compare")
    action.add_argument(
        "--backfill-db",
        action="store_true",
        help="write object keys back to documents/export jobs (after --verify)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="manifest path (default: <data_dir>/migrations/object-storage-manifest.json)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow a non-empty target prefix or replace a corrupt manifest",
    )
    parser.add_argument(
        "--rebind",
        action="store_true",
        help="adopt the current target; resets transferred entries to pending",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.dry_run or args.apply or args.verify or args.backfill_db):
        args.dry_run = True
    from app.core.config import settings

    return asyncio.run(run_async(args, settings))


if __name__ == "__main__":
    sys.exit(main())
