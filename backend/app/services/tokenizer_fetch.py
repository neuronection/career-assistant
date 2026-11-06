"""Pinned, bounded Hugging Face tokenizer fetch for the admin job queue.

The only network path for tokenizer assets. A fetch is an explicit admin
action, never a request/boot read path: the request enqueues one
``tokenizer_fetch`` background job, and the handler downloads a small,
allowlisted file set from an allowlisted host at a pinned 40-character commit
revision, verifies the ``tokenizer.json`` SHA-256 and writes it into the
content-addressed local cache (``<cache>/<sha256>/tokenizer.json``).

No ``trust_remote_code``, no repository code, no branch/tag revision, no
arbitrary URL and no unbounded body: redirects are followed only within the
host allowlist and every response is capped. The cache is keyed by content
hash, so a repeat fetch is a cache hit with no network call.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.ai.tokenizers.service import HF_TOKENIZER_FILENAME, default_cache_dir
from app.core.errors import DomainError
from app.services.audit import emitter

FETCH_JOB_TYPE = "tokenizer_fetch"
PRIMARY_TOKENIZER_FILE = HF_TOKENIZER_FILENAME
ALLOWED_FILES = (
    PRIMARY_TOKENIZER_FILE,
    "config.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)
MAX_TOKENIZER_BYTES = 32 * 1024 * 1024
MAX_SMALL_FILE_BYTES = 1024 * 1024
MAX_REDIRECTS = 5
FETCH_TIMEOUT_SECONDS = 30.0

# Hugging Face's own hosts plus the CDN/Xet hosts it redirects to for public
# files. Anything else is refused before a byte is read.
ALLOWED_HOSTS = frozenset(
    {
        "huggingface.co",
        "cdn-lfs.huggingface.co",
        "cdn-lfs-us-1.huggingface.co",
        "cdn-lfs-eu-1.huggingface.co",
        "cas-bridge.xethub.hf.co",
        "cas-server.xethub.hf.co",
    }
)

REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
PINNED_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TokenizerFetchError(ValueError):
    """A typed fetch failure; ``reason`` is safe to surface to the admin."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class TokenizerFetchRequest:
    """One validated pinned fetch request."""

    repository: str
    revision: str
    files: tuple[str, ...] = (PRIMARY_TOKENIZER_FILE,)
    expected_sha256: str | None = None

    def __post_init__(self) -> None:
        repository = str(self.repository or "").strip()
        revision = str(self.revision or "").strip().lower()
        if not REPOSITORY_PATTERN.fullmatch(repository):
            raise TokenizerFetchError(
                "invalid_repository", "repository must be an org/name Hugging Face id"
            )
        if not PINNED_REVISION_PATTERN.fullmatch(revision):
            raise TokenizerFetchError(
                "revision_not_pinned",
                "revision must be a full 40-character commit sha (branches/tags are refused)",
            )
        files = tuple(str(name).strip() for name in self.files)
        if not files:
            raise TokenizerFetchError("invalid_files", "at least tokenizer.json is required")
        unknown = sorted(set(files) - set(ALLOWED_FILES))
        if unknown:
            raise TokenizerFetchError(
                "file_not_allowed", f"{unknown} (allowed: {list(ALLOWED_FILES)})"
            )
        if PRIMARY_TOKENIZER_FILE not in files:
            raise TokenizerFetchError("invalid_files", "tokenizer.json must be included")
        expected = self.expected_sha256
        if expected is not None:
            expected = str(expected).strip().lower()
            if not SHA256_PATTERN.fullmatch(expected):
                raise TokenizerFetchError("invalid_checksum", "expected sha256 must be 64 hex")
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "expected_sha256", expected)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TokenizerFetchRequest:
        """Build from a job/API payload (unknown keys are ignored)."""
        files = payload.get("files")
        if files is None:
            files = (PRIMARY_TOKENIZER_FILE,)
        return cls(
            repository=payload.get("repository", ""),
            revision=payload.get("revision", ""),
            files=tuple(files),
            expected_sha256=payload.get("expected_sha256"),
        )


@dataclass(frozen=True)
class TokenizerFetchResult:
    """The bounded fetch result stored in the job result and returned by the API."""

    repository: str
    revision: str
    sha256: str
    size_bytes: int
    cached: bool
    files: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "revision": self.revision,
            "filename": PRIMARY_TOKENIZER_FILE,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "cached": self.cached,
            "files": dict(self.files),
        }


def fetch_url(repository: str, revision: str, filename: str) -> str:
    """The one canonical download URL shape (no user-supplied host/path)."""
    return f"https://huggingface.co/{repository}/resolve/{revision}/{filename}"


def validate_fetch_url(url: str) -> str:
    """Refuse a non-HTTPS URL, credentials or a host outside the allowlist."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise TokenizerFetchError("host_not_allowed", f"scheme {parts.scheme!r}")
    if parts.username or parts.password:
        raise TokenizerFetchError("host_not_allowed", "credentials in URL")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise TokenizerFetchError("host_not_allowed", host or "missing host")
    if parts.port not in (None, 443):
        raise TokenizerFetchError("host_not_allowed", f"port {parts.port}")
    return url


def cache_path(sha256: str, cache_dir: Path | str | None = None) -> Path:
    """The content-addressed path for one tokenizer.json."""
    root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    return root / sha256 / PRIMARY_TOKENIZER_FILE


def _file_limit(filename: str) -> int:
    return MAX_TOKENIZER_BYTES if filename == PRIMARY_TOKENIZER_FILE else MAX_SMALL_FILE_BYTES


def _has_cached_artifact(sha256: str, cache_dir: Path) -> bool:
    path = cache_path(sha256, cache_dir)
    try:
        payload = path.read_bytes()
    except OSError:
        return False
    return len(payload) <= MAX_TOKENIZER_BYTES and _sha256(payload) == sha256


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def _download(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
) -> bytes:
    """Download one allowlisted URL, following only allowlisted redirects."""
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        validate_fetch_url(current)
        async with client.stream(
            "GET",
            current,
            headers={"User-Agent": "career-assistant-tokenizer-fetch/1"},
        ) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise TokenizerFetchError("fetch_failed", "redirect without location")
                current = urljoin(current, location)
                continue
            if response.status_code != 200:
                raise TokenizerFetchError("fetch_failed", f"HTTP {response.status_code}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise TokenizerFetchError("asset_too_large", f"{total} > {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks)
    raise TokenizerFetchError("fetch_failed", f"more than {MAX_REDIRECTS} redirects")


async def fetch_tokenizer_asset(
    request: TokenizerFetchRequest,
    *,
    cache_dir: Path | str | None = None,
    client: httpx.AsyncClient | None = None,
) -> TokenizerFetchResult:
    """Download/verify/cache the request's files; a cache hit makes no call."""
    root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    expected = request.expected_sha256
    if expected is not None and _has_cached_artifact(expected, root):
        files = {
            name: (cache_path(expected, root).parent / name).stat().st_size
            for name in request.files
            if (cache_path(expected, root).parent / name).is_file()
        }
        return TokenizerFetchResult(
            repository=request.repository,
            revision=request.revision,
            sha256=expected,
            size_bytes=files.get(PRIMARY_TOKENIZER_FILE, 0),
            cached=True,
            files=files,
        )

    owned = client is None
    http_client = client or httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False)
    try:
        primary_bytes: bytes | None = None
        verified: str | None = None
        sizes: dict[str, int] = {}
        ordered = (
            PRIMARY_TOKENIZER_FILE,
            *(name for name in request.files if name != PRIMARY_TOKENIZER_FILE),
        )
        for filename in ordered:
            payload = await _download(
                http_client,
                fetch_url(request.repository, request.revision, filename),
                max_bytes=_file_limit(filename),
            )
            if filename == PRIMARY_TOKENIZER_FILE:
                primary_bytes = payload
                verified = _sha256(payload)
                if expected is not None and verified != expected:
                    raise TokenizerFetchError(
                        "checksum_mismatch", f"expected {expected}, got {verified}"
                    )
                _write_atomic(cache_path(verified, root), payload)
            sizes[filename] = len(payload)
            if filename != PRIMARY_TOKENIZER_FILE and verified is not None:
                _write_atomic(cache_path(verified, root).parent / filename, payload)
        if primary_bytes is None or verified is None:  # pragma: no cover - validated above
            raise TokenizerFetchError("invalid_files", "tokenizer.json was not downloaded")
        return TokenizerFetchResult(
            repository=request.repository,
            revision=request.revision,
            sha256=verified,
            size_bytes=len(primary_bytes),
            cached=False,
            files=sizes,
        )
    finally:
        if owned:
            await http_client.aclose()


async def handle_tokenizer_fetch(
    db,
    job,
    *,
    progress,
    cancelled,
    fetcher=None,
) -> dict[str, Any]:
    """Run one queued fetch; the only caller of the network path."""
    actor = str(job.user_id) if job.user_id is not None else "system"
    try:
        request = TokenizerFetchRequest.from_payload(dict(job.payload or {}))
        await progress(5, "validating pinned tokenizer")
        if await cancelled():
            raise DomainError("Cancelled")
        result = await (fetcher or fetch_tokenizer_asset)(request)
        await progress(95, "tokenizer cached")
        db.add(
            emitter.audit_event(
                actor=actor,
                action="vector.tokenizer.fetched",
                resource_ref=emitter.resource(
                    f"tokenizer:{request.repository}@{request.revision}",
                    sha256=result.sha256,
                ),
            )
        )
        await db.commit()
        return result.to_dict()
    except DomainError:
        raise
    except (TokenizerFetchError, ValueError) as exc:
        reason = getattr(exc, "reason", "fetch_failed")
        detail = getattr(exc, "detail", str(exc))
        db.add(
            emitter.audit_event(
                actor=actor,
                action="vector.tokenizer.fetch_failed",
                resource_ref=emitter.resource(
                    "tokenizer:failed",
                    reason=reason,
                ),
                outcome="failed",
            )
        )
        await db.commit()
        raise DomainError(f"{reason}: {detail}".strip()) from exc


__all__ = [
    "ALLOWED_FILES",
    "ALLOWED_HOSTS",
    "FETCH_JOB_TYPE",
    "MAX_REDIRECTS",
    "MAX_SMALL_FILE_BYTES",
    "MAX_TOKENIZER_BYTES",
    "PRIMARY_TOKENIZER_FILE",
    "TokenizerFetchError",
    "TokenizerFetchRequest",
    "TokenizerFetchResult",
    "cache_path",
    "fetch_tokenizer_asset",
    "fetch_url",
    "handle_tokenizer_fetch",
    "validate_fetch_url",
]
