"""Composite market dashboard (plan 195): one window, one compiled filter
set, per-card isolation and the list-coherent status basis — verified on
Postgres (xdist) and the SQLite lane."""

from datetime import UTC, datetime, timedelta

from app.models.experience_model import Organization
from app.models.job_model import Job, JobFamily
from app.models.posting_model import PostingInteraction
from app.services.postings import stats_dashboard_service, stats_service
from tests.conftest import (
    _add_posting_skill,
    _make_posting,
    register_user,
    user_id_from_headers,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def _dashboard(client, headers, **params):
    response = await client.get("/api/v1/postings/stats/dashboard", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response


async def _explore_total(client, headers, **params) -> int:
    response = await client.get("/api/v1/postings/explore", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return int(response.json()["total"])


async def test_dashboard_resolves_every_card_on_one_as_of(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    await _make_posting(db, source, external_id="dash-1", title="Data Analyst")
    body = (await _dashboard(client, auth_headers, window="30d")).json()

    for card in stats_dashboard_service.DASHBOARD_CARDS:
        assert card in body, card
        assert body[card] is not None, card
    assert body["errors"] == {}
    assert body["window"] == "30d"
    assert body["basis"] == "all"
    assert body["as_of"] == body["summary"]["as_of"]
    assert body["as_of"] == body["overview"]["as_of"]
    assert body["as_of"] == body["clockwork"]["as_of"]
    assert body["bucket"] == body["timeseries"]["bucket"]


async def test_dashboard_cache_control_header(
    client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    response = await client.get(
        "/api/v1/postings/stats/dashboard",
        params={"cards": "summary"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"


async def test_dashboard_card_selection(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    await _make_posting(db, source, external_id="dash-sel")
    body = (await _dashboard(client, auth_headers, cards="summary,overview")).json()
    assert body["summary"] is not None
    assert body["overview"] is not None
    assert body["skills"] is None
    assert body["salary"] is None


async def test_dashboard_invalid_card_is_400(client, auth_headers):
    response = await client.get(
        "/api/v1/postings/stats/dashboard",
        params={"cards": "nope"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "nope" in response.json()["detail"]


async def test_dashboard_rejects_window_owned_filters(client, auth_headers):
    for owned in ("posted_within", "posted_after"):
        response = await client.get(
            "/api/v1/postings/stats/dashboard",
            params={owned: "7d" if owned == "posted_within" else "2026-01-01"},
            headers=auth_headers,
        )
        assert response.status_code == 400, owned
        assert owned in response.json()["detail"]


async def test_dashboard_empty_db_returns_zero_shapes(client, auth_headers):
    body = (await _dashboard(client, auth_headers)).json()
    assert body["summary"]["open_total"] == 0
    assert body["overview"]["new_in_range"]["count"] == 0
    assert body["skills"]["top"] == []
    assert body["salary"]["currencies"] == []
    assert body["companies_summary"]["companies_hiring"] == 0
    assert body["breakdown"]["rows"] == []
    assert sum(cell["count"] for cell in body["clockwork"]["cells"]) == 0


async def test_dashboard_filters_apply_to_every_card(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    await _make_posting(
        db, source, external_id="dash-senior", title="Senior Data Engineer", seniority="senior"
    )
    await _make_posting(
        db, source, external_id="dash-junior", title="Junior Data Analyst", seniority="junior"
    )
    body = (await _dashboard(client, auth_headers, window="30d", seniority="senior")).json()

    assert body["overview"]["new_in_range"]["count"] == 1
    assert body["summary"]["new_30d"]["count"] == 1
    assert sum(cell["count"] for cell in body["clockwork"]["cells"]) == 1
    assert body["applied_filters"]["seniority"] == ["senior"]


async def test_dashboard_user_hidden_follows_the_list_on_both_bases(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    member_headers = await register_user(client, "member@example.com")
    user_id = user_id_from_headers(member_headers)
    visible = await _make_posting(db, source, external_id="dash-visible", title="Visible Role")
    hidden = await _make_posting(db, source, external_id="dash-hidden", title="Hidden Role")
    system_hidden = await _make_posting(
        db, source, external_id="dash-system-hidden", title="System Hidden Role"
    )
    system_hidden.status = "hidden"
    db.add(PostingInteraction(user_id=user_id, posting_id=hidden.id, hidden_at=_now()))
    await db.commit()

    for basis in ("open", "all"):
        body = (
            await _dashboard(client, member_headers, window="30d", basis=basis, cards="overview")
        ).json()
        expected = await _explore_total(client, member_headers, posted_within="30d", basis=basis)
        assert body["overview"]["new_in_range"]["count"] == expected

    all_body = (
        await _dashboard(client, member_headers, window="30d", basis="all", cards="overview")
    ).json()
    assert all_body["overview"]["new_in_range"]["count"] == 1

    include = (
        await _dashboard(
            client,
            member_headers,
            window="30d",
            basis="all",
            hidden_include="true",
            cards="overview",
        )
    ).json()
    assert include["overview"]["new_in_range"]["count"] == 1
    assert "hidden_include" not in include["applied_filters"]
    assert (
        await _explore_total(
            client, member_headers, posted_within="30d", basis="all", hidden_include="true"
        )
        == 2
    )
    assert visible.id and hidden.id


async def test_dashboard_hidden_include_is_admin_only(
    db, client, client_admin_headers, profile_ready, seeded_catalog, source, kinds
):
    """`hidden_include` is an admin/debug escape hatch: a normal user's
    request ignores it, an admin's own hidden rows opt back in."""
    admin_id = user_id_from_headers(client_admin_headers)
    await _make_posting(db, source, external_id="admin-visible", title="Admin Visible Role")
    hidden = await _make_posting(db, source, external_id="admin-hidden", title="Admin Hidden Role")
    db.add(PostingInteraction(user_id=admin_id, posting_id=hidden.id, hidden_at=_now()))
    await db.commit()

    without = (
        await _dashboard(client, client_admin_headers, window="30d", basis="all", cards="overview")
    ).json()
    ignored = (
        await _dashboard(
            client,
            client_admin_headers,
            window="30d",
            basis="all",
            hidden_include="false",
            cards="overview",
        )
    ).json()
    assert without["overview"]["new_in_range"]["count"] == 1
    assert ignored["overview"]["new_in_range"]["count"] == 1

    included = (
        await _dashboard(
            client,
            client_admin_headers,
            window="30d",
            basis="all",
            hidden_include="true",
            cards="overview",
        )
    ).json()
    assert included["overview"]["new_in_range"]["count"] == 2
    assert included["applied_filters"]["hidden_include"] is True
    listing = await _explore_total(
        client,
        client_admin_headers,
        posted_within="30d",
        basis="all",
        hidden_include="true",
    )
    assert included["overview"]["new_in_range"]["count"] == listing


async def test_dashboard_partial_failure_returns_200_with_typed_error(
    client, auth_headers, profile_ready, seeded_catalog, source, kinds, monkeypatch
):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("salary blew up")

    monkeypatch.setattr(stats_service, "salary", boom)
    body = (await _dashboard(client, auth_headers, cards="summary,salary")).json()
    assert body["summary"] is not None
    assert body["salary"] is None
    assert body["errors"]["salary"]["code"] == "error"
    assert "salary blew up" in body["errors"]["salary"]["message"]


async def test_dashboard_timeout_is_isolated_and_the_next_card_still_answers(
    client, auth_headers, profile_ready, seeded_catalog, source, kinds, monkeypatch
):
    async def slow(*_args, **_kwargs):
        import asyncio

        await asyncio.sleep(1.0)
        return None

    monkeypatch.setattr(stats_service, "salary", slow)
    monkeypatch.setattr(stats_dashboard_service, "CARD_TIMEOUT_SECONDS", 0.1)
    started = _now()
    body = (await _dashboard(client, auth_headers, cards="salary,overview")).json()
    assert body["salary"] is None
    assert body["errors"]["salary"]["code"] == "timeout"
    assert body["overview"] is not None
    assert _now() - started < timedelta(seconds=5)


async def test_dashboard_parity_matrix_with_explore(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """Every filterable axis the dashboard forwards counts exactly the
    list the drill opens — same clause, same population."""
    org = Organization(key="parity-acme", name="Parity Acme", status="active")
    family = JobFamily(key="parity-family", label="Parity", path="parity/it", level=1)
    db.add_all([org, family])
    await db.flush()
    job = Job(code="parity-job", title="Parity Analyst", family_id=family.id)
    db.add(job)
    await db.flush()

    match = await _make_posting(
        db,
        source,
        external_id="parity-match",
        title="Parity Match Engineer",
        seniority="senior",
        employment_type="full_time",
        contract_type="permanent",
        onsite_policy="remote",
        education_level="bachelor",
        location={"city": "Athens", "country": "Greece"},
        salary={"min": 60_000, "max": 80_000, "currency": "EUR", "period": "year"},
        skills_raw=[],
        raw={"description": ""},
    )
    match.org_id = org.id
    match.catalog_job_id = job.id
    other = await _make_posting(
        db,
        source,
        external_id="parity-other",
        title="Other Junior Role",
        seniority="junior",
        employment_type="part_time",
        contract_type="temporary",
        onsite_policy="onsite",
        education_level="high_school",
        location={"city": "Berlin", "country": "Germany"},
        salary={"min": 20_000, "max": 25_000, "currency": "EUR", "period": "year"},
        skills_raw=[],
        raw={"description": ""},
    )
    await db.commit()
    await _add_posting_skill(db, match, "programming", 5, "must_have")
    await _add_posting_skill(db, other, "writing", 2, "nice_to_have")

    axes = [
        ({"source": source.key}, 2),
        ({"seniority": "senior"}, 1),
        ({"remote_policy": "remote"}, 1),
        ({"employment_type": "full_time"}, 1),
        ({"contract": "permanent"}, 1),
        ({"education_min": "bachelor"}, 1),
        ({"city": "Athens"}, 1),
        ({"country": "Greece"}, 1),
        ({"org": "Parity Acme"}, 1),
        ({"mapped_family": "parity-family"}, 1),
        ({"salary_min": 50_000}, 1),
        ({"skills": "programming"}, 1),
        ({"skills": "programming,writing", "skill_mode": "any"}, 2),
        ({"skills": "programming,writing", "skill_mode": "all"}, 0),
        ({"q": "Parity Match"}, 1),
    ]
    for axis, expected in axes:
        body = (
            await _dashboard(client, auth_headers, window="30d", cards="overview", **axis)
        ).json()
        listing = await _explore_total(client, auth_headers, posted_within="30d", **axis)
        assert body["overview"]["new_in_range"]["count"] == listing == expected, axis


async def test_breakdown_counts_match_the_explore_total_on_every_axis(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """The parity pin names its card/total: `breakdown(dimension=X)` rows
    sum to the Explore total under the same compiled filter, on both
    status bases."""
    await _make_posting(
        db, source, external_id="pin-a", title="Pin A", seniority="senior", onsite_policy="remote"
    )
    await _make_posting(
        db, source, external_id="pin-b", title="Pin B", seniority="junior", onsite_policy="remote"
    )
    expired = await _make_posting(
        db, source, external_id="pin-c", title="Pin C", seniority="senior", onsite_policy="hybrid"
    )
    expired.status = "expired"
    await db.commit()

    for basis in ("open", "all"):
        for dimension, axis, value in (
            ("seniority", "seniority", "senior"),
            ("work_mode", "remote_policy", "remote"),
            ("source", "source", source.key),
        ):
            body = (
                await _dashboard(
                    client,
                    auth_headers,
                    window="30d",
                    basis=basis,
                    dimension=dimension,
                    cards="breakdown",
                )
            ).json()
            rows = {row["key"]: row["count"] for row in body["breakdown"]["rows"]}
            expected = await _explore_total(
                client, auth_headers, posted_within="30d", basis=basis, **{axis: value}
            )
            assert rows.get(value, 0) == expected, (basis, dimension)


async def test_explore_basis_all_includes_expired_but_not_hidden(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    expired = await _make_posting(db, source, external_id="basis-expired", title="Expired Role")
    expired.status = "expired"
    hidden = await _make_posting(db, source, external_id="basis-hidden", title="Hidden Status")
    hidden.status = "hidden"
    await db.commit()

    open_total = await _explore_total(client, auth_headers, posted_within="30d")
    all_total = await _explore_total(client, auth_headers, posted_within="30d", basis="all")
    assert open_total == 0
    assert all_total == 1
