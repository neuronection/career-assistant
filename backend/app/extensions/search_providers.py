"""Web-search provider settings (family shape, ADR-0035 / plan 28 Phase 4).

App-side policy over the family contract: an ordered `providers[]` list in
the `web.search_providers` AppSetting (admin scope, instance-wide), keys
Fernet-encrypted inside the setting row (never returned), lazy migration
from the pre-plan-28 single `web.searxng_url` value, and ordered-fallback
search (first enabled provider that answers wins).

The wire transport stays career's own: SearXNG search runs through the
SSRF-guarded `webfetch` client (plan 80 trust boundary — app policy, not
contract). Only the searxng type is offered until guarded adapters exist
for the POST-style providers; the vendored catalog gates the UI.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.settings_model import AppSetting

SETTING_KEY = "web.search_providers"
LEGACY_SETTING_KEY = "web.searxng_url"

# Career's guarded transport covers searxng today; keyed POST providers
# (tavily/brave/exa/serper/google-pse) join when guarded adapters land.
SUPPORTED_TYPES = ("searxng",)

LEGACY_PROVIDER_ID = "legacy"


class SearchProviderError(Exception):
    """App-level settings error; `kind` mirrors the family taxonomy."""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        self.message = message
        super().__init__(message)


def provider_key_hint(api_key: str) -> str:
    return f"••••{api_key[-4:]}" if len(api_key) > 4 else "••••"


async def _setting(db: AsyncSession, key: str) -> dict:
    row = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalars().first()
    return row.value if row is not None else {}


def _provider_rows(raw_list: object) -> list[dict]:
    return (
        [entry for entry in raw_list if isinstance(entry, dict)]
        if isinstance(raw_list, list)
        else []
    )


async def _put_setting(db: AsyncSession, key: str, value: dict) -> None:
    row = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalars().first()
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    await db.commit()


def _normalize(raw: dict) -> dict:
    provider_id = str(raw.get("id", "")).strip()
    if not provider_id:
        raise SearchProviderError("bad_request", "provider id is required")
    p_type = str(raw.get("type", "")).strip()
    if p_type not in SUPPORTED_TYPES:
        raise SearchProviderError(
            "unknown_type",
            f"provider type must be one of {list(SUPPORTED_TYPES)} "
            "(keyed POST providers join when guarded adapters land)",
        )
    name = str(raw.get("name", "") or "").strip() or "SearXNG"
    base_url = str(raw.get("base_url", "") or "").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise SearchProviderError("missing_config", "a base URL is required")
    try:
        max_results = int(raw.get("max_results", 5))
    except (TypeError, ValueError):
        max_results = 5
    return {
        "id": provider_id,
        "name": name,
        "type": p_type,
        "enabled": bool(raw.get("enabled", True)),
        "base_url": base_url,
        "key_hint": str(raw.get("key_hint", "") or "").strip() or None,
        "max_results": max(1, min(max_results, 10)),
        "api_key_enc": str(raw.get("api_key_enc", "") or "") or None,
    }


async def list_providers(db: AsyncSession) -> list[dict]:
    """Normalized provider views (no key material), with lazy migration."""
    raw_list = (await _setting(db, SETTING_KEY)).get("providers")
    providers = _provider_rows(raw_list)

    legacy = (await _setting(db, LEGACY_SETTING_KEY)).get("url")
    if not providers and legacy:
        providers = [
            _normalize(
                {
                    "id": LEGACY_PROVIDER_ID,
                    "name": "SearXNG",
                    "type": "searxng",
                    "enabled": True,
                    "base_url": legacy,
                }
            )
        ]
        await _put_setting(db, SETTING_KEY, {"providers": providers})
        await _put_setting(db, LEGACY_SETTING_KEY, {})

    views = []
    for entry in providers:
        try:
            normalized = _normalize(entry)
        except SearchProviderError:
            continue
        views.append({**normalized, "key_set": bool(normalized.get("api_key_enc"))})
        views[-1].pop("api_key_enc")
    return views


async def _write_providers(db: AsyncSession, providers: list[dict]) -> None:
    await _put_setting(db, SETTING_KEY, {"providers": providers})


async def upsert_provider(db: AsyncSession, body: dict, *, provider_id: str | None = None) -> dict:
    raw_list = (await _setting(db, SETTING_KEY)).get("providers")
    providers = _provider_rows(raw_list)

    api_key = body.get("api_key")
    if provider_id is None:
        provider_id = uuid.uuid4().hex[:8]
        target: dict = {"id": provider_id}
        providers.append(target)
    else:
        index = next(
            (i for i, entry in enumerate(providers) if entry.get("id") == provider_id), None
        )
        if index is None:
            raise SearchProviderError("bad_request", f"provider '{provider_id}' not found")
        target = providers[index]

    merged = {
        **target,
        **{key: value for key, value in body.items() if key != "api_key" and value is not None},
    }
    merged["id"] = provider_id

    if api_key is not None:
        if str(api_key).strip():
            merged["api_key_enc"] = encrypt_secret(str(api_key).strip()) or ""
            merged["key_hint"] = provider_key_hint(str(api_key).strip())
        else:
            merged["api_key_enc"] = None
            merged["key_hint"] = None

    normalized = _normalize(merged)
    providers[providers.index(target)] = normalized
    await _write_providers(db, providers)
    view = {**normalized, "key_set": bool(normalized.get("api_key_enc"))}
    view.pop("api_key_enc")
    return view


async def delete_provider(db: AsyncSession, provider_id: str) -> bool:
    raw_list = (await _setting(db, SETTING_KEY)).get("providers")
    providers = _provider_rows(raw_list)
    remaining = [entry for entry in providers if entry.get("id") != provider_id]
    if len(remaining) == len(providers):
        return False
    await _write_providers(db, remaining)
    return True


async def move_provider(db: AsyncSession, provider_id: str, direction: str) -> list[dict]:
    if direction not in ("up", "down"):
        raise SearchProviderError("bad_request", "direction must be 'up' or 'down'")
    providers = await list_providers(db)
    index = next((i for i, entry in enumerate(providers) if entry["id"] == provider_id), None)
    if index is None:
        raise SearchProviderError("bad_request", f"provider '{provider_id}' not found")
    swap = index - 1 if direction == "up" else index + 1
    if 0 <= swap < len(providers):
        providers[index], providers[swap] = providers[swap], providers[index]
        await _write_providers(db, providers)
    return await list_providers(db)


async def provider_api_key(db: AsyncSession, provider_id: str) -> str:
    raw_list = (await _setting(db, SETTING_KEY)).get("providers")
    providers = _provider_rows(raw_list)
    entry = next((entry for entry in providers if entry.get("id") == provider_id), None)
    if entry is None or not entry.get("api_key_enc"):
        return ""
    return decrypt_secret(entry["api_key_enc"]) or ""


async def search_with_fallback(db: AsyncSession, query: str, n: int) -> dict | None:
    """First enabled provider that answers wins; None = none configured.

    The result carries the family-normalized shape plus the serving
    provider's name; failures accumulate per provider like the desktop
    reference — the last provider's status is preserved so callers can
    report honest reasons (json_disabled vs unreachable vs …)."""
    from app.services.webfetch import search_web

    providers = [entry for entry in await list_providers(db) if entry["enabled"]]
    if not providers:
        return None
    errors: list[str] = []
    last_result: dict | None = None
    for provider in providers:
        # career's guarded searxng transport (plan 80) — keyless today; the
        # Fernet-stored key rides along when keyed searxng lands
        result = await search_web(provider["base_url"], query, n)
        if result.get("available"):
            return {**result, "provider_name": provider["name"]}
        errors.append(f"{provider['name']}: {result.get('status', 'unreachable')}")
        last_result = result
    return {
        **(last_result or {"status": "unreachable"}),
        "detail": "; ".join(errors)[:300],
    }
