"""Read-tool parity (plan 119.1): saved searches, market trend and one
fit breakdown answer from their services, and an empty result is stated
honestly — never a hallucinated summary.

All three are registry `read` tools, so the MCP surface projects them
without a second tool list (asserted here as the registry contract).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.ai.tools import list_tools, run_tool
from app.models.market_model import MarketSnapshot
from app.services.postings.engagement_service import EngagementService
from tests.conftest import _uid


async def _saved_search(db, user_id, *, query: str, saved: bool) -> UUID:
    from app.models.enums import SearchScope

    record = await EngagementService(db).record_search(
        user_id,
        SearchScope.POSTINGS,
        query,
        {"remote": True},
        7,
    )
    if saved:
        await EngagementService(db).save_search(user_id, record.id)
    return record.id


async def test_my_saved_searches_returns_only_saved_rows(client, auth_headers, db):
    user_id = UUID(_uid(auth_headers))
    saved_id = await _saved_search(db, user_id, query="backend", saved=True)
    await _saved_search(db, user_id, query="design", saved=False)

    result = await run_tool(db, "my_saved_searches", user_id, {})
    assert [row["search_id"] for row in result["searches"]] == [str(saved_id)]
    row = result["searches"][0]
    assert row["scope"] == "postings"
    assert row["query"] == "backend"
    assert row["filters"] == {"remote": True}
    assert row["result_count"] == 7


async def test_my_saved_searches_empty_state_is_honest(client, auth_headers, db):
    result = await run_tool(db, "my_saved_searches", UUID(_uid(auth_headers)), {})
    assert result["searches"] == []
    assert "Nothing tracked yet" in result["note"]
    assert "Save search" in result["note"]


async def test_market_trend_requires_exactly_one_scope(client, auth_headers, db):
    user_id = UUID(_uid(auth_headers))
    both = await run_tool(
        db, "market_trend", user_id, {"family_key": "technology", "job_ref": "software-engineer"}
    )
    neither = await run_tool(db, "market_trend", user_id, {})
    assert "exactly one" in both["error"]
    assert "exactly one" in neither["error"]


async def test_market_trend_reads_persisted_history(client, auth_headers, db):
    user_id = UUID(_uid(auth_headers))
    today = datetime.now(UTC).date()
    for offset, sample in ((2, 12), (1, 18), (0, 4)):
        db.add(
            MarketSnapshot(
                scope_kind="family",
                scope_key="family:technology",
                family_key="technology",
                capture_date=today - timedelta(days=offset),
                captured_at=datetime.now(UTC) - timedelta(days=offset),
                sample_size=sample,
                thin_sample=sample < 10,
                payload={
                    "sample_size": sample,
                    "thin_sample": sample < 10,
                    "salary_band": None if sample < 10 else {"p25": 3000, "p75": 5000},
                    "months": [
                        {
                            "month": (today - timedelta(days=offset)).strftime("%Y-%m"),
                            "postings": sample,
                        }
                    ],
                },
            )
        )
    await db.commit()

    result = await run_tool(db, "market_trend", user_id, {"family_key": "technology"})
    assert result["scope"] == {"kind": "family", "key": "technology"}
    assert [row["sample_size"] for row in result["trend"]] == [12, 18, 4]
    assert result["trend"][-1]["thin_sample"] is True
    assert "thin_sample" in result["note"]


async def test_market_trend_empty_history_is_honest(client, auth_headers, db):
    result = await run_tool(db, "market_trend", UUID(_uid(auth_headers)), {"family_key": "nope"})
    assert result["trend"] == []
    assert "No demand history" in result["note"]


async def test_my_fit_breakdown_catalog_job(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    from app.services.catalog.job_service import JobService

    jobs, _ = await JobService(db).list_jobs(status="published", page_size=1)
    assert jobs, "seeded catalog must publish at least one job"

    result = await run_tool(
        db, "my_fit_breakdown", UUID(_uid(auth_headers)), {"target": jobs[0].code}
    )
    assert result["target"]["kind"] == "catalog_job"
    assert 0.0 <= result["score"] <= 10.0
    assert result["dimensions"], "the breakdown must carry its dimensions"
    assert all(0.0 <= entry["score"] <= 10.0 for entry in result["dimensions"].values())


async def test_my_fit_breakdown_unknown_target_points_at_the_entry_point(
    client, auth_headers, db, seeded_catalog
):
    result = await run_tool(
        db, "my_fit_breakdown", UUID(_uid(auth_headers)), {"target": "no-such-target"}
    )
    assert "No posting or catalog job matched" in result["error"]
    assert "search_postings" in result["error"]


async def test_my_fit_breakdown_reads_a_mapped_posting(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    from app.services.catalog.job_service import JobService
    from app.services.postings.postings_service import resolve_posting
    from tests.conftest import _make_posting

    jobs, _ = await JobService(db).list_jobs(status="published", page_size=1)
    posting = await _make_posting(db, source, external_id="fit-parity-1")
    posting.catalog_job_id = jobs[0].id
    posting.status = "mapped"
    await db.commit()
    resolved = await resolve_posting(db, posting.ref)
    assert resolved is not None
    result = await run_tool(
        db, "my_fit_breakdown", UUID(_uid(auth_headers)), {"target": posting.ref}
    )
    assert result["target"]["kind"] == "posting"
    assert result["target"]["ref"] == posting.ref
    assert result["dimensions"]


async def test_new_read_tools_are_chat_and_mcp_surface(client, auth_headers, db):
    by_key = {entry["key"]: entry for entry in list_tools()}
    for key in ("my_saved_searches", "market_trend", "my_fit_breakdown"):
        assert by_key[key]["scope"] == "read"
        assert by_key[key]["kind"] == "tool"
        assert "chat" in by_key[key]["audiences"]
