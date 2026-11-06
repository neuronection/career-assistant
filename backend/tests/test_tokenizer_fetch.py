"""Pinned HF tokenizer fetch (plan 52 T2b): allowlist, bounds, cache, audit."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import DomainError
from app.models.background_job_model import BackgroundJob
from app.models.identity_model import AuditEvent
from app.services import tokenizer_fetch
from app.services.tokenizer_fetch import (
    ALLOWED_HOSTS,
    MAX_TOKENIZER_BYTES,
    TokenizerFetchError,
    TokenizerFetchRequest,
    TokenizerFetchResult,
    fetch_tokenizer_asset,
    fetch_url,
    handle_tokenizer_fetch,
    validate_fetch_url,
)
from app.storage import retrieval_ops as ops

HF_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tokenizer_hf_wordlevel.json"
REVISION = "0123456789abcdef0123456789abcdef01234567"
SHA = hashlib.sha256(HF_FIXTURE.read_bytes()).hexdigest()


def _request(**overrides) -> TokenizerFetchRequest:
    payload = {
        "repository": "org/model",
        "revision": REVISION,
        "files": ("tokenizer.json",),
        "expected_sha256": SHA,
    }
    payload.update(overrides)
    return TokenizerFetchRequest(**payload)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_fetch_job_is_not_a_space_run():
    assert "TOKENIZER_FETCH" in ops.TOKENIZER_JOB_TYPES
    assert "TOKENIZER_FETCH" not in ops.VECTOR_JOB_TYPES


def test_fetch_request_requires_pinned_revision_and_allowlisted_files():
    with pytest.raises(TokenizerFetchError) as error:
        _request(revision="main")
    assert error.value.reason == "revision_not_pinned"

    with pytest.raises(TokenizerFetchError) as error:
        _request(repository="https://evil.example/model")
    assert error.value.reason == "invalid_repository"

    with pytest.raises(TokenizerFetchError) as error:
        _request(files=("tokenizer.json", "pytorch_model.bin"))
    assert error.value.reason == "file_not_allowed"

    with pytest.raises(TokenizerFetchError) as error:
        _request(files=("config.json",))
    assert error.value.reason == "invalid_files"

    with pytest.raises(TokenizerFetchError) as error:
        _request(expected_sha256="not-a-sha")
    assert error.value.reason == "invalid_checksum"


def test_fetch_url_host_allowlist():
    assert fetch_url("org/model", REVISION, "tokenizer.json").startswith(
        "https://huggingface.co/org/model/resolve/"
    )
    for host in ALLOWED_HOSTS:
        assert validate_fetch_url(f"https://{host}/x") == f"https://{host}/x"
    for url in (
        "https://evil.example/tokenizer.json",
        "http://huggingface.co/tokenizer.json",
        "https://user:pass@huggingface.co/tokenizer.json",
    ):
        with pytest.raises(TokenizerFetchError) as error:
            validate_fetch_url(url)
        assert error.value.reason == "host_not_allowed"


async def test_fetch_downloads_verifies_and_caches(tmp_path: Path):
    payload = HF_FIXTURE.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "huggingface.co"
        assert request.url.path.endswith("/tokenizer.json")
        return httpx.Response(200, content=payload)

    client = _client(handler)
    try:
        result = await fetch_tokenizer_asset(_request(), cache_dir=tmp_path, client=client)
    finally:
        await client.aclose()
    assert result.sha256 == SHA
    assert result.size_bytes == len(payload)
    assert result.cached is False
    cached = tmp_path / SHA / "tokenizer.json"
    assert cached.read_bytes() == payload

    def forbidden(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"cache hit must not fetch: {request.url}")

    client = _client(forbidden)
    try:
        again = await fetch_tokenizer_asset(_request(), cache_dir=tmp_path, client=client)
    finally:
        await client.aclose()
    assert again.cached is True
    assert again.sha256 == SHA


async def test_fetch_rejects_checksum_mismatch_and_oversize(tmp_path: Path):
    payload = HF_FIXTURE.read_bytes()

    def wrong(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    client = _client(wrong)
    try:
        with pytest.raises(TokenizerFetchError) as error:
            await fetch_tokenizer_asset(
                _request(expected_sha256="a" * 64), cache_dir=tmp_path, client=client
            )
    finally:
        await client.aclose()
    assert error.value.reason == "checksum_mismatch"

    def huge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_TOKENIZER_BYTES + 1))

    client = _client(huge)
    try:
        with pytest.raises(TokenizerFetchError) as error:
            await fetch_tokenizer_asset(
                _request(expected_sha256=None), cache_dir=tmp_path, client=client
            )
    finally:
        await client.aclose()
    assert error.value.reason == "asset_too_large"


async def test_fetch_refuses_a_redirect_outside_the_allowlist(tmp_path: Path):
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/tokenizer.json"})

    client = _client(redirect)
    try:
        with pytest.raises(TokenizerFetchError) as error:
            await fetch_tokenizer_asset(_request(), cache_dir=tmp_path, client=client)
    finally:
        await client.aclose()
    assert error.value.reason == "host_not_allowed"


async def _noop_progress(value: int, stage: str, detail=None) -> None:
    del value, stage, detail


async def _not_cancelled() -> bool:
    return False


async def test_fetch_handler_audits_success_and_failure(db):
    job = BackgroundJob(
        job_type="tokenizer_fetch",
        payload={
            "repository": "org/model",
            "revision": REVISION,
            "files": ["tokenizer.json"],
            "expected_sha256": SHA,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    async def success(request: TokenizerFetchRequest) -> TokenizerFetchResult:
        assert request.revision == REVISION
        return TokenizerFetchResult(
            repository=request.repository,
            revision=request.revision,
            sha256=SHA,
            size_bytes=len(HF_FIXTURE.read_bytes()),
            cached=False,
            files={"tokenizer.json": len(HF_FIXTURE.read_bytes())},
        )

    result = await handle_tokenizer_fetch(
        db,
        job,
        progress=_noop_progress,
        cancelled=_not_cancelled,
        fetcher=success,
    )
    assert result["sha256"] == SHA
    audits = (await db.execute(select(AuditEvent))).scalars().all()
    assert any(row.action == "vector.tokenizer.fetched" for row in audits)
    assert any(SHA in row.resource for row in audits)

    async def failure(request: TokenizerFetchRequest) -> TokenizerFetchResult:
        raise TokenizerFetchError("host_not_allowed", "evil.example")

    with pytest.raises(DomainError):
        await handle_tokenizer_fetch(
            db,
            job,
            progress=_noop_progress,
            cancelled=_not_cancelled,
            fetcher=failure,
        )
    audits = (await db.execute(select(AuditEvent))).scalars().all()
    assert any(row.action == "vector.tokenizer.fetch_failed" for row in audits)


async def test_fetch_handler_rejects_an_unpinned_payload(db):
    job = BackgroundJob(
        job_type="tokenizer_fetch",
        payload={"repository": "org/model", "revision": "main"},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    with pytest.raises(DomainError):
        await handle_tokenizer_fetch(
            db,
            job,
            progress=_noop_progress,
            cancelled=_not_cancelled,
            fetcher=None,
        )
    audits = (await db.execute(select(AuditEvent))).scalars().all()
    assert any(row.action == "vector.tokenizer.fetch_failed" for row in audits)


def test_default_cache_is_content_addressed():
    path = tokenizer_fetch.cache_path(SHA, "/tmp/cache")
    assert path == Path("/tmp/cache") / SHA / "tokenizer.json"


async def test_fetch_api_enqueues_and_reads_status(client, auth_headers, db):
    from tests.conftest import register_user

    payload = {
        "repository": "org/model",
        "revision": REVISION,
        "expected_sha256": SHA,
    }
    started = await client.post(
        "/api/v1/admin/retrieval/tokenizer/fetch",
        json=payload,
        headers={**auth_headers, "Idempotency-Key": "fetch-api-test-0001"},
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["job_type"] == "tokenizer_fetch"
    assert body["status"] == "queued"
    assert body["requested"]["revision"] == REVISION

    status = await client.get(
        f"/api/v1/admin/retrieval/tokenizer/fetch/{body['job_id']}",
        headers=auth_headers,
    )
    assert status.status_code == 200, status.text
    detail = status.json()
    assert detail["job_id"] == body["job_id"]
    assert detail["requested"]["repository"] == "org/model"
    ops.assert_no_raw_text(detail)

    replay = await client.post(
        "/api/v1/admin/retrieval/tokenizer/fetch",
        json=payload,
        headers={**auth_headers, "Idempotency-Key": "fetch-api-test-0001"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["job_id"] == body["job_id"]
    assert replay.json()["deduplicated"] is True

    invalid = await client.post(
        "/api/v1/admin/retrieval/tokenizer/fetch",
        json={**payload, "revision": "main"},
        headers={**auth_headers, "Idempotency-Key": "fetch-api-test-0002"},
    )
    assert invalid.status_code == 422 or invalid.status_code == 400

    nonadmin = await register_user(client, "tokenizer-fetch-nonadmin@example.com")
    assert (
        await client.post(
            "/api/v1/admin/retrieval/tokenizer/fetch",
            json=payload,
            headers={**nonadmin, "Idempotency-Key": "fetch-api-test-0003"},
        )
    ).status_code == 403
    assert (
        await client.get(
            f"/api/v1/admin/retrieval/tokenizer/fetch/{body['job_id']}",
            headers=nonadmin,
        )
    ).status_code == 403
