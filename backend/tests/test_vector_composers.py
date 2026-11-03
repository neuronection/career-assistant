"""Pure composers for the vector store (plan 50 §5, P1c).

Determinism, chunk bounds, empty inputs, the closed view vocabulary and the
``text_ref`` pointers: composers are the contract between a source row and
the records an index worker embeds.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.vector_composers import (
    BODY_CHUNK_CHARS,
    BODY_CHUNK_OVERLAP_CHARS,
    COMPOSER_VERSION,
    TEXT_REF_SCHEMA_VERSION,
    chunk_text,
    compose_job_views,
    compose_posting_views,
    compose_profile_views,
    compose_skill_text,
    compose_skill_views,
)
from app.storage.vector_contract import V1_VIEWS


def _posting(**overrides):
    values = {
        "id": uuid.UUID(int=7),
        "title": "Backend Engineer",
        "org": "ACME",
        "raw": {"description": "Build reliable services for payments."},
        "extract": {
            "skills": [
                {"raw_label": "python", "priority": "must_have", "required_level": 6},
                {"skill_key": "sql", "priority": "nice_to_have", "required_level": 4},
            ],
            "responsibilities": [
                {"text": "Ship the payments API", "time_pct": 60},
                {"text": "Review designs", "optional": True},
            ],
            "prerequisites": [{"kind": "language", "label": "English C1"}],
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_chunk_text_is_bounded_overlapping_and_deterministic():
    text = " ".join(f"word{index}" for index in range(1200))
    chunks = chunk_text(text, size=200, overlap=40)
    assert len(chunks) > 1
    previous = None
    for chunk in chunks:
        assert chunk.char_end > chunk.char_start
        assert chunk.char_end <= len(text)
        assert text[chunk.char_start : chunk.char_end] == chunk.text
        if previous is not None:
            assert chunk.char_start <= previous.char_end, "windows overlap"
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text.rstrip())
    assert chunk_text(text, size=200, overlap=40) == chunks
    assert chunk_text("   \n  ") == []
    assert chunk_text("") == []


def test_chunk_text_rejects_an_impossible_overlap():
    import pytest

    with pytest.raises(ValueError):
        chunk_text("anything", size=10, overlap=10)
    with pytest.raises(ValueError):
        chunk_text("anything", size=0, overlap=0)


def test_posting_views_cover_the_closed_vocabulary():
    composed = compose_posting_views(_posting())
    assert composed.kind == "posting"
    assert composed.composer_version == COMPOSER_VERSION
    assert set(composed.views) == set(V1_VIEWS)
    assert composed.views["summary"].splitlines()[0] == "Backend Engineer"
    assert "ACME" in composed.views["summary"]
    assert "skill: python must_have level 6" in composed.views["requirements"]
    assert "prerequisite: English C1" in composed.views["requirements"]
    assert "responsibility: Ship the payments API (60%)" in composed.views["responsibilities"]
    assert "(optional)" in composed.views["responsibilities"]
    assert "skill: sql nice_to_have level 4" in composed.views["skills"]
    assert composed.views["body"] == "Build reliable services for payments."
    assert {record.view for record in composed.records} == set(V1_VIEWS)


def test_posting_composition_is_deterministic_and_order_independent():
    first = compose_posting_views(_posting())
    second = compose_posting_views(_posting())
    assert first == second
    assert first.source_hash == second.source_hash

    reordered = _posting(
        extract={
            "skills": [
                {"skill_key": "sql", "priority": "nice_to_have", "required_level": 4},
                {"raw_label": "python", "priority": "must_have", "required_level": 6},
            ],
            "responsibilities": _posting().extract["responsibilities"],
            "prerequisites": _posting().extract["prerequisites"],
        }
    )
    assert compose_posting_views(reordered).views == first.views


def test_posting_body_chunks_carry_char_ranges_and_refs():
    body = " ".join(f"paragraph{index}" for index in range(2000))
    composed = compose_posting_views(_posting(raw={"description": body}))
    chunks = [record for record in composed.records if record.view == "body"]
    assert len(chunks) > 1
    assert [record.chunk_index for record in chunks] == list(range(len(chunks)))
    for record in chunks:
        assert record.char_start is not None and record.char_end is not None
        assert body[record.char_start : record.char_end] == record.text
        assert record.text_ref == {
            "table": "job_postings",
            "id": str(uuid.UUID(int=7)),
            "field": "raw.description",
        }
        assert record.text_ref_schema_version == TEXT_REF_SCHEMA_VERSION
    assert len(chunks[0].text) <= BODY_CHUNK_CHARS
    assert BODY_CHUNK_OVERLAP_CHARS < BODY_CHUNK_CHARS


def test_posting_with_no_content_composes_nothing():
    composed = compose_posting_views(_posting(title="", org="", raw={}, extract={}))
    assert composed.records == ()
    assert composed.is_empty
    assert (
        composed.source_hash
        == compose_posting_views(_posting(title="", org="", raw={}, extract={})).source_hash
    )


def test_source_hash_tracks_content_only():
    base = compose_posting_views(_posting())
    changed = compose_posting_views(_posting(title="Staff Engineer"))
    assert base.source_hash != changed.source_hash
    assert base.records[0].content_hash != changed.records[0].content_hash


def test_posting_records_point_at_the_source_never_at_text():
    composed = compose_posting_views(_posting())
    for record in composed.records:
        assert record.text_ref is not None
        assert set(record.text_ref) == {"table", "id", "field"}
        assert "text" not in record.text_ref


def test_profile_views_mirror_the_profile_surface():
    composed = compose_profile_views(
        user_id=str(uuid.UUID(int=9)),
        profiles=[{"education": "BSc Computer Science", "city": "Athens", "country": "Greece"}],
        interests=["Astronomy", "Open source"],
        skills=[{"label": "Python", "level": 7}, {"label": "SQL", "level": 4}],
        experience_titles=["Backend intern"],
    )
    assert composed.kind == "profile"
    assert "interest: Astronomy" in composed.views["summary"]
    assert "location: Athens Greece" in composed.views["summary"]
    assert composed.views["skills"] == "skill: Python level 7\nskill: SQL level 4"
    assert "experience: Backend intern" in composed.views["body"]
    assert "education: BSc Computer Science" in composed.views["body"]
    assert {record.view for record in composed.records} == {"summary", "skills", "body"}
    for record in composed.records:
        assert record.text_ref["table"] == "users"
        assert record.text_ref["id"] == str(uuid.UUID(int=9))


def test_empty_profile_composes_nothing():
    composed = compose_profile_views(
        user_id=None, profiles=[], interests=[], skills=[], experience_titles=[]
    )
    assert composed.is_empty


def test_skill_text_is_stable_across_alias_order():
    first = SimpleNamespace(
        id=uuid.UUID(int=3), key="python", label="Python", aliases=["py", "python3"]
    )
    second = SimpleNamespace(
        id=uuid.UUID(int=3), key="python", label="Python", aliases=["python3", "py"]
    )
    assert compose_skill_text(first) == "python\nPython\npy\npython3"
    assert compose_skill_text(first) == compose_skill_text(second)
    views = compose_skill_views(first)
    assert [record.view for record in views.records] == ["summary"]
    assert views.records[0].text_ref == {
        "table": "skills",
        "id": str(uuid.UUID(int=3)),
        "field": "key+label+aliases",
    }
    assert compose_skill_views(SimpleNamespace(id=None, key="", label="", aliases=[])).is_empty


def _job(**overrides):
    values = {
        "id": uuid.UUID(int=11),
        "title": "Data Engineer",
        "short_description": "Build the pipelines that carry the warehouse.",
        "families": None,
        "attributes": {"responsibilities": ["Own the ingestion jobs"]},
        "skill_links": [
            SimpleNamespace(
                importance="bonus",
                required_level=3,
                skill=SimpleNamespace(key="sql", label="SQL"),
            ),
            SimpleNamespace(
                importance="core",
                required_level=8,
                skill=SimpleNamespace(key="python", label="Python"),
            ),
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_job_views_cover_the_closed_vocabulary():
    composed = compose_job_views(_job(), family_label="Data & Analytics")
    assert composed.kind == "job"
    assert composed.composer_version == COMPOSER_VERSION
    assert set(composed.views) == set(V1_VIEWS)
    assert composed.views["summary"].splitlines() == [
        "Data Engineer",
        "Data & Analytics",
        "Build the pipelines that carry the warehouse.",
    ]
    assert composed.views["requirements"].splitlines() == [
        "skill: Python core level 8",
        "skill: SQL bonus level 3",
    ]
    assert composed.views["skills"].splitlines() == ["skill: Python level 8", "skill: SQL level 3"]
    assert composed.views["responsibilities"] == "responsibility: Own the ingestion jobs"
    assert composed.views["body"] == "Build the pipelines that carry the warehouse."
    assert {record.view for record in composed.records} == set(V1_VIEWS)


def test_job_composition_is_deterministic_and_order_independent():
    first = compose_job_views(_job(), family_label="Data & Analytics")
    cleaned = _job(
        skill_links=list(reversed(_job().skill_links)),
    )
    assert compose_job_views(cleaned, family_label="Data & Analytics") == first
    assert compose_job_views(_job(), family_label="Data & Analytics").source_hash == (
        first.source_hash
    )
    changed = compose_job_views(_job(title="Senior Data Engineer"), family_label="Data & Analytics")
    assert changed.source_hash != first.source_hash


def test_job_records_point_at_the_catalog_row_never_at_text():
    composed = compose_job_views(_job(), family_label="Data & Analytics")
    for record in composed.records:
        assert record.text_ref is not None
        assert record.text_ref["table"] == "jobs"
        assert record.text_ref["id"] == str(uuid.UUID(int=11))
        assert "text" not in record.text_ref
        assert record.text_ref_schema_version == TEXT_REF_SCHEMA_VERSION
    body_refs = {
        record.text_ref["field"] for record in composed.records if record.view == "body"
    }
    assert body_refs == {"short_description"}


def test_job_body_chunks_carry_char_ranges():
    body = " ".join(f"duty{index}" for index in range(2000))
    composed = compose_job_views(_job(short_description=body), family_label="Data")
    chunks = [record for record in composed.records if record.view == "body"]
    assert len(chunks) > 1
    assert [record.chunk_index for record in chunks] == list(range(len(chunks)))
    for record in chunks:
        assert body[record.char_start : record.char_end] == record.text
    assert len(chunks[0].text) <= BODY_CHUNK_CHARS


def test_a_job_with_no_content_composes_nothing():
    empty = _job(title="", short_description="", attributes={}, skill_links=[])
    composed = compose_job_views(empty)
    assert composed.records == ()
    assert composed.is_empty
    assert composed.views["responsibilities"] == ""


def test_job_skills_may_be_passed_as_the_loaded_projection():
    """The index loader hands over the eager projection; the composer never
    needs a lazy relationship load."""
    projection = [
        {"label": "Python", "key": "python", "importance": "core", "level": 8},
    ]
    composed = compose_job_views(
        SimpleNamespace(
            id=uuid.UUID(int=12),
            title="Data Engineer",
            short_description="",
            attributes={},
            skill_links=[],
        ),
        family_label=None,
        skills=projection,
    )
    assert composed.views["requirements"] == "skill: Python core level 8"
