"""Connector registry (Phase 26 / plan 32 Phase 1): data, not code.

Built-ins auto-register at import with an extension manifest
(``extension/v1`` connector kind, ADR-0040) validated at REGISTRATION
against the vendored envelope schema — capability gating happens there,
never mid-run. The T3 script-tier builtin (``mcp``) is allowlist-gated:
invisible until ``connector_plugins_allowlist`` names it. Third-party
code arrives via the
``career_assistant.connectors`` entry-point group, admin-opt-in through
the ``connector_plugins_allowlist`` setting: that path is **T1 bundled
only** — entry-point plugins are code shipped in the deployment image
(reviewed, in-process by definition, ADR-0040 clause 2). External
authors write T3 MCP connectors (the Phase-2 script tier), never
in-process plugins. Enabling a source = a ``job_sources`` row with
``connector_key`` + validated config; installing a plugin never needs a
migration.
"""

from __future__ import annotations

import json
import logging
import sys
from importlib import metadata
from pathlib import Path

from app.core.errors import ValidationError
from app.extensions import contract, sdk
from app.extensions.builtin import (
    AtsApiConnector,
    CsvConnector,
    JsonLdConnector,
    ManualUrlConnector,
    RssConnector,
)
from app.extensions.builtin.job_boards import (
    ArbeitnowConnector,
    JobicyConnector,
    RemotiveConnector,
)
from app.extensions.builtin.mcp import McpConnector
from app.extensions.sdk import PostingConnector

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "career_assistant.connectors"

_BUILTINS: list[PostingConnector] = [
    AtsApiConnector(),
    JsonLdConnector(),
    RssConnector(),
    CsvConnector(),
    ManualUrlConnector(),
    ArbeitnowConnector(),
    RemotiveConnector(),
    JobicyConnector(),
    McpConnector(),
]

_registry: dict[str, PostingConnector] = {}
_plugins_loaded = False


def _schema_path() -> Path:
    """The vendored envelope schema — repo-root contracts/ in dev/web,
    the frozen bundle's top-level contracts/ dir when packaged."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "contracts" / "extension-manifest.schema.json"
    return Path(__file__).resolve().parents[3] / "contracts" / "extension-manifest.schema.json"


def _docs_tree_schema_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "contracts" / "docs-tree.schema.json"
    return Path(__file__).resolve().parents[3] / "contracts" / "docs-tree.schema.json"


def _bundled_manifest_schema() -> dict:
    try:
        return json.loads(_schema_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"extension manifest schema unavailable at {_schema_path()}: {exc} — "
            "registration fails closed (vendored contract set incomplete)"
        ) from exc


def _docs_tree_schema() -> dict:
    try:
        return json.loads(_docs_tree_schema_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"docs-tree schema unavailable at {_docs_tree_schema_path()}: {exc} — "
            "registration fails closed (vendored contract set incomplete)"
        ) from exc


def _validate_docs_binding(connector: PostingConnector, manifest: dict) -> None:
    """Per-extension docs binding (plan 34 §10.5): a manifest carrying
    the ``docs`` pointer promises a tree that exists beside it and
    validates — a broken promise self-disables exactly like an invalid
    manifest (the extension never half-runs)."""
    pointer = manifest.get("docs")
    if pointer is None:
        return
    if pointer != contract.DOCS_POINTER:
        raise ValidationError(
            f"Connector {connector.key} docs pointer must be "
            f"{contract.DOCS_POINTER!r}, got {pointer!r}"
        )
    docs_dir = sdk.manifest_path(connector).parent / "docs"
    tree_path = docs_dir / "docs-tree.json"
    try:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"Connector {connector.key} points at {contract.DOCS_POINTER} "
            f"but the tree is unreadable ({exc})"
        ) from exc
    schema = _docs_tree_schema()
    err = contract.validate(schema["$defs"]["extensionDocsTree"], tree, schema)
    if err is not None:
        raise ValidationError(f"Connector {connector.key} docs tree invalid: {err}")
    problems = contract.docs_tree_semantics(tree, exists=lambda ref: (docs_dir / ref).is_file())
    if problems:
        raise ValidationError(f"Connector {connector.key} docs tree invalid: {'; '.join(problems)}")


def validate_manifest(connector: PostingConnector) -> dict:
    """Validate a connector's manifest against the vendored envelope
    (bundled form) — the registration-time capability gate. The manifest
    itself is a FILE at the bundle root (``builtin/<key>/manifest.json``,
    the family form) — never code-declared."""
    manifest = connector.manifest()
    schema = _bundled_manifest_schema()
    err = contract.validate(schema["$defs"]["bundledManifest"], manifest, schema)
    if err is not None:
        raise ValidationError(f"Connector {connector.key} manifest invalid: {err}")
    _validate_docs_binding(connector, manifest)
    return manifest


def allowlist_enabled() -> bool:
    from app.core.config import settings

    return bool(getattr(settings, "connector_plugins_allowlist", None))


def plugin_allowed(key: str) -> bool:
    from app.core.config import settings

    allowlist = getattr(settings, "connector_plugins_allowlist", None) or []
    return key in allowlist


def _load_plugins() -> None:
    """Entry-point discovery — T1 bundled plugins, opt-in via the allowlist."""
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    for connector in _BUILTINS:
        # Allowlist-gated builtins (the T3 script tier) are invisible
        # until the admin opts in — off by default, structurally; a
        # removed allowlist entry unregisters on the next load.
        if getattr(connector, "allowlist_gated", False) and not plugin_allowed(connector.key):
            _registry.pop(connector.key, None)
            continue
        validate_manifest(connector)
        _registry[connector.key] = connector
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        return
    for ep in eps:
        try:
            connector = ep.load()()
        except Exception as exc:
            logger.warning("Connector plugin %s failed to load: %s", ep.name, exc)
            continue
        if not isinstance(connector, PostingConnector):
            logger.warning("Connector plugin %s is not a PostingConnector", ep.name)
            continue
        if not plugin_allowed(connector.key):
            logger.info(
                "Connector plugin %s discovered but not allowlisted — skipping",
                connector.key,
            )
            continue
        try:
            validate_manifest(connector)
        except ValidationError as exc:
            logger.warning("Connector plugin %s rejected at registration: %s", ep.name, exc)
            continue
        _registry.setdefault(connector.key, connector)


def reset_registry() -> None:
    """Test hook: drop plugin entries (built-ins stay)."""
    global _plugins_loaded
    for key in list(_registry):
        if key not in {c.key for c in _BUILTINS}:
            del _registry[key]
    _plugins_loaded = False


def register_connector(connector: PostingConnector, *, allow: bool = True) -> None:
    """Registration used by tests and by allowlisted plugins at runtime.

    The manifest gate runs for EVERY registration: an envelope-invalid
    connector never enters the registry (throws here, never mid-run)."""
    if not allow and not plugin_allowed(connector.key):
        raise ValidationError(f"Connector plugin not allowlisted: {connector.key}")
    validate_manifest(connector)
    _registry[connector.key] = connector


def get_connector(key: str) -> PostingConnector:
    _load_plugins()
    connector = _registry.get(key)
    if connector is None:
        raise ValidationError(f"Unknown connector: {key}")
    return connector


async def resolve_connector(db, key: str) -> PostingConnector:
    """The sync-time routing table: built-ins (T1, in-process, unchanged)
    first; any other key resolves as an imported T2 instance and executes
    through the sandbox runner (plan 32 Phase 5 — imported third-party
    code never runs in-process, D2)."""
    _load_plugins()
    connector = _registry.get(key)
    if connector is not None:
        return connector
    from app.extensions.lifecycle import t2_install
    from app.extensions.runtime.sandbox.connector import SandboxConnector

    return SandboxConnector(db, await t2_install(db, key))


def iter_connectors() -> list[PostingConnector]:
    """Registered connector instances (the chat-tools bridge reads their
    manifests) — triggers the lazy load like every other accessor."""
    _load_plugins()
    return list(_registry.values())


def list_connectors() -> list[dict]:
    _load_plugins()
    return [
        {
            "key": c.key,
            "title": c.title,
            "docs_url": c.docs_url,
            "capabilities": c.capabilities.model_dump(mode="json"),
            "builtin": c.key in {b.key for b in _BUILTINS},
            "config_schema": c.config_model().model_json_schema(),
            "manifest": c.manifest(),
            "secret_fields": contract.secret_fields(c.manifest().get("configSchema")),
        }
        for c in _registry.values()
    ]
