"""Per-CV description overrides never echo their own row head — and
certifications are head-only outright.

The renderer prints title/org as the item heading; a drafted description
restating them ("**ECPE C2 - Proficiency**, **Michigan** — …") reads as a
duplicate record. `apply_overrides` strips the echoed lead deterministically
at the single merge funnel (preview, versions, every export format), and
drops certification description patches entirely — the profile carries no
cert description, so AI text under the heading is fluff by construction.
"""

from app.services.cv_context_service import apply_overrides


def _experience_snapshot() -> tuple[dict, dict]:
    snapshot = {
        "experience": [
            {
                "id": "x1",
                "title": "Backend Intern",
                "org": "Telecom Corp",
                "description": "",
            }
        ]
    }
    return snapshot, {"experience": ["x1"]}


def test_strips_echoed_title_and_org_from_description():
    snapshot, index = _experience_snapshot()
    overrides = {
        "experience:x1": {
            "description": (
                "**Backend Intern**, **Telecom Corp** — built internal "
                "tooling for enterprise telecom operations."
            )
        }
    }
    result = apply_overrides(snapshot, index, overrides)
    assert result["experience"][0]["description"] == (
        "built internal tooling for enterprise telecom operations."
    )


def test_clean_description_passes_through():
    snapshot, index = _experience_snapshot()
    overrides = {
        "experience:x1": {
            "description": "Automated release deployments and batch workflows."
        }
    }
    result = apply_overrides(snapshot, index, overrides)
    assert result["experience"][0]["description"] == (
        "Automated release deployments and batch workflows."
    )


def test_description_that_is_only_the_echo_is_kept():
    snapshot, index = _experience_snapshot()
    overrides = {"experience:x1": {"description": "Backend Intern, Telecom Corp"}}
    result = apply_overrides(snapshot, index, overrides)
    assert result["experience"][0]["description"] == "Backend Intern, Telecom Corp"


def test_education_program_and_institution_echo_stripped():
    snapshot = {
        "education": [
            {
                "id": "e1",
                "program": "MSc Computer Science",
                "institution": "University of Sample",
                "description": "",
            }
        ]
    }
    index = {"education": ["e1"]}
    overrides = {
        "education:e1": {
            "description": (
                "MSc Computer Science, University of Sample — coursework in "
                "distributed systems with a thesis on consensus protocols."
            )
        }
    }
    result = apply_overrides(snapshot, index, overrides)
    assert result["education"][0]["description"] == (
        "coursework in distributed systems with a thesis on consensus protocols."
    )


def test_summary_override_materializes_without_profile_aspirations():
    """A CV whose profile has no aspirations resolves no `summary` scalar;
    typing one in the studio must still produce a renderable summary."""
    result = apply_overrides({}, {}, {"summary:summary": {"summary": "Typed text"}})
    assert result["summary"] == {"summary": "Typed text"}


def test_summary_override_patches_existing_scalar():
    snapshot = {"summary": {"summary": "Profile text"}}
    index = {"summary": ["summary"]}
    result = apply_overrides(
        snapshot, index, {"summary:summary": {"summary": "Edited"}}
    )
    assert result["summary"] == {"summary": "Edited"}


def test_summary_override_ignored_for_mismatched_scalar_id():
    snapshot = {"summary": {"summary": "Profile text"}}
    index = {"summary": ["summary"]}
    result = apply_overrides(snapshot, index, {"summary:other": {"summary": "Nope"}})
    assert result["summary"] == {"summary": "Profile text"}


def test_certification_descriptions_are_head_only():
    snapshot = {
        "certifications": [
            {
                "id": "c1",
                "title": "ECPE C2 - Proficiency",
                "org": "Michigan",
                "start": "2021-05",
                "description": "",
            }
        ]
    }
    index = {"certifications": ["c1"]}
    overrides = {
        "certifications:c1": {
            "description": "*C2 Mastery* certification proving fluent English.",
            "start": "2021-06",
        }
    }
    result = apply_overrides(snapshot, index, overrides)
    assert result["certifications"][0]["description"] == ""
    assert result["certifications"][0]["start"] == "2021-06"
