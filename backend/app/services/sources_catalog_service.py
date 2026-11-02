"""Instance-wide ATS catalogs (plan 187): one ``app_settings`` row —
``key = "posting.sources.catalogs"`` — read + whole-value writes.

The backend never fetches catalog URLs (no SSRF surface): the browser
fetches, validates, and PUTs the parsed document. Validation here is the
authoritative gate — strict pydantic for shape, the connector REGISTRY
(not a frontend-constant mirror) for connector keys, slug uniqueness, and
the stored-catalogs cap. Concurrency is last-write-wins on the single
row (acceptable for an admin-only manual surface); writes assign the
whole ``value`` — never a nested-list mutation.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.settings_model import AppSetting
from app.schemas.sources_catalog import (
    CATALOG_SETTING_KEY,
    MAX_CATALOGS,
    CatalogUpsertIn,
)

PRESET_KEY_EXAMPLE = "recruitee"


def _registry_connector_keys() -> set[str]:
    from app.extensions.registry import list_connectors

    return {str(entry["key"]) for entry in list_connectors()}


class SourcesCatalogService:
    """Load/upsert/delete over the single catalogs settings row."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _row(self) -> AppSetting | None:
        return (
            await self.db.execute(select(AppSetting).where(AppSetting.key == CATALOG_SETTING_KEY))
        ).scalar_one_or_none()

    async def _row_or_create(self) -> AppSetting:
        row = await self._row()
        if row is None:
            row = AppSetting(key=CATALOG_SETTING_KEY, value={"catalogs": []})
            self.db.add(row)
            try:
                await self.db.commit()
            except IntegrityError:
                await self.db.rollback()
                row = await self._row()
        return row

    async def list_catalogs(self) -> list[dict]:
        row = await self._row()
        if row is None:
            return []
        catalogs = row.value.get("catalogs") if isinstance(row.value, dict) else None
        return [entry for entry in (catalogs or []) if isinstance(entry, dict)]

    async def upsert(self, catalog_id: str, data: CatalogUpsertIn) -> dict:
        """Validate + store one catalog; a known id replaces in place
        (any tier), a new id counts against the max-catalogs cap."""
        entry = self._entry(catalog_id, data)
        existing = await self.list_catalogs()
        index = next((i for i, item in enumerate(existing) if item.get("id") == catalog_id), None)
        if index is None and len(existing) >= MAX_CATALOGS:
            raise ValidationError(
                f"at most {MAX_CATALOGS} catalogs can be stored — remove one first"
            )
        catalogs = list(existing)
        if index is None:
            catalogs.append(entry)
        else:
            catalogs[index] = entry
        row = await self._row_or_create()
        row.value = {"catalogs": catalogs}
        await self.db.commit()
        return entry

    async def delete(self, catalog_id: str) -> bool:
        existing = await self.list_catalogs()
        remaining = [item for item in existing if item.get("id") != catalog_id]
        if len(remaining) == len(existing):
            return False
        row = await self._row_or_create()
        row.value = {"catalogs": remaining}
        await self.db.commit()
        return True

    def _entry(self, catalog_id: str, data: CatalogUpsertIn) -> dict:
        payload = data.model_dump(mode="json")
        url = (payload.get("url") or "").strip() or None
        tier = "user" if url is None else payload["tier"]
        self._validate_catalog(payload, tier=tier)
        return {
            "id": catalog_id,
            "kind": "url" if url else "file",
            "url": url,
            "name": payload["name"],
            "license": payload.get("license"),
            "tier": tier,
            "fetchedAt": payload["fetchedAt"],
            "updatedAt": payload["updatedAt"],
            "revision": payload["revision"],
            "contentHash": payload["contentHash"],
            "etag": payload.get("etag"),
            "lastModified": payload.get("lastModified"),
            "presets": payload["presets"],
            "providers": payload["providers"],
        }

    def _validate_catalog(self, payload: dict, *, tier: str) -> None:
        allowed = _registry_connector_keys()
        slugs: set[str] = set()
        for preset in payload["presets"]:
            slug = preset["slug"]
            if slug in slugs:
                raise ValidationError(f"duplicate preset slug in catalog: {slug}")
            slugs.add(slug)
            if preset["connectorKey"] not in allowed:
                raise ValidationError(f"unknown connector key: {preset['connectorKey']}")
        provider_ids: set[str] = set()
        for provider in payload["providers"]:
            if provider["id"] in provider_ids:
                raise ValidationError(f"duplicate provider id in catalog: {provider['id']}")
            provider_ids.add(provider["id"])
            if provider["connectorKey"] not in allowed:
                raise ValidationError(f"unknown connector key: {provider['connectorKey']}")
        if tier not in ("operator", "community", "user"):
            raise ValidationError(f"unsupported catalog tier: {tier}")
