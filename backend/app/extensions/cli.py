"""Extension-source CLI (plan 32 Phase 3): the admin/CI surface over the
same lifecycle service the settings UI rides.

Usage (from ``backend/``)::

    uv run python -m app.extensions.cli source add <descriptor.json>
    uv run python -m app.extensions.cli source list
    uv run python -m app.extensions.cli source sync <origin-or-id>
    uv run python -m app.extensions.cli source preview <origin-or-id> <extension-id>
    uv run python -m app.extensions.cli source install <origin> <extension-id> \
        --consent-echo '<preview JSON echo>'
    uv run python -m app.extensions.cli source pin <extension-id> \
        --consent-echo '<preview JSON echo>'
    uv run python -m app.extensions.cli source remove <origin-or-id>
    uv run python -m app.extensions.cli source validate <path-or-url> [--ref strategy=value]
    uv run python -m app.extensions.cli desired-state get
    uv run python -m app.extensions.cli desired-state put <document.json>
    uv run python -m app.extensions.cli reconcile

``source validate`` is the authoring helper: it validates the descriptor
against the vendored schema, then (for local paths) fetches, discovers,
schema-validates and host-profile-checks every manifest it finds — the
same pipeline an install runs, read-only. Exits non-zero on any typed
failure; secrets are never accepted on the command line (send them via
the admin API's sealed payload or the settings UI).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.extensions import lifecycle
from app.extensions.lifecycle import LifecycleError


def _print(data) -> None:
    print(json.dumps(data, indent=2, default=str))


def _consent_echo(raw: str) -> dict:
    """A host-derived echo as inline JSON or ``@path`` — never a boolean.

    Capture it from ``source preview`` (or the admin preview endpoints);
    the install/apply call re-derives the values and refuses drift.
    """
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text(encoding="utf-8")
    try:
        echo = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LifecycleError("invalid", f"--consent-echo is not JSON: {exc}") from exc
    if not isinstance(echo, dict):
        raise LifecycleError("invalid", "--consent-echo must be a JSON object")
    return echo


async def _resolve_source(db, ref: str):
    from sqlalchemy import select

    from app.models.extension_model import ExtensionSource

    query = select(ExtensionSource)
    try:
        row = (
            (await db.execute(query.where(ExtensionSource.id == uuid.UUID(ref)))).scalars().first()
        )
    except ValueError:
        row = None
    if row is None:
        row = (await db.execute(query.where(ExtensionSource.origin == ref))).scalars().first()
    if row is None:
        raise LifecycleError("not-found", f"no source matches {ref!r}")
    return row


async def _cmd_source(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        if args.action == "add":
            doc = json.loads(Path(args.descriptor).read_text(encoding="utf-8"))
            _print(await lifecycle.add_source(db, doc))
            return 0
        if args.action == "list":
            _print(await lifecycle.list_sources(db))
            return 0
        if args.action == "sync":
            source = await _resolve_source(db, args.source)
            report = await lifecycle.sync_source(db, source.id)
            _print(report)
            return 0 if report.get("ok") else 1
        if args.action == "preview":
            source = await _resolve_source(db, args.source)
            _print(await lifecycle.preview_install(db, source.id, args.extension_id))
            return 0
        if args.action == "install":
            source = await _resolve_source(db, args.source)
            _print(
                await lifecycle.install_extension(
                    db,
                    source.id,
                    args.extension_id,
                    consent=_consent_echo(args.consent_echo),
                )
            )
            return 0
        if args.action == "pin":
            from sqlalchemy import select

            from app.models.extension_model import ExtensionInstall

            install = (
                (
                    await db.execute(
                        select(ExtensionInstall).where(
                            ExtensionInstall.extension_id == args.extension_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if install is None:
                raise LifecycleError("not-found", f"no install for {args.extension_id!r}")
            _print(
                await lifecycle.apply_update(
                    db, install.id, consent=_consent_echo(args.consent_echo)
                )
            )
            return 0
        if args.action == "remove":
            source = await _resolve_source(db, args.source)
            _print(await lifecycle.remove_source(db, source.id))
            return 0
        if args.action == "validate":
            return await _validate(args)
    raise LifecycleError("invalid", f"unknown source action: {args.action}")


async def _validate(args: argparse.Namespace) -> int:
    """Validate a descriptor (and, for local paths, everything it offers)."""
    doc: dict = {
        "ref": _parse_ref(args.ref) if args.ref else {"strategy": "branch", "value": "main"}
    }
    target = args.target_or_url
    if target.startswith("https://"):
        doc = {"url": target, **doc}
        parsed = lifecycle.validate_source_descriptor(doc)
        print(f"ok: https descriptor valid ({parsed.origin})")
        return 0
    path = Path(target).resolve()
    doc = {"local": {"path": str(path)}, **doc}
    lifecycle.validate_source_descriptor(doc)
    print(f"ok: local descriptor valid ({path})")

    import tempfile

    with tempfile.TemporaryDirectory(prefix="ca-ext-validate-") as tmp:
        tree = Path(tmp) / "tree"
        transport = lifecycle.GitTransport()
        resolved = await transport.resolve(str(path), doc["ref"])
        await transport.fetch(str(path), resolved, tree)
        found = lifecycle.discover_manifests(tree, args.subpath or "")
        if not found:
            raise LifecycleError("invalid", "no extension manifests found (root + one level)")
        for entry in found:
            manifest = entry["manifest"]
            tier = None
            if manifest.get("kind") == "connector":
                try:
                    tier = lifecycle.detect_connector_tier(
                        lifecycle._entry_dir(tree, entry["subpath"])
                    )
                except LifecycleError as exc:
                    print(
                        f"  {entry['extensionId']} @ {entry['subpath'] or '.'} — INCOMPATIBLE: "
                        f"{exc.detail}"
                    )
                    continue
            reason = lifecycle.check_host_profile(manifest, tier)
            digest = lifecycle.digest_tree(lifecycle._entry_dir(tree, entry["subpath"]))
            state = "compatible" if reason is None else f"INCOMPATIBLE: {reason}"
            print(f"  {entry['extensionId']} @ {entry['subpath'] or '.'} — {digest[:12]}… {state}")
    return 0


def _parse_ref(raw: str) -> dict:
    strategy, _, value = raw.partition("=")
    ref = {"strategy": strategy}
    if value:
        ref["value"] = value
    return ref


async def _cmd_desired_state(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        if args.action == "get":
            _print(await lifecycle.get_desired_state(db))
            return 0
        if args.action == "put":
            doc = json.loads(Path(args.document).read_text(encoding="utf-8"))
            _print(await lifecycle.put_desired_state(db, doc))
            return 0
    raise LifecycleError("invalid", f"unknown desired-state action: {args.action}")


async def _cmd_reconcile(_: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        _print(await lifecycle.reconcile(db))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.extensions.cli")
    sub = parser.add_subparsers(dest="group", required=True)

    source = sub.add_parser(
        "source", help="extension sources: add/list/sync/install/pin/remove/validate"
    )
    source_sub = source.add_subparsers(dest="action", required=True)
    add = source_sub.add_parser("add", help="add a source from a descriptor JSON file")
    add.add_argument("descriptor")
    source_sub.add_parser("list", help="list sources + candidates + installs")
    sync = source_sub.add_parser("sync", help="fetch + discover + update-check")
    sync.add_argument("source", help="origin URL/path or source id")
    preview = source_sub.add_parser(
        "preview", help="host-derived install preview + consent echo (no mutation)"
    )
    preview.add_argument("source")
    preview.add_argument("extension_id")
    install = source_sub.add_parser("install", help="consent-install an offered extension")
    install.add_argument("source")
    install.add_argument("extension_id")
    install.add_argument(
        "--consent-echo",
        required=True,
        help="the exact echo from `source preview` (JSON object or @path)",
    )
    pin = source_sub.add_parser("pin", help="apply a recorded update (explicit re-consent)")
    pin.add_argument("extension_id")
    pin.add_argument(
        "--consent-echo",
        required=True,
        help="the exact echo from the update preview (JSON object or @path)",
    )
    remove = source_sub.add_parser("remove", help="remove a source (installs park)")
    remove.add_argument("source")
    validate = source_sub.add_parser(
        "validate", help="validate a descriptor (and a local repo's manifests)"
    )
    validate.add_argument("target_or_url")
    validate.add_argument(
        "--ref", help="ref spec, e.g. release-tag | tag-pattern=v* | branch=main | commit-pin=<sha>"
    )
    validate.add_argument("--subpath", default="")
    source.set_defaults(func=_cmd_source)

    desired = sub.add_parser("desired-state", help="GitOps desired state (admin-owned)")
    desired_sub = desired.add_subparsers(dest="action", required=True)
    desired_sub.add_parser("get")
    put = desired_sub.add_parser("put")
    put.add_argument("document")
    desired.set_defaults(func=_cmd_desired_state)

    reconcile = sub.add_parser("reconcile", help="run the GitOps reconcile once")
    reconcile.set_defaults(func=_cmd_reconcile)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except LifecycleError as exc:
        print(f"{exc.code}: {exc.detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
