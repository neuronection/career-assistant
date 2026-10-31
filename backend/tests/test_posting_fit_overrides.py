"""Plan 169 — goal-adjusted fit: FitOverrides neutralize disabled profile
inputs (neutral-7 + ``disabled`` markers), the prereqs parts merge by
min-cap over participating parts only (a disabled part never contributes
a penalty), goal-adjusted values are derived rescores over the canonical
cache (never written, estimates untouched), and the goal-adjusted score
drives window selection, the sweep seam, findings and the curator
payload."""

import json
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.posting_model import JobPosting, PostingFit
from app.models.user_model import UserSkill
from app.schemas.autopilot import ProfileUsage
from app.services.postings.posting_fit_service import (
    FitOverrides,
    _load_context,
    compute_posting_fit,
    get_posting_fits_batch,
)
from tests.conftest import _make_posting, _uid


async def _extracted(db, source, external_id: str, extract_overrides: dict | None = None):
    from app.ai.agents.posting_extractor import (
        ExtractPrerequisite,
        ExtractSkill,
        PostingExtract,
    )
    from app.services.postings.extract_service import apply_extract

    payload = {
        "title_norm": "Data Analyst",
        "seniority": "junior",
        "education": {"level": "bachelor"},
        "languages": ["de"],
        "prerequisites": [
            ExtractPrerequisite(
                kind="certificate",
                label="PMP certificate",
                evidence_quote="PMP certification required",
                confidence=0.95,
            )
        ],
        "skills": [
            ExtractSkill(
                skill_key="programming",
                required_level=8,
                priority="must_have",
                evidence_quote="strong programming required",
                confidence=0.95,
            )
        ],
        "field_confidence": {},
    }
    payload.update(extract_overrides or {})
    posting = await _make_posting(db, source, external_id=external_id, title="Data Analyst")
    await apply_extract(db, posting, PostingExtract(**payload))
    await db.commit()
    await db.refresh(posting)
    return posting


async def _give_skill(db, user_id, key: str, level: int) -> None:
    from app.models.taxonomy_model import Skill

    skill = (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
    assert skill is not None, f"seeded skill missing: {key}"
    db.add(UserSkill(user_id=user_id, skill_id=skill.id, level=level, source="self_report"))
    await db.commit()


def _user_id(auth_headers) -> uuid_mod.UUID:
    return uuid_mod.UUID(_uid(auth_headers))


FLAG_COMBOS = [
    {},
    {"use_skills": False},
    {"use_education": False},
    {"use_languages": False},
    {"use_location": False},
    {"use_experience": False},
    {"use_lifestyle": False},
    {"use_skills": False, "use_education": False, "use_lifestyle": False},
    {"stage_source": "goal"},
]


@pytest.fixture
def frozen_now(monkeypatch):
    now = datetime.now(UTC)

    def _frozen():
        return now

    monkeypatch.setattr("app.services.postings.posting_fit_service._utcnow", _frozen)
    return now


# ------------------------------------------------------------ per-toggle


async def test_each_toggle_neutralizes_exactly_its_part(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, frozen_now
):
    user_id = _user_id(auth_headers)
    await _give_skill(db, user_id, "programming", 2)
    posting = await _extracted(db, source, "ovr-per-toggle")
    context = await _load_context(db, user_id)

    cases = [
        (FitOverrides(use_skills=False), "skills"),
        (FitOverrides(use_location=False), "location_remote"),
        (FitOverrides(use_experience=False), "seniority_stage"),
    ]
    for overrides, dim in cases:
        result = await compute_posting_fit(
            db, user_id, posting, context=context, overrides=overrides
        )
        entry = result["breakdown"][dim]
        assert entry["score"] == 7.0 and entry.get("neutral") and entry.get("disabled"), (
            f"{dim} must read neutral-7 disabled"
        )
        others = [key for key in result["breakdown"] if key != dim]
        assert all("disabled" not in result["breakdown"][key] for key in others), (
            f"{dim} flag must not leak into other dimensions"
        )

    result = await compute_posting_fit(
        db, user_id, posting, context=context, overrides=FitOverrides(use_lifestyle=False)
    )
    assert result["gates"] == []
    assert all("disabled" not in entry for entry in result["breakdown"].values()), (
        "lifestyle gates are not a dimension — no disabled marker"
    )

    result = await compute_posting_fit(
        db, user_id, posting, context=context, overrides=FitOverrides(use_languages=False)
    )
    parts = result["breakdown"]["prereqs"]["parts"]
    assert parts["languages"].get("disabled") is True
    assert parts["education"].get("disabled") is not True
    assert parts["certificates"].get("disabled") is not True

    result = await compute_posting_fit(
        db, user_id, posting, context=context, overrides=FitOverrides(use_education=False)
    )
    parts = result["breakdown"]["prereqs"]["parts"]
    assert parts["education"].get("disabled") is True
    assert parts["certificates"].get("disabled") is True, "certificates ride use_education"
    assert parts["languages"].get("disabled") is not True


async def test_skills_disabled_scores_neutral_not_the_must_have_cap(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _user_id(auth_headers)
    await _give_skill(db, user_id, "programming", 2)
    posting = await _extracted(db, source, "ovr-skills-neutral")
    canonical = await compute_posting_fit(db, user_id, posting)
    assert canonical["breakdown"]["skills"]["score"] < 4.0, "unmet must-have drags the dim"
    adjusted = await compute_posting_fit(
        db, user_id, posting, overrides=FitOverrides(use_skills=False)
    )
    entry = adjusted["breakdown"]["skills"]
    assert entry["score"] == 7.0 and entry.get("neutral") and entry.get("disabled")


# ------------------------------------------------------- prereqs parts


async def test_disabled_prereq_part_never_contributes_a_penalty(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, frozen_now
):
    user_id = _user_id(auth_headers)
    posting = await _extracted(db, source, "ovr-prereqs-rise")
    context = await _load_context(db, user_id)
    canonical = await compute_posting_fit(db, user_id, posting, context=context)
    merged = canonical["breakdown"]["prereqs"]
    assert merged["score"] == 3.0, "education below requirement is the strongest penalty"
    assert merged["parts"]["education"]["score"] == 3.0
    assert merged["parts"]["languages"]["score"] == 5.0
    assert merged["parts"]["certificates"]["score"] == 6.0

    for combo in FLAG_COMBOS:
        overrides = FitOverrides.from_profile_usage(ProfileUsage(**combo), ["junior"])
        result = await compute_posting_fit(
            db, user_id, posting, context=context, overrides=overrides
        )
        adjusted = result["breakdown"]["prereqs"]
        assert adjusted["score"] >= merged["score"], (
            f"{combo}: the merged prereqs score can only rise or stay"
        )
        if not any(
            part.get("signal") and not part.get("disabled") for part in adjusted["parts"].values()
        ):
            assert adjusted.get("neutral") and adjusted["score"] == 7.0

    result = await compute_posting_fit(
        db,
        user_id,
        posting,
        context=context,
        overrides=FitOverrides(use_education=False, use_languages=False),
    )
    adjusted = result["breakdown"]["prereqs"]
    assert adjusted["score"] == 7.0 and adjusted.get("neutral"), (
        "all participating parts disabled → neutral 7.0"
    )
    assert adjusted["parts"]["education"]["disabled"] is True
    assert adjusted["parts"]["certificates"]["disabled"] is True
    assert adjusted["parts"]["languages"]["disabled"] is True


async def test_prereqs_scored_gate_preserved(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, frozen_now
):
    user_id = _user_id(auth_headers)
    posting = await _extracted(
        db,
        source,
        "ovr-scored-gate",
        extract_overrides={"languages": [], "prerequisites": []},
    )
    from app.models.user_model import Profile

    profile = (await db.execute(select(Profile))).scalars().first()
    profile.basics = {k: v for k, v in (profile.basics or {}).items() if k != "education_level"}
    await db.commit()

    context = await _load_context(db, user_id)
    canonical = await compute_posting_fit(db, user_id, posting, context=context)
    entry = canonical["breakdown"]["prereqs"]
    assert entry["score"] == 7.0 and entry.get("neutral"), (
        "education requirement with an unspecified level stays the scored-gate neutral"
    )
    adjusted = await compute_posting_fit(
        db, user_id, posting, context=context, overrides=FitOverrides(use_education=False)
    )
    assert adjusted["breakdown"]["prereqs"]["score"] == 7.0
    assert adjusted["breakdown"]["prereqs"].get("neutral") is True

    posting_languages = await _extracted(
        db,
        source,
        "ovr-scored-gate-lang",
        extract_overrides={"prerequisites": []},
    )
    adjusted = await compute_posting_fit(
        db,
        user_id,
        posting_languages,
        context=context,
        overrides=FitOverrides(use_education=False),
    )
    entry = adjusted["breakdown"]["prereqs"]
    assert entry["score"] == 5.0 and not entry.get("neutral"), (
        "a participating language penalty keeps the dimension non-neutral"
    )


async def test_merges_unchanged_when_all_parts_on(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, frozen_now
):
    user_id = _user_id(auth_headers)
    await _give_skill(db, user_id, "programming", 2)
    posting = await _extracted(db, source, "ovr-all-on")
    context = await _load_context(db, user_id)
    inactive = await compute_posting_fit(db, user_id, posting, context=context)
    active_all_on = await compute_posting_fit(
        db, user_id, posting, context=context, overrides=FitOverrides()
    )
    assert inactive == active_all_on, "an all-on override block reproduces today's values"
    entry = active_all_on["breakdown"]["prereqs"]
    assert entry["score"] == 3.0
    assert entry["parts"]["education"]["score"] == 3.0
    assert entry["parts"]["languages"]["score"] == 5.0
    assert entry["parts"]["certificates"]["score"] == 6.0
    assert all("disabled" not in part for part in entry["parts"].values())


# ------------------------------------------------------------- stage swap


async def test_stage_source_goal_swaps_the_stage_value(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _user_id(auth_headers)
    posting = await _extracted(db, source, "ovr-stage-goal")
    context = await _load_context(db, user_id)
    canonical = await compute_posting_fit(db, user_id, posting, context=context)
    assert canonical["breakdown"]["seniority_stage"]["detail"] == "junior role for a student"

    overrides = FitOverrides.from_profile_usage(
        ProfileUsage(stage_source="goal"), ["senior", "intern"]
    )
    assert overrides.stage is not None and overrides.stage.value == "experienced", (
        "the max seniority rank decides"
    )
    result = await compute_posting_fit(db, user_id, posting, context=context, overrides=overrides)
    entry = result["breakdown"]["seniority_stage"]
    assert entry["detail"] == "junior role for a experienced"
    assert entry["score"] == 4.0

    gated = FitOverrides.from_profile_usage(
        ProfileUsage(stage_source="goal", use_experience=False), ["senior"]
    )
    result = await compute_posting_fit(db, user_id, posting, context=context, overrides=gated)
    entry = result["breakdown"]["seniority_stage"]
    assert entry.get("disabled") is True, "a disabled use_experience wins over stage_source"


async def test_switching_and_returning_unchanged_under_profile_source(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from app.services.postings.posting_fit_service import _seniority_stage_dimension

    posting = await _extracted(db, source, "ovr-stage-profile")
    for stage_value in ("switching", "returning", "early_career"):
        baseline = _seniority_stage_dimension(posting, stage_value)
        overrides = FitOverrides.from_profile_usage(ProfileUsage(), [])
        assert overrides.stage is None, "profile source never swaps the stage"
        assert overrides.active is False
        assert _seniority_stage_dimension(posting, stage_value) == baseline


# ------------------------------------------------------------ cache rule


async def test_inputs_hash_is_toggle_invariant(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, frozen_now
):
    user_id = _user_id(auth_headers)
    await _give_skill(db, user_id, "programming", 2)
    posting = await _extracted(db, source, "ovr-hash")
    context = await _load_context(db, user_id)
    canonical = await compute_posting_fit(db, user_id, posting, context=context)
    for combo in FLAG_COMBOS:
        overrides = FitOverrides.from_profile_usage(ProfileUsage(**combo), ["junior"])
        result = await compute_posting_fit(
            db, user_id, posting, context=context, overrides=overrides
        )
        assert result["inputs_hash"] == canonical["inputs_hash"], f"{combo} rides the hash"


async def test_rescore_property_matches_fresh_compute(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, frozen_now
):
    user_id = _user_id(auth_headers)
    await _give_skill(db, user_id, "programming", 2)
    posting = await _extracted(db, source, "ovr-property")
    context = await _load_context(db, user_id)
    await get_posting_fits_batch(db, user_id, [posting], refresh=True)

    for combo in FLAG_COMBOS:
        overrides = FitOverrides.from_profile_usage(ProfileUsage(**combo), ["senior"])
        fresh = await compute_posting_fit(
            db, user_id, posting, context=context, overrides=overrides
        )
        batched = (await get_posting_fits_batch(db, user_id, [posting], fit_overrides=overrides))[
            posting.id
        ]
        assert batched["score"] == fresh["score"], f"{combo}: blended score must match"
        for dim, entry in fresh["breakdown"].items():
            other = batched["breakdown"][dim]
            assert other["score"] == entry["score"], f"{combo}/{dim}"
            assert bool(other.get("neutral")) == bool(entry.get("neutral")), f"{combo}/{dim}"
            assert bool(other.get("disabled")) == bool(entry.get("disabled")), f"{combo}/{dim}"
        assert batched["gates"] == fresh["gates"], f"{combo}: gates must match"
        assert batched["inputs_hash"] == fresh["inputs_hash"]


async def test_miss_path_writes_canonical_not_adjusted(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _user_id(auth_headers)
    await _give_skill(db, user_id, "programming", 2)
    posting = await _extracted(db, source, "ovr-miss-path")
    result_posting_id = posting.id
    canonical = await compute_posting_fit(db, user_id, posting)
    overrides = FitOverrides(use_skills=False)

    result = (await get_posting_fits_batch(db, user_id, [posting], fit_overrides=overrides))[
        posting.id
    ]
    assert result["score"] > canonical["score"], "the result carries the adjusted rescore"
    assert result["breakdown"]["skills"].get("disabled") is True

    db.expire_all()
    row = (await db.execute(select(PostingFit))).scalars().first()
    assert float(row.score) == canonical["score"], "the cache row stays canonical"
    assert row.breakdown["skills"].get("disabled") is not True
    assert row.inputs_hash == canonical["inputs_hash"]

    posting_id = result_posting_id
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalars().first()
    )
    hit = await get_posting_fits_batch(db, user_id, [posting], fit_overrides=overrides)
    assert hit[posting_id]["score"] == result["score"], "a canonical hit rescores too"


async def test_estimate_rows_are_never_rescored(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _user_id(auth_headers)
    posting = await _make_posting(db, source, external_id="ovr-estimate", title="Estimate only")
    assert posting.extract_version is None
    canonical = await compute_posting_fit(db, user_id, posting)
    assert canonical["estimate"] is True

    for overrides in (
        FitOverrides(use_skills=False),
        FitOverrides.from_profile_usage(ProfileUsage(stage_source="goal"), ["principal"]),
    ):
        result = (await get_posting_fits_batch(db, user_id, [posting], fit_overrides=overrides))[
            posting.id
        ]
        assert result["score"] == canonical["score"], "estimates ignore the toggles"
        assert result["estimate"] is True
        assert "disabled" not in json.dumps(result["breakdown"])
        fresh = await compute_posting_fit(db, user_id, posting, overrides=overrides)
        assert fresh["score"] == canonical["score"]


# ------------------------------------------------- goal-adjusted call sites


async def test_window_selection_honors_the_toggles(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    await _give_skill(db, auth_headers and _user_id(auth_headers), "programming", 2)
    a = await _extracted(
        db,
        source,
        "ovr-window-a",
        extract_overrides={
            "languages": [],
            "prerequisites": [],
            "education": {"level": "high_school"},
        },
    )  # unmet must-have skill, fresher posting
    b = await _extracted(
        db,
        source,
        "ovr-window-b",
        extract_overrides={
            "languages": [],
            "prerequisites": [],
            "skills": [],
            "education": {"level": "high_school"},
        },
    )
    b.posted_at = datetime.now(UTC) - timedelta(days=6)
    await db.commit()

    filters: dict = {}
    canonical = await get_posting_fits_batch(db, _user_id(auth_headers), [a, b])
    assert canonical[b.id]["score"] > canonical[a.id]["score"], (
        "canonically the complete candidate outranks the skill-gap one"
    )
    page = await _explore_first(db, _user_id(auth_headers), filters)
    assert page == b.id

    overrides = FitOverrides(use_skills=False)
    adjusted = await get_posting_fits_batch(
        db, _user_id(auth_headers), [a, b], fit_overrides=overrides
    )
    assert adjusted[a.id]["score"] > adjusted[b.id]["score"], (
        "with skills off the canonically-low candidate rises to the top"
    )
    page = await _explore_first(db, _user_id(auth_headers), filters, fit_overrides=overrides)
    assert page == a.id, "the fit window selection itself honors the toggles"


async def _explore_first(db, user_id, filters, *, fit_overrides=None) -> uuid_mod.UUID:
    from app.services.postings.explore_service import explore

    result = await explore(
        db,
        user_id,
        filters,
        sort="fit",
        limit=1,
        with_facets=False,
        fit_overrides=fit_overrides,
    )
    return result["items"][0]["posting"].id


async def test_scored_candidates_seam_carries_adjusted_fit(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from app.ai.graphs.autopilot import AutopilotState, GraphDeps, _scored_candidates

    user_id = _user_id(auth_headers)
    await _give_skill(db, user_id, "programming", 2)
    posting = await _extracted(db, source, "ovr-sweep-seam")
    canonical = await compute_posting_fit(db, user_id, posting)
    state = AutopilotState(user_id=str(user_id), constraints={})
    rows = [(posting, None, None)]

    plain_deps = GraphDeps(db=db)
    plain = await _scored_candidates(plain_deps, state, rows)
    assert len(plain) == 1
    assert plain[0]["fit"] == canonical["score"]
    assert plain[0]["breakdown"]["skills"].get("disabled") is not True

    adjusted_deps = GraphDeps(db=db, fit_overrides=FitOverrides(use_skills=False))
    adjusted = await _scored_candidates(adjusted_deps, state, rows)
    assert len(adjusted) == 1
    assert adjusted[0]["fit"] != plain[0]["fit"], "the seam scores with the goal overrides"
    assert adjusted[0]["breakdown"]["skills"].get("disabled") is True, (
        "disabled markers ride into the evidence"
    )


async def test_curator_payload_carries_disabled_markers(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from app.ai.graphs.autopilot import AutopilotState, _curate_user_prompt

    state = AutopilotState(user_id="u", constraints={}, goal_text="data work")
    pool = [
        {
            "posting_id": "p1",
            "title": "Data Analyst",
            "org": "ExtractCo",
            "fit": 7.1,
            "breakdown": {
                "skills": {
                    "score": 7.0,
                    "detail": "skills disabled for this goal",
                    "neutral": True,
                    "disabled": True,
                    "weight": 3,
                }
            },
            "skills": [],
            "responsibilities": [],
            "snippet": "We need programming.",
        }
    ]
    payload = json.loads(_curate_user_prompt(state, pool))
    entry = payload["candidates"][0]["fit_breakdown"]["skills"]
    assert entry["disabled"] is True and entry["score"] == 7.0
