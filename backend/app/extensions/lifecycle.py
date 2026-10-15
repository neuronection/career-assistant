"""Extension sources, consent, pinning and GitOps reconcile (plan 32
Phase 3 / ADR-0040 D13+D15+D22) — the app-side import layer.

The pipeline (one shape, every host): resolve → shallow fetch → discover
manifests → schema-validate against the vendored envelope → host-profile
compatibility → per-extension consent (capabilities, tier, provenance and
digest in user language — the T3 perimeter disclosure rendered VERBATIM
from the vendored charter) → pinned install. Installed content is DATA:
content-addressed under ``data_dir/extensions/<id>/<digest>/``, never
importlib'd into the process (D2's gate point); the runnable surface is
the existing ``mcp`` connector — the install mints a disabled job source
whose stdio command spawns ``server.py`` FROM THE CLONED CONTENT (D13's
managed spawn, the Phase-2 handoff).

Supply-chain law implemented here, fail-closed everywhere:

* consent is REQUIRED before any install of imported code/data (D7) and
  persists per install (who/when/what-digest — verifiable);
* no auto-apply path exists at all (D22): every T3 code change is an
  explicit re-consent/apply; T0 data auto-applies only on a byte-identical
  manifest (capabilities + configSchema unchanged);
* capability growth or tier change on update re-consents (D15);
* digest drift on a pinned ref is a LOUD failure — never a silent refetch;
* GitOps reconcile installs and moves pins only, never auto-enables,
  never deletes data (deletion is structurally inexpressible in the
  desired-state schema); manual installs are never re-pinned or removed
  (drift reported as status); a failed fetch leaves pins untouched and
  marks the source failing;
* the dev/test ``local`` file-path source kind is gated OFF in production
  boots and confined to allowlisted parent roots (path discipline);
* private-repo credentials are secret-slot references resolved host-side
  into the git subprocess environment (GIT_CONFIG_* — never argv, never
  logs); an inline token is structurally invalid at the schema seam.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.extensions import contract
from app.models.extension_model import ExtensionInstall, ExtensionSource

logger = logging.getLogger(__name__)

DESIRED_STATE_KEY = "extensions.desired_state"
ENTRY_FILE = "server.py"
EXTENSIONS_SUBDIR = "extensions"
MANIFEST_FILE = "manifest.json"
MANIFEST_MAX_BYTES = 524_288
TREE_MAX_FILES = 4096
TREE_MAX_BYTES = 128 * 1024 * 1024

# Host profile (career, ADR-0040 D8): connector-kind imports only today
# (mini-app surfaces arrive with plan 32 Phase 4; bridge is server-class).
# Imported connectors run T3 (external MCP process) — the host grants no
# `net` at this tier (the script's own sockets are consent-disclosed, D22),
# so the honored capability set for imports is exactly what the bundled
# `mcp` connector declares.
IMPORTED_KINDS = ("connector",)
IMPORTED_HONORED_CAPABILITIES = frozenset({"sync", "secrets"})
TIER_FOR_IMPORT = "T3"

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class LifecycleError(Exception):
    """One typed import-layer failure (charter error codes, capped detail)."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail[:500]
        super().__init__(f"{code}: {self.detail}")


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------- contracts


def _contracts_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "contracts"
    return Path(__file__).resolve().parents[3] / "contracts"


def _load_json(name: str) -> dict:
    try:
        return json.loads((_contracts_dir() / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(
            "not-ready", f"vendored contract {name} unavailable: {exc} — import fails closed"
        ) from exc


_sources_schema_cache: dict | None = None
_charter_cache: dict | None = None


def _sources_schema() -> dict:
    global _sources_schema_cache
    if _sources_schema_cache is None:
        _sources_schema_cache = _load_json("extension-sources.schema.json")
    return _sources_schema_cache


def _charter() -> dict:
    global _charter_cache
    if _charter_cache is None:
        _charter_cache = _load_json("extension-charter.json")
    return _charter_cache


def t3_perimeter_disclosure() -> str:
    """The T3 perimeter copy, VERBATIM from the vendored charter (D22)."""
    return str(_charter()["consent"]["t3PerimeterDisclosure"])


# ------------------------------------------------------- descriptor shape


@dataclass
class SourceDescriptor:
    """One validated source descriptor (production https or dev/test local)."""

    kind: str  # "git" | "local"
    origin: str  # https URL or absolute local path
    document: dict  # the validated descriptor verbatim
    subpath: str = ""

    @property
    def ref_strategy(self) -> dict:
        return self.document.get("ref") or {}

    @property
    def credential_slots(self) -> list[dict]:
        return list(self.document.get("credentials") or [])


def local_sources_available() -> bool:
    """The local dev/test kind requires a non-production boot AND at least
    one allowlisted root (fail-closed both ways)."""
    from app.core.config import settings

    return settings.is_dev and bool(settings.extension_local_source_roots)


def _check_local_root(path_str: str) -> Path:
    """net_guard-style path discipline for local sources: the repo root
    must RESOLVE under an allowlisted parent (symlinks followed, traversal
    collapsed — the comparison happens on resolved paths, never on input
    text)."""
    from app.core.config import settings

    if not settings.is_dev:
        raise LifecycleError(
            "path-denied",
            "local extension sources are gated off in production boots "
            "(CAREER_APP_ENV=production) — fail-closed",
        )
    roots = [Path(root).expanduser().resolve() for root in settings.extension_local_source_roots]
    if not roots:
        raise LifecycleError(
            "path-denied",
            "local extension sources need an allowlisted root "
            "(CAREER_EXTENSION_LOCAL_SOURCE_ROOTS) — none configured, fail-closed",
        )
    resolved = Path(path_str).expanduser().resolve()
    for root in roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if not resolved.exists():
            raise LifecycleError("not-found", f"local source path does not exist: {resolved}")
        return resolved
    raise LifecycleError(
        "path-denied",
        f"local source {resolved} is outside every allowlisted root — refusing",
    )


def validate_source_descriptor(doc: dict) -> SourceDescriptor:
    """Validate a source descriptor against the vendored schema.

    Production descriptors validate against the ROOT (https-only by
    structure); a ``local`` document is routed to the distinct
    ``$defs.localSourceDescriptor`` variant and additionally passes the
    production boot gate + root allowlist above. Unknown shapes fail
    closed — there is no third kind.
    """
    schema = _sources_schema()
    if isinstance(doc, dict) and "local" in doc:
        if "url" in doc:
            raise LifecycleError("invalid", "a source is either https or local — never both")
        target = schema["$defs"]["localSourceDescriptor"]
        err = contract.validate(target, doc, schema)
        if err is not None:
            raise LifecycleError("invalid", f"local source descriptor invalid: {err}")
        path = _check_local_root(str((doc.get("local") or {}).get("path") or ""))
        return SourceDescriptor(
            kind="local", origin=str(path), document=doc, subpath=str(doc.get("subpath") or "")
        )
    err = contract.validate(schema, doc, schema)
    if err is not None:
        raise LifecycleError("invalid", f"source descriptor invalid: {err}")
    return SourceDescriptor(
        kind="git",
        origin=str(doc.get("url") or ""),
        document=doc,
        subpath=str(doc.get("subpath") or ""),
    )


# ------------------------------------------------------------ git transport


@dataclass
class ResolvedRef:
    ref: str  # the pin identity: tag NAME for tag strategies, the commit SHA otherwise
    sha: str  # commit sha
    fetch_ref: str = ""  # what git can fetch (tag/branch name or sha); defaults to ref


class GitTransport:
    """git subprocess transport (resolve + shallow fetch). Overridable as a
    seam for tests — the real https path never opens sockets itself beyond
    the git CLI, and credentials ride the GIT_CONFIG_* environment (never
    argv, so they never appear in process listings or logs)."""

    async def _git(
        self, args: list[str], *, cwd: Path | None = None, env: dict | None = None
    ) -> str:
        from app.core.config import settings

        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=settings.extension_fetch_timeout_seconds
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise LifecycleError("unreachable", f"git {' '.join(args[:2])} timed out") from None
        if proc.returncode != 0:
            detail = (err or b"").decode("utf-8", "replace").strip().splitlines()
            raise LifecycleError(
                "unreachable", f"git failed: {detail[-1] if detail else 'unknown'}"
            )
        return out.decode("utf-8", "replace")

    def _env(self, token: str | None) -> dict | None:
        """Private-repo credential: git config via environment (git ≥2.31)
        — the token never crosses argv, and error output is scrubbed by the
        caller (only the last stderr line surfaces)."""
        import os

        if not token:
            return None
        env = dict(os.environ)
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {token}",
            }
        )
        return env

    async def resolve(self, origin: str, ref: dict, *, token: str | None = None) -> ResolvedRef:
        strategy = ref.get("strategy")
        value = str(ref.get("value") or "")
        env = self._env(token)
        if strategy == "commit-pin":
            return ResolvedRef(ref=value, sha=value, fetch_ref=value)
        listing = await self._git(["ls-remote", origin], env=env)
        refs: dict[str, str] = {}
        for line in listing.splitlines():
            sha, _, name = line.partition("\t")
            if name.endswith("^{}"):
                continue
            refs[name.strip()] = sha.strip()
        if strategy == "branch":
            head = refs.get(f"refs/heads/{value}") or ""
            if not head:
                raise LifecycleError("not-found", f"branch {value!r} not found on {origin}")
            return ResolvedRef(ref=head, sha=head, fetch_ref=value)
        tags = {
            name.removeprefix("refs/tags/"): sha
            for name, sha in refs.items()
            if name.startswith("refs/tags/")
        }
        if strategy == "tag-pattern":
            tags = {tag: sha for tag, sha in tags.items() if fnmatch.fnmatchcase(tag, value)}
        ref_ = _latest_tag(tags)
        if ref_ is None:
            raise LifecycleError(
                "not-found", f"no release tag matching {strategy} {value!r} on {origin}"
            )
        return ResolvedRef(ref=ref_, sha=tags[ref_], fetch_ref=ref_)

    async def fetch(
        self, origin: str, resolved: ResolvedRef, dest: Path, *, token: str | None = None
    ) -> None:
        env = self._env(token)
        fetch_ref = resolved.fetch_ref or resolved.ref
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", fetch_ref):
            dest.mkdir(parents=True, exist_ok=True)
            await self._git(["init", "--quiet"], cwd=dest)
            await self._git(["remote", "add", "origin", origin], cwd=dest)
            await self._git(
                ["fetch", "--quiet", "--depth", "1", "origin", fetch_ref], cwd=dest, env=env
            )
            await self._git(["checkout", "--quiet", "FETCH_HEAD"], cwd=dest)
            return
        await self._git(
            ["clone", "--quiet", "--depth", "1", "--branch", fetch_ref, origin, str(dest)],
            env=env,
        )


def _latest_tag(tags: dict[str, str]) -> str | None:
    """Highest semver tag; name-descending fallback for non-semver tags."""
    if not tags:
        return None

    def key(tag: str):
        m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(.*)", tag)
        if not m:
            return (0, (0, 0, 0), tag)
        return (1, tuple(int(part) for part in m.group(1, 2, 3)), tag)

    return max(tags, key=key)


_transport: GitTransport | None = None


def git_transport() -> GitTransport:
    global _transport
    if _transport is None:
        _transport = GitTransport()
    return _transport


def set_git_transport(transport: GitTransport | None) -> None:
    """Test seam: inject a fake transport (no network, deterministic)."""
    global _transport
    _transport = transport


# ---------------------------------------------------------------- content


def _content_root(data_dir: Path | None = None) -> Path:
    from app.core.config import settings

    return (data_dir or settings.data_dir) / EXTENSIONS_SUBDIR


def digest_tree(root: Path) -> str:
    """Deterministic sha256 over a content tree: regular files only
    (symlinks and specials are SKIPPED — they never contribute and never
    execute), sorted by relative path, path+NUL+size+NUL+bytes per file.
    Adversarial caps: file count and total bytes (typed error beyond)."""
    digest = hashlib.sha256()
    files: list[tuple[str, Path]] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        files.append((path.relative_to(root).as_posix(), path))
        total += path.stat().st_size
    if len(files) > TREE_MAX_FILES or total > TREE_MAX_BYTES:
        raise LifecycleError(
            "invalid",
            f"extension content exceeds caps ({len(files)} files / {total} bytes)",
        )
    for rel, path in files:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode())
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _copy_tree(src: Path, dest: Path) -> None:
    """Materialize the extension content — regular files only; symlinks
    never cross (the copied tree is exactly what the digest describes and
    what a spawn can execute)."""
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        if ".git" in path.relative_to(src).parts:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        target = dest / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def discover_manifests(tree: Path, subpath: str) -> list[dict]:
    """Manifest discovery: the subpath dir (repo root when absent) plus
    ONE level of child dirs — each manifest.json is byte-capped, parsed
    and schema-validated against the vendored imported envelope."""
    base = (tree / subpath).resolve() if subpath else tree.resolve()
    try:
        base.relative_to(tree.resolve())
    except ValueError as exc:
        raise LifecycleError("path-denied", "subpath escapes the cloned tree") from exc
    schema = _load_json("extension-manifest.schema.json")
    found: list[dict] = []
    candidates = [base, *(child for child in sorted(base.iterdir()) if child.is_dir())]
    for candidate in candidates:
        manifest_path = candidate / MANIFEST_FILE
        if not manifest_path.is_file():
            continue
        raw = manifest_path.read_bytes()
        if len(raw) > MANIFEST_MAX_BYTES:
            raise LifecycleError("invalid", f"{manifest_path.name} exceeds the byte cap")
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LifecycleError("invalid", f"manifest is not JSON: {exc}") from exc
        err = contract.validate_manifest(manifest, schema)
        if err is not None:
            raise LifecycleError("invalid", f"manifest invalid: {err}")
        found.append(
            {
                "extensionId": manifest.get("id"),
                "subpath": candidate.relative_to(tree).as_posix(),
                "manifest": manifest,
            }
        )
    return found


def check_host_profile(manifest: dict) -> str | None:
    """Host-profile compatibility (data, never code): kind hosted? tier
    runnable? apiVersion current? capabilities honored? Returns the
    self-disable reason, or None when compatible."""
    kind = manifest.get("kind")
    if kind not in IMPORTED_KINDS:
        return (
            f"kind {kind!r} is not hosted for import (career hosts connector-kind "
            "imports; mini-app surfaces arrive with plan 32 Phase 4, bridge is server-class)"
        )
    api_version = manifest.get("apiVersion")
    if api_version != contract.ENVELOPE_API_VERSION:
        return f"apiVersion {api_version!r} is not {contract.ENVELOPE_API_VERSION}"
    kind_version = manifest.get("kindVersion")
    if not isinstance(kind_version, int) or kind_version > contract.CONNECTOR_KIND_VERSION:
        return (
            f"requires host connector refinement >= {kind_version} "
            f"(host has {contract.CONNECTOR_KIND_VERSION}) — self-disable"
        )
    caps = set(manifest.get("capabilities") or [])
    unhonored = sorted(caps - IMPORTED_HONORED_CAPABILITIES)
    if unhonored:
        return f"capabilities not honored by this host: {', '.join(unhonored)}"
    return None


def _entry_dir(tree: Path, subpath: str) -> Path:
    return (tree / subpath).resolve() if subpath else tree.resolve()


def consent_payload(manifest: dict, digest: str, *, subpath: str = "") -> dict:
    """What a consent surface MUST show (charter consent law): capabilities,
    tier + import class, provenance verbatim from the manifest, the pinned
    digest, and the T3 perimeter disclosure VERBATIM."""
    return {
        "extensionId": manifest.get("id"),
        "version": manifest.get("version"),
        "subpath": subpath,
        "digest": digest,
        "tier": TIER_FOR_IMPORT,
        "importClass": "imported",
        "capabilities": list(manifest.get("capabilities") or []),
        "provenance": {
            "author": manifest.get("author"),
            "license": manifest.get("license"),
            "repository": manifest.get("repository"),
            "description": manifest.get("description"),
        },
        "disclosureKey": "t3PerimeterDisclosure",
        "disclosure": t3_perimeter_disclosure(),
    }


def _manifest_digest_fields(manifest: dict) -> dict:
    """The byte-identical-manifest test fields (D22): capabilities +
    configSchema — unchanged is the ONLY condition under which T0 data
    diffs may auto-apply."""
    return {
        "capabilities": list(manifest.get("capabilities") or []),
        "configSchema": manifest.get("configSchema"),
    }


def manifest_diff(old: dict, new: dict) -> dict:
    old_caps = set(old.get("capabilities") or [])
    new_caps = set(new.get("capabilities") or [])
    diff: dict[str, Any] = {
        "version": {"from": old.get("version"), "to": new.get("version")},
        "capabilitiesAdded": sorted(new_caps - old_caps),
        "configSchemaChanged": _manifest_digest_fields(old) != _manifest_digest_fields(new),
    }
    return diff


def update_requires_reconsent(diff: dict, tier: str) -> bool:
    """D15/D22: capability growth or tier change re-consents; and with no
    signing service there is no auto-apply path at all for CODE — only a
    T0 install with a byte-identical manifest may auto-apply."""
    if diff.get("capabilitiesAdded") or diff.get("configSchemaChanged"):
        return True
    return tier != "T0"


# ------------------------------------------------------------ db service


def _resolve_source_secrets(source: ExtensionSource) -> str | None:
    """The first declared credential slot's sealed value, decrypted
    host-side (D22: slot references resolve here — values never live in
    the descriptor, never in logs)."""
    from app.core.encryption import decrypt_secret

    descriptor = source.descriptor or {}
    creds = descriptor.get("credentials") or []
    if not creds:
        return None
    sealed = (source.secrets or {}).get(str(creds[0].get("slot") or ""))
    value = decrypt_secret(sealed) if isinstance(sealed, str) else None
    return value or None


def _source_view(source: ExtensionSource, installs: list[ExtensionInstall]) -> dict:
    descriptor = source.descriptor or {}
    candidates = []
    for candidate in source.candidates or []:
        manifest = candidate.get("manifest") or {}
        entry = dict(candidate)
        # The consent surface's data: what the UI shows BEFORE install —
        # capabilities, tier, provenance verbatim, digest and the T3
        # perimeter disclosure VERBATIM (charter consent law).
        entry["consent"] = consent_payload(
            manifest,
            str(candidate.get("digest") or ""),
            subpath=str(candidate.get("subpath") or ""),
        )
        candidates.append(entry)
    return {
        "id": str(source.id),
        "kind": source.kind,
        "origin": source.origin,
        "descriptor": {
            "url": descriptor.get("url"),
            "local": descriptor.get("local"),
            "ref": descriptor.get("ref"),
            "subpath": descriptor.get("subpath"),
            "credentialSlots": [c.get("slot") for c in descriptor.get("credentials") or []],
        },
        "status": source.status,
        "error": source.error,
        "last_checked_at": source.last_checked_at.isoformat() if source.last_checked_at else None,
        "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
        "consecutive_failures": source.consecutive_failures,
        "candidates": candidates,
        "installs": [_install_view(install) for install in installs],
    }


def _install_view(install: ExtensionInstall) -> dict:
    manifest = install.manifest or {}
    return {
        "id": str(install.id),
        "extensionId": install.extension_id,
        "version": install.version,
        "digest": install.digest,
        "pinRef": install.pin_ref,
        "tier": install.tier,
        "originClass": "imported",
        "state": install.state,
        "enabled": install.enabled,
        "managedBy": install.managed_by,
        "parked": install.parked,
        "sourceKey": install.source_key,
        "contentPath": install.content_path,
        "provenance": {
            "author": manifest.get("author"),
            "license": manifest.get("license"),
            "repository": manifest.get("repository"),
            "description": manifest.get("description"),
        },
        "consentedAt": (install.consents or [{}])[-1].get("at") if install.consents else None,
        "update": install.update or {},
        "tombstonedAt": install.tombstoned_at.isoformat() if install.tombstoned_at else None,
    }


async def _installs_for_source(db: AsyncSession, source_id: uuid.UUID) -> list[ExtensionInstall]:
    rows = await db.execute(select(ExtensionInstall).where(ExtensionInstall.source_id == source_id))
    return list(rows.scalars().all())


async def list_sources(db: AsyncSession) -> list[dict]:
    sources = (
        (await db.execute(select(ExtensionSource).order_by(ExtensionSource.created_at)))
        .scalars()
        .all()
    )
    views = []
    for source in sources:
        installs = await _installs_for_source(db, source.id)
        views.append(_source_view(source, installs))
    return views


async def add_source(
    db: AsyncSession,
    descriptor: dict,
    *,
    secrets: dict | None = None,
) -> dict:
    """Add a source (validated against the vendored schema — production
    https root or the gated local variant). No fetch happens here: a
    failed fetch must be a *status*, never a failed add."""
    parsed = validate_source_descriptor(descriptor)
    existing = await db.execute(
        select(ExtensionSource).where(ExtensionSource.origin == parsed.origin)
    )
    if existing.scalars().first() is not None:
        raise LifecycleError("invalid", f"source already exists: {parsed.origin}")
    from app.core.encryption import encrypt_secret

    source = ExtensionSource(
        origin=parsed.origin,
        kind=parsed.kind,
        descriptor=parsed.document,
        secrets={
            slot: encrypt_secret(str(value))
            for slot, value in (secrets or {}).items()
            if value and slot in {c.get("slot") for c in parsed.credential_slots}
        },
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return _source_view(source, [])


async def remove_source(db: AsyncSession, source_id: uuid.UUID) -> dict:
    """Manual source removal: installs PARK (disabled + orphaned), data
    and consent records stay — removal never deletes data."""
    source = await db.get(ExtensionSource, source_id)
    if source is None:
        raise LifecycleError("not-found", "source not found")
    for install in await _installs_for_source(db, source_id):
        await _park(db, install, note="source removed")
        install.source_id = None
    await db.delete(source)
    await db.commit()
    return {"id": str(source_id), "removed": True}


async def _fetch_tree(source: ExtensionSource, dest: Path) -> tuple[ResolvedRef, Path]:
    """resolve + shallow fetch into dest (temp dir). Credentials resolve
    host-side from the sealed slot map."""
    descriptor = source.descriptor or {}
    ref = descriptor.get("ref") or {}
    token = _resolve_source_secrets(source)
    resolved = await git_transport().resolve(source.origin, ref, token=token)
    await git_transport().fetch(source.origin, resolved, dest, token=token)
    return resolved, dest


async def sync_source(
    db: AsyncSession, source_id: uuid.UUID, *, data_dir: Path | None = None
) -> dict:
    """Fetch + discover + validate + compat-check + digest — recording the
    source's candidates and running the update check for its installs.

    A failed fetch leaves every pin untouched and marks the source
    failing (D22); a digest that CHANGED under the same pinned ref is a
    LOUD failure (digest drift), never a silent refetch."""
    import tempfile

    source = await db.get(ExtensionSource, source_id)
    if source is None:
        raise LifecycleError("not-found", "source not found")
    try:
        with tempfile.TemporaryDirectory(prefix="ca-ext-src-") as tmp:
            tree = Path(tmp) / "tree"
            resolved, _ = await _fetch_tree(source, tree)
            candidates = []
            for found in discover_manifests(
                tree, str((source.descriptor or {}).get("subpath") or "")
            ):
                manifest = found["manifest"]
                reason = check_host_profile(manifest)
                sub = found["subpath"]
                entry_dir = _entry_dir(tree, sub)
                digest = digest_tree(entry_dir)
                candidates.append(
                    {
                        "extensionId": found["extensionId"],
                        "subpath": sub,
                        "digest": digest,
                        "ref": resolved.ref,
                        "manifest": manifest,
                        "compatible": reason is None,
                        "reason": reason,
                        "hasEntry": (entry_dir / ENTRY_FILE).is_file(),
                    }
                )
            if not candidates:
                raise LifecycleError(
                    "invalid", "no extension manifests found (root + one level scanned)"
                )
    except LifecycleError as exc:
        source.status = "failing"
        source.consecutive_failures += 1
        source.error = f"{exc.code}: {exc.detail}"
        source.last_checked_at = _utcnow()
        report = {"ok": False, "error": {"code": exc.code, "detail": exc.detail}}
        await _check_installs_after_failed_fetch(db, source)
        await db.commit()
        return report

    source.candidates = candidates
    source.status = "ok"
    source.error = ""
    source.consecutive_failures = 0
    source.last_success_at = _utcnow()
    source.last_checked_at = _utcnow()
    updates = await _check_updates(db, source, candidates)
    await db.commit()
    return {
        "ok": True,
        "resolvedRef": candidates[0].get("ref") if candidates else None,
        "candidates": [
            {k: v for k, v in candidate.items() if k != "manifest"} for candidate in candidates
        ],
        "updates": updates,
    }


async def _check_installs_after_failed_fetch(db: AsyncSession, source: ExtensionSource) -> None:
    """D22: a failed fetch leaves pins untouched — installs keep their
    recorded digest/pin; only status notes the failure."""
    for install in await _installs_for_source(db, source.id):
        note = install.update or {}
        note["lastCheckFailed"] = True
        install.update = note


async def install_extension(
    db: AsyncSession,
    source_id: uuid.UUID,
    extension_id: str,
    *,
    consent: bool,
    actor_id: uuid.UUID | None = None,
    managed_by: str = "manual",
    data_dir: Path | None = None,
) -> dict:
    """Consent-gated install (D7): lands the discovered content under
    ``data_dir/extensions/<id>/<digest>/`` and mints a DISABLED ``mcp``
    job source whose stdio command spawns the cloned ``server.py``
    (managed spawn, D13). Never enables — the explicit enable call is the
    only path to a live instance. A tombstoned install revives (history
    retained, still disabled — never silently re-enabled)."""
    import tempfile

    if not consent:
        raise LifecycleError(
            "invalid", "consent is required before any install of imported code/data (D7)"
        )
    source = await db.get(ExtensionSource, source_id)
    if source is None:
        raise LifecycleError("not-found", "source not found")
    prior = await db.execute(
        select(ExtensionInstall).where(ExtensionInstall.extension_id == extension_id)
    )
    prior_install = prior.scalars().first()
    if prior_install is not None and prior_install.state != "removed":
        raise LifecycleError("invalid", f"extension already installed: {extension_id}")
    with tempfile.TemporaryDirectory(prefix="ca-ext-src-") as tmp:
        tree = Path(tmp) / "tree"
        await _fetch_tree(source, tree)
        candidate = None
        for found in discover_manifests(tree, str((source.descriptor or {}).get("subpath") or "")):
            if found["extensionId"] == extension_id:
                candidate = found
                break
        if candidate is None:
            raise LifecycleError(
                "not-found", f"extension {extension_id!r} not offered by this source"
            )
        manifest = candidate["manifest"]
        reason = check_host_profile(manifest)
        if reason is not None:
            raise LifecycleError("unsupported", reason)
        sub = candidate["subpath"]
        entry_dir = _entry_dir(tree, sub)
        if not (entry_dir / ENTRY_FILE).is_file():
            raise LifecycleError(
                "unsupported",
                f"no runnable entry ({ENTRY_FILE}) beside the manifest — career imports "
                "connectors as T3 MCP servers (the template repo shape)",
            )
        digest = digest_tree(entry_dir)
        install = await _land_install(
            db,
            source=source,
            extension_id=extension_id,
            manifest=manifest,
            subpath=sub,
            digest=digest,
            ref=_pin_ref(source, digest),
            actor_id=actor_id,
            managed_by=managed_by,
            content_src=entry_dir,
            data_dir=data_dir,
            prior_install=prior_install,
        )
    await db.commit()
    return _install_view(install)


def _pin_ref(source: ExtensionSource, digest: str) -> str:
    """The pin record's ref: the descriptor's own pin when it names this
    digest, else the resolved fetch ref recorded during sync."""
    pin = (source.descriptor or {}).get("pin") or {}
    if pin.get("digest") == digest:
        return str(pin.get("ref") or "")
    for candidate in source.candidates or []:
        if candidate.get("digest") == digest:
            return str(candidate.get("ref") or "")
    return ""


async def _land_install(
    db: AsyncSession,
    *,
    source: ExtensionSource,
    extension_id: str,
    manifest: dict,
    subpath: str,
    digest: str,
    ref: str,
    actor_id: uuid.UUID | None,
    managed_by: str,
    content_src: Path,
    data_dir: Path | None,
    prior_install: ExtensionInstall | None = None,
) -> ExtensionInstall:
    """The one place content lands + consent is recorded + the instance is
    minted — shared by install and re-consented apply. A tombstoned
    ``prior_install`` revives in place (history retained, still disabled)."""
    from app.models.posting_model import JobSource

    content_dir = _content_root(data_dir) / extension_id / digest
    if not (content_dir / MANIFEST_FILE).exists():
        _copy_tree(content_src, content_dir)
    command = f'"{sys.executable}" "{content_dir / ENTRY_FILE}"'
    source_key = extension_id
    clash = await db.execute(select(JobSource).where(JobSource.key == source_key))
    existing_row = clash.scalars().first()
    if existing_row is None:
        job_source = JobSource(
            key=source_key,
            connector_key="mcp",
            config={
                "transport": "stdio",
                "command": command,
                "tool": "fetch_postings",
                "timeout_seconds": 30,
            },
            enabled=False,
        )
        db.add(job_source)
        _validate_mcp_config(job_source)
    else:
        if existing_row.connector_key != "mcp":
            raise LifecycleError(
                "invalid", f"a non-imported job source already owns the key {source_key!r}"
            )
        existing_row.config = {**existing_row.config, "command": command}
        existing_row.enabled = False
    payload = consent_payload(manifest, digest, subpath=subpath)
    record = {
        **payload,
        "actor": str(actor_id) if actor_id else None,
        "at": _utcnow().isoformat(),
    }
    if prior_install is not None:
        prior_install.source_id = source.id
        prior_install.version = str(manifest.get("version") or "")
        prior_install.manifest = manifest
        prior_install.pin_ref = ref
        prior_install.digest = digest
        prior_install.content_path = str(content_dir)
        prior_install.state = "installed"
        prior_install.enabled = False
        prior_install.managed_by = managed_by
        prior_install.source_key = source_key
        prior_install.consents = [*(prior_install.consents or []), record]
        prior_install.pin_history = [
            *(prior_install.pin_history or []),
            {"ref": ref, "digest": digest, "at": record["at"]},
        ]
        prior_install.installed_by = actor_id
        prior_install.installed_at = _utcnow()
        prior_install.tombstoned_at = None
        prior_install.parked = False
        prior_install.update = {}
        return prior_install
    install = ExtensionInstall(
        extension_id=extension_id,
        source_id=source.id,
        version=str(manifest.get("version") or ""),
        manifest=manifest,
        pin_ref=ref,
        digest=digest,
        content_path=str(content_dir),
        tier=TIER_FOR_IMPORT,
        state="installed",
        enabled=False,
        managed_by=managed_by,
        source_key=source_key,
        consents=[record],
        pin_history=[{"ref": ref, "digest": digest, "at": record["at"]}],
        installed_by=actor_id,
        installed_at=_utcnow(),
    )
    db.add(install)
    return install


def _validate_mcp_config(job_source) -> None:
    """Fail closed when the T3 tier is admin-disabled: the mcp connector
    must be allowlisted before an instance can be minted."""
    from app.extensions.registry import get_connector

    try:
        connector = get_connector("mcp")
    except Exception as exc:
        raise LifecycleError(
            "not-ready",
            "the mcp connector is not allowlisted (CAREER_CONNECTOR_PLUGINS_ALLOWLIST "
            'must name "mcp") — the T3 script tier is admin-opt-in',
        ) from exc
    connector.validate_config(job_source.config)


# ---------------------------------------------------------- update engine


async def _check_updates(
    db: AsyncSession, source: ExtensionSource, candidates: list[dict]
) -> list[dict]:
    """Update check per install (D15): ref move + digest change + manifest
    diff. Same-digest ref moves apply (content identical, nothing
    consented changes); digest changes are recorded as available updates
    requiring re-consent — NEVER applied here. A changed digest under the
    SAME pinned ref is drift: loud, blocking, never a silent refetch."""
    reports: list[dict] = []
    by_id = {candidate["extensionId"]: candidate for candidate in candidates}
    for install in await _installs_for_source(db, source.id):
        if install.state == "removed":
            continue
        candidate = by_id.get(install.extension_id)
        if candidate is None:
            note = install.update or {}
            note["state"] = "absent-from-source"
            install.update = note
            reports.append({"extensionId": install.extension_id, "state": "absent-from-source"})
            continue
        new_ref, new_digest = candidate["ref"], candidate["digest"]
        if new_digest == install.digest:
            if new_ref and new_ref != install.pin_ref:
                install.pin_history = [
                    *(install.pin_history or []),
                    {"ref": new_ref, "digest": new_digest, "at": _utcnow().isoformat()},
                ]
                install.pin_ref = new_ref
            install.update = {}
            reports.append({"extensionId": install.extension_id, "state": "current"})
            continue
        if new_ref == install.pin_ref:
            # Digest drift on a pinned ref: the SAME named ref now yields
            # different content (tag force-move, history rewrite) — the
            # supply-chain attack signal. LOUD failure, never a silent
            # refetch: pins untouched, source degraded, admin verifies and
            # re-consents explicitly (D22).
            install.update = {
                "state": "digest-drift",
                "ref": install.pin_ref,
                "expectedDigest": install.digest,
                "foundDigest": new_digest,
                "detail": "pinned ref content changed — refusing to refetch; verify the "
                "source and re-consent explicitly",
            }
            source.status = "degraded"
            source.error = f"digest drift on {install.extension_id} at pinned ref {install.pin_ref}"
            reports.append({"extensionId": install.extension_id, "state": "digest-drift"})
            continue
        diff = manifest_diff(install.manifest or {}, candidate["manifest"])
        install.update = {
            "state": "available",
            "ref": new_ref,
            "digest": new_digest,
            "manifestDiff": diff,
            "requiresReconsent": update_requires_reconsent(diff, install.tier),
        }
        reports.append(
            {"extensionId": install.extension_id, "state": "available", "manifestDiff": diff}
        )
    return reports


async def apply_update(
    db: AsyncSession,
    install_id: uuid.UUID,
    *,
    consent: bool,
    actor_id: uuid.UUID | None = None,
    data_dir: Path | None = None,
) -> dict:
    """The ONLY apply path (D22): an explicit re-consent to the recorded
    available update. Lands the new digest, moves the pin, appends the
    consent record, and points the minted instance at the new content."""
    import tempfile

    if not consent:
        raise LifecycleError("invalid", "applying an imported update requires re-consent (D22)")
    install = await db.get(ExtensionInstall, install_id)
    if install is None:
        raise LifecycleError("not-found", "install not found")
    update = install.update or {}
    if update.get("state") != "available":
        raise LifecycleError("invalid", f"no update available (state: {update.get('state')!r})")
    source = await db.get(ExtensionSource, install.source_id) if install.source_id else None
    if source is None:
        raise LifecycleError("not-found", "the source row is gone — re-import instead")
    with tempfile.TemporaryDirectory(prefix="ca-ext-src-") as tmp:
        tree = Path(tmp) / "tree"
        await _fetch_tree(source, tree)
        candidate = None
        for found in discover_manifests(tree, str((source.descriptor or {}).get("subpath") or "")):
            if found["extensionId"] == install.extension_id:
                candidate = found
                break
        if candidate is None:
            raise LifecycleError("not-found", "the update disappeared from the source")
        manifest = candidate["manifest"]
        reason = check_host_profile(manifest)
        if reason is not None:
            raise LifecycleError("unsupported", f"the update is not hostable: {reason}")
        sub = candidate["subpath"]
        entry_dir = _entry_dir(tree, sub)
        if not (entry_dir / ENTRY_FILE).is_file():
            raise LifecycleError(
                "unsupported", f"the update lost its runnable entry ({ENTRY_FILE})"
            )
        digest = digest_tree(entry_dir)
        if digest != update.get("digest"):
            raise LifecycleError(
                "invalid",
                "the source moved again mid-apply — re-run the check; pins untouched",
            )
        content_dir = _content_root(data_dir) / install.extension_id / digest
        if not (content_dir / MANIFEST_FILE).exists():
            _copy_tree(entry_dir, content_dir)
        payload = consent_payload(manifest, digest, subpath=sub)
        record = {
            **payload,
            "actor": str(actor_id) if actor_id else None,
            "at": _utcnow().isoformat(),
            "reconsent": True,
        }
        install.consents = [*(install.consents or []), record]
        install.pin_history = [
            *(install.pin_history or []),
            {"ref": str(update.get("ref") or ""), "digest": digest, "at": record["at"]},
        ]
        install.manifest = manifest
        install.version = str(manifest.get("version") or "")
        install.pin_ref = str(update.get("ref") or install.pin_ref)
        install.digest = digest
        install.content_path = str(content_dir)
        install.update = {}
        from app.models.posting_model import JobSource

        row = await db.execute(select(JobSource).where(JobSource.key == install.source_key))
        job_source = row.scalars().first()
        if job_source is not None:
            job_source.config = {
                **job_source.config,
                "command": f'"{sys.executable}" "{content_dir / ENTRY_FILE}"',
            }
    await db.commit()
    return _install_view(install)


# ------------------------------------------------------- instance controls


async def _park(db: AsyncSession, install: ExtensionInstall, *, note: str) -> None:
    """Park: disabled + flagged, data intact, tombstone-able (D22)."""
    from app.models.posting_model import JobSource

    install.enabled = False
    install.parked = True
    if install.state != "removed":
        install.state = "disabled"
    if install.source_key:
        row = await db.execute(select(JobSource).where(JobSource.key == install.source_key))
        job_source = row.scalars().first()
        if job_source is not None:
            job_source.enabled = False
    logger.info("extension parked (%s): %s", note, install.extension_id)


async def set_install_enabled(db: AsyncSession, install_id: uuid.UUID, enabled: bool) -> dict:
    """The ONLY enable path — an explicit admin act (installs, updates and
    reconcile never auto-enable, D22)."""
    from app.models.posting_model import JobSource

    install = await db.get(ExtensionInstall, install_id)
    if install is None:
        raise LifecycleError("not-found", "install not found")
    if install.state == "removed":
        raise LifecycleError(
            "invalid", "a tombstoned extension is never re-enabled on its own — re-import"
        )
    if enabled:
        install.state = "installed" if install.state == "disabled" else install.state
        install.parked = False
    row = await db.execute(select(JobSource).where(JobSource.key == install.source_key))
    job_source = row.scalars().first()
    if job_source is None:
        raise LifecycleError("not-found", "the minted job source is gone — re-import")
    job_source.enabled = enabled
    install.enabled = enabled
    await db.commit()
    return _install_view(install)


async def park_install(db: AsyncSession, install_id: uuid.UUID) -> dict:
    install = await db.get(ExtensionInstall, install_id)
    if install is None:
        raise LifecycleError("not-found", "install not found")
    await _park(db, install, note="admin park")
    await db.commit()
    return _install_view(install)


async def tombstone_install(db: AsyncSession, install_id: uuid.UUID) -> dict:
    """Tombstone (lifecycle `removed`): the minted instance is disabled,
    the install row + content + consent records are retained — a re-import
    at the same digest surfaces the history, never a silent re-enable."""
    install = await db.get(ExtensionInstall, install_id)
    if install is None:
        raise LifecycleError("not-found", "install not found")
    await _park(db, install, note="tombstone")
    install.state = "removed"
    install.tombstoned_at = _utcnow()
    await db.commit()
    return _install_view(install)


# ------------------------------------------------------------ GitOps


async def get_desired_state(db: AsyncSession) -> dict:
    from app.models.settings_model import AppSetting

    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == DESIRED_STATE_KEY)))
        .scalars()
        .first()
    )
    return row.value if row is not None else {}


async def put_desired_state(db: AsyncSession, document: dict) -> dict:
    """Admin-owned desired state (the model NEVER authors this —
    ADR-0011 §7). Validated against the vendored desiredStateDocument
    schema; deletion is structurally inexpressible there."""
    schema = _sources_schema()
    target = schema["$defs"]["desiredStateDocument"]
    err = contract.validate(target, document, schema)
    if err is not None:
        raise LifecycleError("invalid", f"desired-state document invalid: {err}")
    from app.models.settings_model import AppSetting

    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == DESIRED_STATE_KEY)))
        .scalars()
        .first()
    )
    if row is None:
        db.add(
            AppSetting(
                key=DESIRED_STATE_KEY,
                value=document,
                description="GitOps desired state for imported extensions (admin-authored)",
            )
        )
    else:
        row.value = document
    await db.commit()
    return document


async def reconcile(db: AsyncSession, *, data_dir: Path | None = None) -> dict:
    """GitOps reconcile (D13/D22) — installs and moves pins ONLY for the
    extensions the list names; never auto-enables; never deletes data.
    Manual installs are never re-pinned or removed (drift is reported as
    status). Failed fetches leave pins untouched and mark the source
    failing. Removal from the list parks gitops-managed installs disabled
    + tombstone-able. New imports still require a prior consent record at
    the exact digest — consent is the gate; the list is only a pin-mover.
    """
    report: dict[str, list] = {
        "installed": [],
        "pinsMoved": [],
        "needsConsent": [],
        "updatesAvailable": [],
        "drift": [],
        "parked": [],
        "failures": [],
        "ignoredEnableIntent": [],
    }
    desired = await get_desired_state(db)
    entries = desired.get("extensions") or []
    if not desired:
        return report
    named_sources = {str(entry.get("url") or ""): entry for entry in desired.get("sources") or []}
    installs = (await db.execute(select(ExtensionInstall))).scalars().all()
    by_extension = {install.extension_id: install for install in installs}

    for entry in entries:
        extension_id = str(entry.get("id") or "")
        pin = entry.get("pin") or {}
        source_url = str(entry.get("sourceUrl") or "")
        if entry.get("enabled"):
            report["ignoredEnableIntent"].append(
                {"extensionId": extension_id, "reason": "reconcile never auto-enables (D22)"}
            )
        source = (
            (await db.execute(select(ExtensionSource).where(ExtensionSource.origin == source_url)))
            .scalars()
            .first()
        )
        if source is None:
            descriptor = named_sources.get(source_url)
            if descriptor is None:
                report["drift"].append(
                    {
                        "extensionId": extension_id,
                        "reason": f"desired source not declared: {source_url}",
                    }
                )
                continue
            try:
                view = await add_source(db, dict(descriptor))
            except LifecycleError as exc:
                report["failures"].append({"extensionId": extension_id, "error": exc.detail})
                continue
            source = await db.get(ExtensionSource, uuid.UUID(view["id"]))
        assert source is not None
        install = by_extension.get(extension_id)
        if install is None:
            await _reconcile_missing_install(
                db, source, extension_id, pin, report, data_dir=data_dir
            )
            continue
        if install.managed_by == "manual":
            report["drift"].append(
                {
                    "extensionId": extension_id,
                    "reason": "manually installed — never re-pinned or removed by reconcile (D22)",
                }
            )
            continue
        await _reconcile_pin(db, source, install, pin, report)

    named = {str(entry.get("id") or "") for entry in entries}
    for install in installs:
        if (
            install.managed_by == "gitops"
            and install.extension_id not in named
            and not install.parked
        ):
            await _park(db, install, note="absent from desired state")
            report["parked"].append({"extensionId": install.extension_id})
    await db.commit()
    return report


async def _reconcile_missing_install(
    db: AsyncSession,
    source: ExtensionSource,
    extension_id: str,
    pin: dict,
    report: dict,
    *,
    data_dir: Path | None,
) -> None:
    """A desired extension with no install: fetch + validate. Consent is
    the gate — without a consent record at this exact digest (a tombstoned
    or previously-removed install carries one) we record the candidate and
    report needs-consent; we never install unconsented code."""
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="ca-ext-gitops-") as tmp:
            tree = Path(tmp) / "tree"
            await _fetch_tree(source, tree)
            found = next(
                (
                    item
                    for item in discover_manifests(
                        tree, str((source.descriptor or {}).get("subpath") or "")
                    )
                    if item["extensionId"] == extension_id
                ),
                None,
            )
            if found is None:
                raise LifecycleError("not-found", f"{extension_id!r} not offered by the source")
            manifest = found["manifest"]
            reason = check_host_profile(manifest)
            if reason is not None:
                raise LifecycleError("unsupported", reason)
            digest = digest_tree(_entry_dir(tree, found["subpath"]))
    except LifecycleError as exc:
        source.status = "failing"
        source.consecutive_failures += 1
        source.error = f"{exc.code}: {exc.detail}"
        report["failures"].append({"extensionId": extension_id, "error": exc.detail})
        return
    if pin.get("digest") and pin["digest"] != digest:
        report["drift"].append(
            {
                "extensionId": extension_id,
                "reason": (
                    f"desired pin digest {pin['digest'][:12]}… != source digest {digest[:12]}…"
                ),
            }
        )
        return
    prior = await db.execute(
        select(ExtensionInstall).where(ExtensionInstall.extension_id == extension_id)
    )
    prior_install = prior.scalars().first()
    consented_digests = (
        {(record or {}).get("digest") for record in (prior_install.consents or [])}
        if prior_install is not None
        else set()
    )
    if digest not in consented_digests:
        report["needsConsent"].append(
            {
                "extensionId": extension_id,
                "digest": digest,
                "reason": "consent is the gate (D13/D7)",
            }
        )
        return
    if prior_install is not None:
        prior_install.state = "installed"
        prior_install.tombstoned_at = None
        prior_install.parked = False
        prior_install.enabled = False
        prior_install.managed_by = "gitops"
        prior_install.source_id = source.id
        report["installed"].append({"extensionId": extension_id, "restored": True})
        return
    report["needsConsent"].append(
        {
            "extensionId": extension_id,
            "digest": digest,
            "reason": "no consent record at this digest",
        }
    )


async def _reconcile_pin(
    db: AsyncSession,
    source: ExtensionSource,
    install: ExtensionInstall,
    pin: dict,
    report: dict,
) -> None:
    """Pin move for a gitops-managed install: exact-digest pin records move
    the recorded ref only when the content is unchanged; any digest change
    on imported code requires re-consent — reported, never applied."""
    desired_digest = str(pin.get("digest") or "")
    desired_ref = str(pin.get("ref") or "")
    if desired_digest == install.digest:
        if desired_ref and desired_ref != install.pin_ref:
            install.pin_ref = desired_ref
            install.pin_history = [
                *(install.pin_history or []),
                {"ref": desired_ref, "digest": install.digest, "at": _utcnow().isoformat()},
            ]
            report["pinsMoved"].append({"extensionId": install.extension_id, "ref": desired_ref})
        return
    prior_consent = {(record or {}).get("digest") for record in (install.consents or [])}
    if desired_digest in prior_consent:
        install.update = {
            "state": "available",
            "ref": desired_ref,
            "digest": desired_digest,
            "requiresReconsent": False,
            "detail": "desired pin matches a previously consented digest",
        }
        report["updatesAvailable"].append(
            {"extensionId": install.extension_id, "digest": desired_digest, "consented": True}
        )
        return
    report["updatesAvailable"].append(
        {
            "extensionId": install.extension_id,
            "digest": desired_digest,
            "requiresReconsent": True,
            "reason": "code updates never auto-apply (D22) — explicit re-consent",
        }
    )
    note = install.update or {}
    note["desiredPin"] = {"ref": desired_ref, "digest": desired_digest}
    install.update = note


async def reconcile_boot() -> None:
    """Boot-time reconcile (D13) — best-effort, never fatal to the boot."""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await reconcile(db)
    except Exception:
        logger.warning("boot-time extension reconcile failed", exc_info=True)
