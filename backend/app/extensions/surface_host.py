"""Career's surface host (app-side orchestration, plan 32 Phase 4).

Joins the installed mini-app rows (``extension_installs``) onto the
vendored charter surface laws (:mod:`app.extensions.surfaces`): the one
registry view for the settings/cards UI and the routed page render views.
D24: "api ─ services orchestrate ─ the subsystem holds the machinery" —
this module is the subsystem-side assembly the thin router calls; it
never reaches AI or connector code."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extension_model import ExtensionInstall

MINI_APP_KIND = "mini-app"

PAGE_ROUTE_PREFIX = "/extensions"


def _locale_for(manifest: dict, requested: list[str]) -> str:
    """Clamp the request's locale preferences onto the manifest's declared
    locales (family string rule): the manifest's defaultLocale is the floor."""
    declared = list(((manifest.get("i18n") or {}).get("locales") or {}).keys())
    if not declared:
        return (manifest.get("i18n") or {}).get("defaultLocale") or "en"
    for tag in requested or []:
        if tag in declared:
            return tag
        primary = tag.split("-")[0]
        match = next((d for d in declared if d.split("-")[0] == primary), None)
        if match:
            return match
    return declared[0]


def _card(install: ExtensionInstall, locales: list[str]) -> dict:
    from app.extensions import surfaces as surface_law

    manifest = install.manifest or {}
    capability_view = surface_law.surface_capabilities(manifest)
    labels = surface_law._manifest_labels(manifest, _locale_for(manifest, locales))
    return {
        "extensionId": install.extension_id,
        "title": labels.get("title") or manifest.get("id"),
        "summary": labels.get("summary")
        or labels.get("description")
        or manifest.get("description"),
        "version": install.version,
        "tier": install.tier,
        "originClass": "imported",
        "enabled": install.enabled,
        "capabilities": list(capability_view.get("declared", []) or []),
        "surfaces": capability_view,
        "routes": _surface_route(install.extension_id)
        if "page" in capability_view["honored"]
        else None,
        "consentedAt": (install.consents or [{}])[-1].get("at") if install.consents else None,
        "provenance": {
            "author": manifest.get("author"),
            "license": manifest.get("license"),
            "repository": manifest.get("repository"),
            "description": manifest.get("description"),
        },
    }


def _surface_route(extension_id: str) -> str:
    return f"{PAGE_ROUTE_PREFIX}/{extension_id}"


async def list_surface_cards(db: AsyncSession, *, locales: list[str] | None = None) -> list[dict]:
    """Installed + ENABLED mini-apps (kill switch hides the route entries;
    origin chips per D25; ordered by extension id for a stable view)."""
    rows = await db.execute(
        select(ExtensionInstall)
        .where(ExtensionInstall.enabled.is_(True))
        .order_by(ExtensionInstall.extension_id)
    )
    cards = []
    for install in rows.scalars().all():
        manifest = install.manifest or {}
        if manifest.get("kind") != MINI_APP_KIND or install.state == "removed":
            continue
        try:
            cards.append(_card(install, locales or ["en"]))
        except Exception:  # a structurally invalid manifest self-silences — never the page
            continue
    return cards


async def surface_page_view(
    db: AsyncSession,
    extension_id: str,
    *,
    locales: list[str] | None = None,
) -> dict:
    """The routed page's render view. Disabled/tombstoned/absent installs
    raise LookupError (the router maps that to 404 — the route dies with
    the kill switch)."""
    from app.extensions import surfaces as surface_law

    row = await db.execute(
        select(ExtensionInstall).where(ExtensionInstall.extension_id == extension_id)
    )
    install = row.scalars().first()
    if (
        install is None
        or not install.enabled
        or install.state == "removed"
        or (install.manifest or {}).get("kind") != MINI_APP_KIND
    ):
        raise LookupError(f"surface {extension_id!r} is not available")
    manifest = install.manifest or {}
    requested = locales or ["en"]
    locale = _locale_for(manifest, requested)
    view = surface_law.surface_view(manifest, locale=locale)
    capability_view = surface_law.surface_capabilities(manifest)
    labels = surface_law._manifest_labels(manifest, locale)
    return {
        "extensionId": install.extension_id,
        "version": install.version,
        "title": labels.get("title") or install.extension_id,
        "surface": view["surface"],
        "placeholders": view["missing_labels"],
        "manifestSummary": {
            "kind": manifest.get("kind"),
            "packKind": manifest.get("packKind"),
            "tier": install.tier,
            "originClass": "imported",
            "capabilities": list(capability_view.get("declared", []) or []),
            "surfaces": capability_view,
            "configSchema": manifest.get("configSchema"),
            "description": manifest.get("description"),
        },
    }
