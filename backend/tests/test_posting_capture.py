"""Plan 212 S2.3 — bookmarklet capture: one URL, one idempotent posting."""

from urllib.parse import urlparse

from app.services.integrations.webfetch import WebFetchBlocked
from app.services.postings.capture_service import canonical_url


async def test_capture_is_idempotent_by_canonical_url(
    client, auth_headers, db, profile_ready, seeded_catalog, monkeypatch
):
    calls: list[str] = []

    async def fake_fetch(url: str, **_kw):
        calls.append(url)
        return url, "<html><head><title>Data Analyst</title></head></html>"

    monkeypatch.setattr("app.services.postings.capture_service.fetch_html", fake_fetch)

    first = await client.post(
        "/api/v1/postings/capture",
        json={"url": "https://Jobs.Example.com/roles/42/?utm_source=board&ref=home"},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["created"] is True

    second = await client.post(
        "/api/v1/postings/capture",
        json={"url": "https://jobs.example.com/roles/42?utm_campaign=mail"},
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == body["id"]
    assert second.json()["created"] is False
    assert calls == ["https://jobs.example.com/roles/42"], "canonical URL fetched once"

    from app.models.posting_model import JobPosting, JobSource

    posting = await db.get(JobPosting, body["id"])
    assert posting is not None
    assert posting.title == "Data Analyst"
    assert posting.url == "https://jobs.example.com/roles/42"
    source = await db.get(JobSource, posting.source_id)
    assert source is not None and source.key == "captures"


async def test_capture_rejects_private_or_invalid_urls(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    async def blocked(url: str, **_kw):
        raise WebFetchBlocked("private or reserved address")

    monkeypatch.setattr("app.services.postings.capture_service.fetch_html", blocked)
    denied = await client.post(
        "/api/v1/postings/capture",
        json={"url": "http://127.0.0.1/secret"},
        headers=auth_headers,
    )
    assert denied.status_code == 400

    invalid = await client.post(
        "/api/v1/postings/capture",
        json={"url": "ftp://example.com/job"},
        headers=auth_headers,
    )
    assert invalid.status_code == 400


def test_canonical_url_strips_tracking_only():
    parsed = urlparse(
        canonical_url("https://www.Example.com/jobs/7/?utm_source=x&team=core&gclid=1#apply")
    )
    assert parsed.geturl() == "https://example.com/jobs/7?team=core"


async def test_capture_survives_malformed_payload_and_empty_title(
    client, auth_headers, db, profile_ready, seeded_catalog, monkeypatch
):
    async def fake_fetch(url: str, **_kw):
        return url, (
            "<html><head><title></title>"
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","title":"Broken","employmentType":"Full-time",'
            '"baseSalary":"Negotiable"}'
            "</script></head></html>"
        )

    monkeypatch.setattr("app.services.postings.capture_service.fetch_html", fake_fetch)
    response = await client.post(
        "/api/v1/postings/capture",
        json={"url": "https://jobs.example.com/roles/broken"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] is True
    from app.models.posting_model import JobPosting

    posting = await db.get(JobPosting, response.json()["id"])
    assert posting is not None
    assert posting.title == "https://jobs.example.com/roles/broken"


def test_canonical_url_keeps_meaningful_query_and_path_cases():
    cases = [
        (
            "https://www.Example.com/jobs/7/?utm_source=x&team=core&gclid=1#apply",
            "https://example.com/jobs/7?team=core",
        ),
        (
            "https://example.com/jobs/7?team=core&utm_medium=y",
            "https://example.com/jobs/7?team=core",
        ),
        ("https://EXAMPLE.com/jobs/7/", "https://example.com/jobs/7"),
        ("https://example.com/", "https://example.com/"),
        (
            "https://example.com/jobs/7?ref=board&source=feed&reference=abc",
            "https://example.com/jobs/7?reference=abc",
        ),
    ]
    for raw, expected in cases:
        assert canonical_url(raw) == expected
    assert canonical_url("https://example.com/Jobs/7") != canonical_url(
        "https://example.com/jobs/7"
    )
    assert canonical_url("http://example.com/jobs/7") != canonical_url("https://example.com/jobs/7")


async def test_capture_uses_the_redirected_canonical_url(
    client, auth_headers, db, profile_ready, seeded_catalog, monkeypatch
):
    async def fake_fetch(url: str, **_kw):
        return (
            "https://www.jobs.example.com/roles/9/?utm_source=redirect#top",
            "<html><head><title>Redirected role</title></head></html>",
        )

    monkeypatch.setattr("app.services.postings.capture_service.fetch_html", fake_fetch)
    response = await client.post(
        "/api/v1/postings/capture",
        json={"url": "https://jobs.example.com/start"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    from app.models.posting_model import JobPosting

    posting = await db.get(JobPosting, response.json()["id"])
    assert posting is not None
    assert posting.url == "https://jobs.example.com/roles/9"


async def test_capture_finds_a_pre_capture_row_with_a_tracking_url(
    client, auth_headers, db, source, profile_ready, seeded_catalog, monkeypatch
):
    from tests.conftest import _make_posting

    existing = await _make_posting(
        db,
        source,
        external_id="pre-capture",
        title="Existing role",
        org="Acme",
        url="https://jobs.example.com/roles/11?utm_source=old",
    )

    async def fail_fetch(*args, **kwargs):
        raise AssertionError("an existing canonical row must not be fetched again")

    monkeypatch.setattr("app.services.postings.capture_service.fetch_html", fail_fetch)
    response = await client.post(
        "/api/v1/postings/capture",
        json={"url": "https://www.jobs.example.com/roles/11/"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(existing.id)
    assert response.json()["created"] is False
