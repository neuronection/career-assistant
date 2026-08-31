"""Phase 22: deterministic fit engine — formulas, fairness, weights, staleness."""

from app.services.fit.dimensions import (
    FIT_VERSION,
    compute_fit,
    education_dimension,
    evidence_years_from_experience,
    experience_dimension,
    interests_dimension,
    location_dimension,
    skills_dimension,
)

SKILL_LINKS = [
    {"skill_id": "s1", "required_level": 8, "importance": "core"},
    {"skill_id": "s2", "required_level": 4, "importance": "important"},
    {"skill_id": "s3", "required_level": 6, "importance": "bonus"},
]


def test_skills_surplus_never_inflates_and_weight_redistributes():
    # user exceeds every requirement — capped at full coverage, not extra
    full = skills_dimension(SKILL_LINKS, {"s1": 10, "s2": 9, "s3": 10})
    exact = skills_dimension(SKILL_LINKS, {"s1": 8, "s2": 4, "s3": 6})
    assert full[0] == exact[0] == 10.0

    # unknown skill redistributes its weight to the known ones (no blanket zero)
    partial = skills_dimension(SKILL_LINKS, {"s2": 4})
    assert 0 < partial[0] < 10

    # unmet core skill caps the dimension
    capped = skills_dimension(SKILL_LINKS, {"s2": 4, "s3": 6})
    assert capped[0] <= 4.0

    # no claimed skills at all ⇒ neutral, not zero
    neutral = skills_dimension(SKILL_LINKS, {})
    assert neutral[0] == 7.0


def test_education_in_progress_counts():
    assert education_dimension("bachelor", "bachelor")[0] == 10.0
    assert education_dimension("bachelor", "master")[0] == 10.0
    # one level short is the expected student state
    assert education_dimension("master", "bachelor")[0] == 6.0
    # two levels short (the typical school-leaver vs bachelor gap)
    assert education_dimension("bachelor", "high_school")[0] == 3.0
    assert education_dimension("doctorate", "high_school")[0] < 3.0
    assert education_dimension(None, None)[0] == 10.0  # no requirement


def test_experience_never_zero_for_missing_signal():
    band = (1, 3)
    # no band or no evidence ⇒ neutral 7 with a "no signal" detail
    assert experience_dimension(None, 0.0, 0)[0] == 7.0
    no_evidence = experience_dimension(band, 0.0, 0)
    assert no_evidence[0] == 7.0 and "no experience" in no_evidence[1]
    # partial evidence scales between 4 and 10
    partial = experience_dimension(band, 0.5, 1)
    assert 4.0 < partial[0] < 10.0
    assert experience_dimension(band, 1.5, 2)[0] == 10.0


def test_evidence_years_kind_weighted_and_fractional_projects():
    years, instances = evidence_years_from_experience(
        [
            {
                "title": "P",
                "kind": "project",
                "start_year": 2024,
                "end_year": 2026,
                "skill_keys": ["programming"],
            },
            {
                "title": "I",
                "kind": "internship",
                "start_year": 2025,
                "end_year": 2026,
                "hours_per_week": 20,
            },
        ]
    )
    assert instances == 2
    # project: 2y × 0.4 × 1.0 ; internship: 1y × 0.75 × (20/40)
    assert years == round(2 * 0.4 + 1 * 0.75 * 0.5, 2)


def test_location_remote_and_relocation():
    ok = location_dimension(
        job_city=None,
        job_country=None,
        job_remote=True,
        user_city="Athens",
        user_country="GR",
        remote_ok=True,
        willing_to_relocate=False,
    )
    misaligned = location_dimension(
        job_city=None,
        job_country=None,
        job_remote=True,
        user_city="Athens",
        user_country="GR",
        remote_ok=False,
        willing_to_relocate=False,
    )
    assert ok[0] == 10.0 and misaligned[0] == 4.0
    unknown = location_dimension(
        job_city=None,
        job_country=None,
        job_remote=False,
        user_city="Athens",
        user_country="GR",
        remote_ok=True,
        willing_to_relocate=False,
    )
    assert unknown[0] == 7.0 and unknown[2] is False  # no signal → weight moves
    relocating = location_dimension(
        job_city="Berlin",
        job_country="DE",
        job_remote=False,
        user_city="Athens",
        user_country="GR",
        remote_ok=False,
        willing_to_relocate=True,
    )
    assert relocating[0] == 8.0


def test_interests_overlap_plus_workstyle():
    score, _detail, signalled = interests_dimension(
        job_interest_ids={"a", "b", "c", "d"},
        user_interest_ids={"a", "b"},
        user_work_style=None,
        job_work_style=None,
    )
    assert signalled and score == 5.0  # 2/4 overlap, no style signal
    both = interests_dimension(
        job_interest_ids={"a"},
        user_interest_ids={"a"},
        user_work_style={
            k: 3 for k in ("teamwork", "environment", "structure", "pace", "leadership")
        },
        job_work_style={
            k: 3 for k in ("teamwork", "environment", "structure", "pace", "leadership")
        },
    )
    assert both[0] == 10.0


def test_compute_fit_neutral_dimensions_redistribute_weights():
    job = {
        "skill_links": SKILL_LINKS,
        "education_level": "bachelor",
        "experience_band": None,
        "job_remote": False,
        "interest_ids": {"i1"},
        "user": None,
    }
    result = compute_fit(
        job=job,
        user={
            "skill_levels": {"s1": 8, "s2": 4, "s3": 6},
            "education_level": "high_school",
            "interest_ids": {"i1"},
            "work_style": {
                k: 3
                for k in ("teamwork", "environment", "structure", "pace", "leadership")
            },
        },
        weights={
            "skills": 5,
            "location": 5,
            "experience": 1,
            "education": 1,
            "interests": 1,
        },
    )
    assert 0 <= result.score <= 10
    # experience/location carried no signal: their weight must not dilute
    dims = result.breakdown
    assert dims["experience"]["score"] == 7.0
    assert "weight" in dims["experience"]


def test_fairness_niche_beats_popular_on_fit_alone():
    """A niche job with perfect skill fit must outrank a mediocre popular one.

    Fit contains no popularity/family-size/demand term, so identical
    dimension values produce identical scores regardless of the catalog.
    """

    def make_job(skills, demand_outlook):
        return {
            "skill_links": skills,
            "education_level": "bachelor",
            "experience_band": None,
            "job_remote": False,
            "interest_ids": set(),
            "demand_outlook": demand_outlook,
        }

    user = {
        "skill_levels": {"s1": 8, "s2": 4},
        "education_level": "high_school",
        "interest_ids": set(),
    }
    niche = make_job(
        [{"skill_id": "s1", "required_level": 8, "importance": "core"}], "stable"
    )
    popular = make_job(
        [{"skill_id": "s9", "required_level": 9, "importance": "core"}], "hot"
    )
    weights = {
        "skills": 5,
        "location": 1,
        "experience": 1,
        "education": 1,
        "interests": 1,
    }
    niche_fit = compute_fit(job=niche, user=user, weights=weights)
    popular_fit = compute_fit(job=popular, user=user, weights=weights)
    assert niche_fit.score > popular_fit.score
    # demand played no role: swapping outlooks changes nothing
    popular_swapped = compute_fit(
        job=make_job(
            [{"skill_id": "s9", "required_level": 9, "importance": "core"}],
            "declining",
        ),
        user=user,
        weights=weights,
    )
    assert popular_swapped.score == popular_fit.score


def test_specialist_highlight_detection():
    job = {
        "skill_links": [{"skill_id": "s1", "required_level": 9, "importance": "core"}],
        "education_level": "doctorate",
        "experience_band": (8, 10),
        "job_remote": False,
        "interest_ids": {"x"},
        "physical_requirements": [],
    }
    user = {
        "skill_levels": {"s1": 10},
        "education_level": "high_school",
        "experience_years": 0,
        "experience_instances": 0,
        "interest_ids": set(),
        "max_education_years": None,
        "physical_conditions": [],
    }
    result = compute_fit(job=job, user=user, weights=None)
    assert result.score < 6.0
    assert result.specialist_dimension == "skills"


def test_fit_version_is_bumpable_constant():
    assert isinstance(FIT_VERSION, int) and FIT_VERSION >= 1
