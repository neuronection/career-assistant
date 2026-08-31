"""Connector registry (Phase 26): data, not code.

Built-ins auto-register at import; plugins arrive via the
`career_assistant.connectors` entry-point group and are **admin-opt-in**
through the `connector_plugins_allowlist` setting (they run in-process).
Enabling a source = a `job_sources` row with `connector_key` + validated
config; installing a plugin never needs a migration.
"""

from __future__ import annotations

import logging
from importlib import metadata

from app.connectors.base import PostingConnector
from app.connectors.builtin import (
    AtsApiConnector,
    CsvConnector,
    JsonLdConnector,
    ManualUrlConnector,
    RssConnector,
)
from app.core.errors import ValidationError

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "career_assistant.connectors"

_BUILTINS: list[PostingConnector] = [
    AtsApiConnector(),
    JsonLdConnector(),
    RssConnector(),
    CsvConnector(),
    ManualUrlConnector(),
]

_registry: dict[str, PostingConnector] = {c.key: c for c in _BUILTINS}
_plugins_loaded = False


def allowlist_enabled() -> bool:
    from app.core.config import settings

    return bool(getattr(settings, "CONNECTOR_PLUGINS_ALLOWLIST", None))


def plugin_allowed(key: str) -> bool:
    from app.core.config import settings

    allowlist = getattr(settings, "CONNECTOR_PLUGINS_ALLOWLIST", None) or []
    return key in allowlist


def _load_plugins() -> None:
    """Entry-point discovery — plugin keys are opt-in via the allowlist."""
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        return
    for ep in eps:
        try:
            connector = ep.load()()
        except Exception as exc:  # noqa: BLE001 — one bad plugin never breaks boot
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
        _registry.setdefault(connector.key, connector)


def reset_registry() -> None:
    """Test hook: drop plugin entries (built-ins stay)."""
    global _plugins_loaded
    for key in list(_registry):
        if key not in {c.key for c in _BUILTINS}:
            del _registry[key]
    _plugins_loaded = False


def register_connector(connector: PostingConnector, *, allow: bool = True) -> None:
    """Registration used by tests and by allowlisted plugins at runtime."""
    if not allow and not plugin_allowed(connector.key):
        raise ValidationError(f"Connector plugin not allowlisted: {connector.key}")
    _registry[connector.key] = connector


def get_connector(key: str) -> PostingConnector:
    _load_plugins()
    connector = _registry.get(key)
    if connector is None:
        raise ValidationError(f"Unknown connector: {key}")
    return connector


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
        }
        for c in _registry.values()
    ]
