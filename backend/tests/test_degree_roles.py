"""Plan 212 S3.3 — deterministic discipline -> family suggestions."""

from app.services.profile.discipline_service import MAX_EXPANDED, degree_matches
from tests.conftest import _uid, register_user


async def _education(client, auth_headers, *, program: str, subjects: list[str] | None = None):
    response = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "Sample University",
            "program": program,
            "level": "bachelor",
            "start": "2022-09-01",
            "in_progress": True,
            "focus_subjects": subjects or [],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text


async def test_degree_matches_program_and_subjects(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    await _education(client, auth_headers, program="BSc Computer Science", subjects=["statistics"])
    matches = await degree_matches(db, _uid(auth_headers))
    keys = [match.family_key for match in matches]
    assert "technology-software" in keys
    assert "technology-data" in keys
    assert "technology" in keys
    assert len(keys) == len(set(keys))
    assert len(keys) <= MAX_EXPANDED
    software = next(match for match in matches if match.family_key == "technology-software")
    assert "computer science" in software.matched_terms
    assert software.reason == "matched"
    parent = next(match for match in matches if match.family_key == "technology")
    assert parent.depth == 1
    assert parent.reason == "parent"
    assert any(match.reason == "family_expansion" for match in matches)


async def test_degree_matching_is_case_whitespace_and_language_tolerant(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    await _education(
        client,
        auth_headers,
        program="  BSc   COMPUTER-SCIENCE ",
        subjects=["  Datenanalyse  ", "Informatik", "Πληροφορική"],
    )
    keys = {match.family_key for match in await degree_matches(db, _uid(auth_headers))}
    assert "technology-software" in keys
    assert "technology-data" in keys


async def test_plural_underscore_and_greek_aliases_are_tolerated(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    await _education(
        client,
        auth_headers,
        program="Bachelor of Laws",
        subjects=["Computer_Sciences", "Βιολογία", "Μηχανική"],
    )
    keys = {match.family_key for match in await degree_matches(db, _uid(auth_headers))}
    assert "public-safety" in keys
    assert "technology-software" in keys
    assert "science" in keys
    assert "engineering-civil" in keys
    assert "engineering-mechanical" in keys


async def test_generic_engineering_uses_the_parent_fallback_and_children(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    for program in ("BSc Engineering", "MSc Engineering Management"):
        await _education(client, auth_headers, program=program)
        keys = {match.family_key for match in await degree_matches(db, _uid(auth_headers))}
        assert "engineering" in keys
        assert "engineering-civil" in keys
        assert "engineering-mechanical" in keys


async def test_specific_engineering_does_not_match_the_other_leaves_as_direct(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    await _education(client, auth_headers, program="BSc Software Engineering")
    matches = await degree_matches(db, _uid(auth_headers))
    direct = {match.family_key for match in matches if match.reason == "matched"}
    assert "technology-software" in direct
    assert "engineering-civil" not in direct
    assert "engineering-mechanical" not in direct
    assert "engineering" not in direct


async def test_generic_degree_names_and_unknown_disciplines_do_not_match(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    await _education(client, auth_headers, program="Bachelor of Arts in Comparative Literature")
    assert await degree_matches(db, _uid(auth_headers)) == []


async def test_degree_matches_are_scoped_to_the_owner(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    other_headers = await register_user(client, "degree-other@example.com")
    await _education(client, other_headers, program="BSc Computer Science")
    assert await degree_matches(db, _uid(auth_headers)) == []


async def test_degree_roles_api_and_empty_state(
    client, auth_headers, profile_ready, seeded_catalog
):
    response = await client.get("/api/v1/profile/degree-roles", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["matches"] == []

    await _education(client, auth_headers, program="LLB Law")
    response = await client.get("/api/v1/profile/degree-roles", headers=auth_headers)
    body = response.json()
    assert any(row["family_key"] == "public-safety" for row in body["matches"])
    assert all(
        row["reason"] in {"matched", "parent", "family_expansion"} for row in body["matches"]
    )
    assert all("rationale" not in row for row in body["matches"])
