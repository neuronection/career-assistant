"""Career's declarative-surface host (plan 32 Phase 4 / ADR-0040 clause 16).

Mini-app extensions declare ``ui:page`` / ``ui:panel`` surfaces whose
nodes ride the charter's closed component vocabulary (stat, table, cards,
filter-bar, select, badge, progress, actions, evidence). This module is
the registration-time structural gate for those nodes (the family
validator law, D23) and the view assembler the surface API serves to the
frontend, which renders through ``@neuronection/assistant-ui``
SurfaceRenderer — extensions never contribute markup (D17: no raw
HTML/JS from extensions is ever rendered at any tier; unknown node or
action ids never render).

Career's surface profile (hostProfiles — charter, Phase 4): pages and
panels are honored; ``ui:window`` is declined on the web host and DEGRADES
along the charter degrade rules (window → page → panel) — the compat
check is data, never code. ``run`` is honored as the typed-action funnel
(surface-kind packs ship ``run:export``-class actions; the pipeline-bearing
run bridge stays with plan 32 Phase 5).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.errors import ValidationError

logger = logging.getLogger(__name__)


DEGRADE_RULES = {
    "window": ("page", "panel"),
    "page": ("panel",),
    "panel": (),
}

COMPONENTS = frozenset(
    {
        "stat",
        "table",
        "cards",
        "filter-bar",
        "select",
        "badge",
        "progress",
        "actions",
        "evidence",
    }
)

RUN_ACTION_IDS = frozenset(
    {"run:cancel", "run:retry", "run:resume", "run:arm", "run:export", "run:diff"}
)
ITEM_ACTION_IDS = frozenset(
    {"item:exclude", "item:override", "item:restore", "item:reveal", "item:open"}
)
ACTION_IDS = RUN_ACTION_IDS | ITEM_ACTION_IDS

SURFACE_NODE_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
MAX_NODES_PER_SURFACE = 96
MAX_ROWS = 300
MAX_DATA_KEYS = 24
CELL_TEXT_CAP = 2000

SURFACE_KINDS = ("page", "panel", "window")


def surface_capabilities(manifest: dict) -> dict:
    """Which declared ui:* surfaces career honors, with the recorded
    degrades (data, never code — D17). Career honors ``page`` + ``panel``;
    a declared ``ui:window`` DEGRADES to the page surface (the first
    honored target along the charter degrade rules)."""
    caps = set(manifest.get("capabilities") or [])
    declared = sorted(c for c in caps if c.startswith("ui:"))
    honored: list[str] = []
    degrades: dict[str, str] = {}
    for cap in declared:
        kind = cap.removeprefix("ui:")
        target = degrade_target(kind)
        if target is None:
            raise ValidationError(
                f"surface {kind!r}: no honored or degradable target on this host — self-disable"
            )
        if target != kind:
            degrades[kind] = target
        if target not in honored:
            honored.append(target)
    return {
        "honored": [k for k in ("page", "panel") if k in honored],
        "degrades": degrades,
        "declared": declared,
    }


def degrade_target(kind: str) -> str | None:
    """Charter degrade rules applied to career's profile: window Hosting
    is declined on the web host → page (first honored target); page and
    panel are honored as declared."""
    if kind in ("page", "panel"):
        return kind
    if kind == "window":
        return next((k for k in DEGRADE_RULES["window"] if k in ("page", "panel")), None)
    return None


def validate_surface_nodes(nodes: list, *, kind: str) -> None:
    """Registration-time structural gate for ONE surface's nodes (the
    family schema laws, career's host-side deep validation): closed
    component vocabulary, shape discipline per type, unique patterned ids,
    closed action ids, and the evidence law wherever recommendations
    render (ADR-0029). Manifest-invalid nodes throw here — surfaces never
    half-run."""
    if not isinstance(nodes, list) or not nodes:
        raise ValidationError(f"surface {kind!r} requires a non-empty nodes array")
    if len(nodes) > MAX_NODES_PER_SURFACE:
        raise ValidationError(f"surface {kind!r} exceeds {MAX_NODES_PER_SURFACE} nodes")
    seen: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValidationError(f"surface {kind!r}: node is not an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not SURFACE_NODE_ID.fullmatch(node_id):
            raise ValidationError(
                f"surface {kind!r}: component ids are lowercase alphanumeric/dash"
                f" (<=40 chars): {node_id!r}"
            )
        if node_id in seen:
            raise ValidationError(f"surface {kind!r}: duplicate component id {node_id!r}")
        seen.add(node_id)
        node_type = node.get("type")
        if node_type not in COMPONENTS:
            raise ValidationError(
                f"surface {kind!r} node {node_id!r}: unknown component type "
                f"{node_type!r} (closed vocabulary: {sorted(COMPONENTS)})"
            )
        if node_type in ("stat", "badge", "progress", "select"):
            if not isinstance(node.get("bind"), str) or not node["bind"]:
                raise ValidationError(
                    f"surface {kind!r} node {node_id!r}: bind must be a data key string"
                )
            if node_type == "select" and (
                not isinstance(node.get("options"), list)
                or not node["options"]
                or any(not isinstance(o, str) for o in node["options"])
            ):
                raise ValidationError(
                    f"surface {kind!r} node {node_id!r}: select requires non-empty string options"
                )
        if node_type == "table" and (
            not isinstance(node.get("columns"), list)
            or not node["columns"]
            or any(not isinstance(c, str) or not c for c in node["columns"])
        ):
            raise ValidationError(
                f"surface {kind!r} node {node_id!r}: table requires non-empty string columns"
            )
        if node_type == "cards" and node.get("of") not in ("items", "groups"):
            raise ValidationError(
                f"surface {kind!r} node {node_id!r}: cards.of must be 'items' or 'groups'"
            )
        if node_type == "filter-bar" and (
            not isinstance(node.get("filters"), list) or not node["filters"]
        ):
            raise ValidationError(
                f"surface {kind!r} node {node_id!r}: filter-bar requires non-empty filters"
            )
        if node_type == "actions" and (
            not isinstance(node.get("actions"), list)
            or not node["actions"]
            or any(a not in ACTION_IDS for a in node["actions"])
        ):
            raise ValidationError(
                f"surface {kind!r} node {node_id!r}: actions must be a non-empty"
                " list of closed typed ids (run:*, item:* — unknown ids never render)"
            )
    shows_items = any(n.get("type") in ("table", "cards") for n in nodes)
    if shows_items and not any(n.get("type") == "evidence" for n in nodes):
        raise ValidationError(
            f"surface {kind!r}: a table/cards component renders recommendations — "
            "the evidence component is mandatory (ADR-0029)"
        )


def validate_data(manifest: dict) -> dict:
    """The declared T0 data block (plan 32 Phase 4): rows for the table/cards
    nodes live under ``rows``; ``groups`` maps card group keys onto heading
    labels; every other key carries scalar or nested-object bind values
    (dot paths walk them, e.g. ``totals.layouts``). Career's surface host
    caps the deck — a declarative pack is data, never an upload surface."""
    data = manifest.get("data")
    if not data:
        return {}
    if not isinstance(data, dict):
        raise ValidationError("manifest data must be an object of key → value")
    if len(data) > MAX_DATA_KEYS:
        raise ValidationError(f"manifest data carries more than {MAX_DATA_KEYS} keys")
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not SURFACE_NODE_ID.fullmatch(key):
            raise ValidationError(f"manifest data key {key!r} is not lowercase-dash safe")
        if isinstance(value, list):
            if len(value) > MAX_ROWS:
                raise ValidationError(f"manifest data[{key}] exceeds {MAX_ROWS} rows")
            normalized[key] = value
        elif isinstance(value, dict):
            normalized[key] = _cap_json(value)
        elif isinstance(value, (str, int, float, bool)):
            normalized[key] = value
        else:
            raise ValidationError(
                f"manifest data[{key}] must be a row array, object or scalar value"
            )
    return normalized


def _cap_json(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, dict):
        return {
            str(key): _cap_json(item, depth + 1)
            for key, item in list(value.items())[:64]
            if key is not None
        }
    if isinstance(value, list):
        return [_cap_json(item, depth + 1) for item in value[:MAX_ROWS]]
    if isinstance(value, str):
        return value[:CELL_TEXT_CAP]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return json.dumps(value)[:CELL_TEXT_CAP]


def surface_view(manifest: dict, *, locale: str = "en") -> dict:
    """Assemble the surface view the frontend renders (nodes + resolved
    labels + rows/values from the declared data). Raises ValidationError
    for structurally invalid surfaces — feeder of the API surface view."""
    surfaces = manifest.get("surfaces")
    if not isinstance(surfaces, dict) or not surfaces:
        raise ValidationError("mini-app declares no surface schema (surfaces.{page,panel,window})")
    kind = _host_surface_kind(surfaces)
    nodes = surfaces[kind].get("nodes") if isinstance(surfaces.get(kind), dict) else None
    if nodes is None:
        raise ValidationError(f"surface {kind!r} missing")
    validate_surface_nodes(nodes, kind=kind)
    data = validate_data(manifest)
    labels, missing = _resolve_labels(manifest, kind, locale)
    view: dict = {
        "kind": kind,
        "degraded": {k: degrade_target(k) for k in sorted(surfaces) if degrade_target(k) != k},
        "nodes": nodes,
        "labels": labels,
        "rows": _rows_from(data.get("rows")),
        "values": {k: v for k, v in data.items() if not isinstance(v, list)},
        "groups": _groups_from(data),
        "filters": {},
    }
    view["filters"] = _facets_from_config(manifest, labels)
    return {
        "surface": view,
        "missing_labels": missing,
    }


def _host_surface_kind(surfaces: dict) -> str:
    for kind in ("page", "panel", "window"):
        if kind in surfaces:
            return kind
    raise ValidationError("surface schema carries none of the hostable kinds")


def _rows_from(rows: Any) -> list[dict]:
    """Data rows → SurfaceRow-shaped dicts (id required; cells capped).
    A row is either a plain column dict or carries the optional
    presentation fields (title/badge/badgeField/group/meta/evidence/
    evidenceSummary/actions)."""
    if not isinstance(rows, list):
        return []
    presentational = {
        "id",
        "title",
        "badge",
        "badgeField",
        "group",
        "meta",
        "evidence",
        "evidenceSummary",
        "actions",
    }
    out: list[dict] = []
    for index, item in enumerate(rows[:MAX_ROWS]):
        if not isinstance(item, dict):
            out.append({"id": f"row-{index + 1}", "values": {"value": _cell(item)}})
            continue
        row_id = item.get("id")
        if not isinstance(row_id, str) or not row_id:
            row_id = f"row-{index + 1}"
        entry: dict[str, Any] = {
            "id": row_id,
            "values": {
                key: _cell(value) for key, value in item.items() if key not in presentational
            },
        }
        if isinstance(item.get("title"), str):
            entry["title"] = _cap(item["title"])
        if isinstance(item.get("badge"), str):
            entry["badge"] = _cap(item["badge"])
            if isinstance(item.get("badgeField"), str):
                entry["badgeField"] = item["badgeField"]
        if isinstance(item.get("group"), str):
            entry["group"] = _cap(item["group"])
        if isinstance(item.get("meta"), list):
            entry["meta"] = [_cap(str(segment)) for segment in item["meta"] if segment][:8]
        if item.get("evidence") is not None:
            entry["evidence"] = item["evidence"]
        if isinstance(item.get("evidenceSummary"), str):
            entry["evidenceSummary"] = _cap(item["evidenceSummary"])
        if isinstance(item.get("actions"), list):
            entry["actions"] = [
                a for a in item["actions"] if isinstance(a, str) and a in ACTION_IDS
            ]
        out.append(entry)
    return out


def _cell(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value)[:CELL_TEXT_CAP]


def _cap(text: str) -> str:
    return text[:CELL_TEXT_CAP]


def _groups_from(data: dict) -> dict:
    """cards.of='groups' headings ride the declared groups map (data.groups
    — group key → resolved label); unresolved groups fall back to
    status.* labels then the raw key at the renderer."""
    groups = data.get("groups")
    if isinstance(groups, dict):
        return {k: _cap(str(v)) for k, v in groups.items() if isinstance(k, str)}
    return {}


def _facets_from_config(manifest: dict, labels: dict[str, str]) -> list[dict]:
    """filter-bar/select options derive from the configSchema enums (D17:
    forms ride configSchema). Option labels resolve through the manifest's
    own i18n (`config.<property>.<option>` keys; raw options otherwise)."""
    facets: list[dict] = []
    properties = (manifest.get("configSchema") or {}).get("properties") or {}
    for name, prop in properties.items():
        if isinstance(prop, dict) and isinstance(prop.get("enum"), list) and prop["enum"]:
            facets.append(
                {
                    "id": name,
                    "options": [
                        {
                            "value": str(option),
                            "label": labels.get(f"config.{name}.{option}") or None,
                        }
                        for option in prop["enum"][:20]
                        if isinstance(option, (str, int, bool))
                    ],
                }
            )
    return facets


def _manifest_labels(manifest: dict, locale: str) -> dict[str, str]:
    i18n = manifest.get("i18n") or {}
    locales = i18n.get("locales") or {}
    config = locales.get(locale) or {}
    default = locales.get(i18n.get("defaultLocale") or "en") or {}
    return {**default, **config}


def _resolve_labels(manifest: dict, kind: str, locale: str) -> tuple[dict[str, str], list[str]]:
    """Resolve surface-side labels: node labels, table column headers,
    action labels and filter facet labels (locale fallback: the default
    locale, then the raw id). Missing labels are REPORTED not dropped —
    the host surfaces the manifest's gaps honestly."""
    labels = _manifest_labels(manifest, locale)
    missing: list[str] = []
    resolved: dict[str, str] = {}
    nodes = (
        list((manifest.get("surfaces") or {}).get(kind, {}).get("nodes", []))
        if isinstance((manifest.get("surfaces") or {}).get(kind), dict)
        else []
    )
    facets: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("id"):
            if f"report.{node['id']}" not in labels:
                missing.append(f"report.{node['id']}")
            resolved[f"report.{node['id']}"] = labels.get(f"report.{node['id']}") or node["id"]
        if node.get("type") == "table":
            for column in node.get("columns", []) or []:
                key = f"report.{node['id']}.{column}"
                resolved[key] = labels.get(key) or column
        if node.get("type") == "actions":
            for action in node.get("actions", []) or []:
                if f"action.{action}" not in labels:
                    missing.append(f"action.{action}")
                resolved[f"action.{action}"] = labels.get(f"action.{action}") or action
        if node.get("type") == "filter-bar":
            for facet in node.get("filters", []) or []:
                facets.add(facet)
    for facet in sorted(facets):
        key = f"filters.{facet}"
        resolved[key] = labels.get(key) or facet
    return resolved, missing
