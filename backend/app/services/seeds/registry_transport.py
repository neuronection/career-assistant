"""Static-index transport for seed providers (plan 218 §3.4).

A registry provider serves the same tree as a seed repository over HTTPS:
``seed-repo.json`` at the index URL, then the selected pack's manifest and
item files. Every request rides the app's guarded fetch (SSRF guard, pinned
resolution, redirect re-validation); the index carries an ETag so an
unchanged provider is a 304 no-op.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.core.seed_pack.errors import (
    DIGEST_MISMATCH,
    INDEX_INVALID,
    MANIFEST_INVALID,
    REGISTRY_FETCH_FAILED,
    REGISTRY_PARTIAL,
    SeedPackError,
)
from app.core.seed_pack.manifest import (
    MAX_ITEM_FILE_BYTES,
    MAX_MANIFEST_BYTES,
    IndexedPack,
    RepoIndex,
    parse_repo_index,
    sha256_hex,
)
from app.services.integrations.webfetch import WebFetchBlocked, fetch_bytes

INDEX_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class IndexFetch:
    index: RepoIndex | None
    etag: str
    base_url: str
    status: int

    @property
    def unchanged(self) -> bool:
        return self.status == 304


def normalize_index_url(uri: str) -> str:
    value = (uri or "").strip()
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise SeedPackError(REGISTRY_FETCH_FAILED, "registry URIs must be https")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise SeedPackError(
            REGISTRY_FETCH_FAILED, "registry URIs must not carry credentials/query/fragment"
        )
    if parts.path.endswith(".json"):
        return value
    return value.rstrip("/") + "/seed-repo.json"


def _base_of(index_url: str) -> str:
    return index_url.rsplit("/", 1)[0]


async def _get(
    url: str, *, etag: str | None = None, max_bytes: int
) -> tuple[int, dict[str, str], bytes, str]:
    headers = {"Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        return await fetch_bytes(url, headers=headers, max_bytes=max_bytes)
    except WebFetchBlocked as exc:
        raise SeedPackError(REGISTRY_FETCH_FAILED, f"{url}: {exc}"[:500]) from exc


class RegistryTransport:
    """Read a repository index and one pack over guarded HTTPS."""

    async def fetch_index(self, uri: str, *, etag: str | None = None) -> IndexFetch:
        url = normalize_index_url(uri)
        status, headers, body, final_url = await _get(url, etag=etag, max_bytes=INDEX_MAX_BYTES)
        base = _base_of(final_url or url)
        if status == 304:
            return IndexFetch(index=None, etag=etag or "", base_url=base, status=304)
        if status != 200:
            raise SeedPackError(REGISTRY_FETCH_FAILED, f"{url}: HTTP {status}")
        try:
            index = parse_repo_index(body)
        except SeedPackError as exc:
            raise SeedPackError(INDEX_INVALID, f"{url}: {exc.detail}") from exc
        return IndexFetch(
            index=index,
            etag=headers.get("etag", ""),
            base_url=base,
            status=status,
        )

    async def fetch_pack(self, base_url: str, indexed: IndexedPack) -> dict[str, bytes]:
        manifest_url = urljoin(f"{base_url}/", indexed.manifest)
        status, _headers, manifest_bytes, _final = await _get(
            manifest_url, max_bytes=MAX_MANIFEST_BYTES
        )
        if status != 200:
            raise SeedPackError(REGISTRY_FETCH_FAILED, f"{manifest_url}: HTTP {status}")
        try:
            manifest: dict[str, Any] = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SeedPackError(MANIFEST_INVALID, f"{manifest_url}: {exc}") from exc
        files: dict[str, bytes] = {"manifest.json": manifest_bytes}
        for entry in manifest.get("item_files") or []:
            path = entry.get("path") if isinstance(entry, dict) else None
            digest = entry.get("sha256") if isinstance(entry, dict) else None
            if not isinstance(path, str) or not isinstance(digest, str):
                raise SeedPackError(MANIFEST_INVALID, f"{manifest_url}: bad item_files entry")
            item_url = urljoin(f"{base_url}/", f"{indexed.path}/{path}")
            try:
                item_status, _item_headers, data, _item_final = await _get(
                    item_url, max_bytes=MAX_ITEM_FILE_BYTES
                )
            except SeedPackError as exc:
                raise SeedPackError(REGISTRY_PARTIAL, f"{item_url}: {exc.detail}"[:500]) from exc
            if item_status != 200:
                raise SeedPackError(REGISTRY_PARTIAL, f"{item_url}: HTTP {item_status}")
            if sha256_hex(data) != digest:
                raise SeedPackError(DIGEST_MISMATCH, item_url)
            files[path] = data
        return files


__all__ = ["IndexFetch", "RegistryTransport", "normalize_index_url"]
