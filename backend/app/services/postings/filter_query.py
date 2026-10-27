"""The postings filter query builder (plan 136): pure functions that
turn a :class:`PostingFilterSpec` into SQLAlchemy where-clauses. Every
axis is independently testable; the composition is a simple AND.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.models.experience_model import Organization
from app.models.posting_model import JobPosting
from app.services.postings.filter_spec import PostingFilterSpec

_TRUE = func.coalesce(  # a tautology for empty clauses
)


def _ilike_any(column: ColumnElement, values: list[str]) -> ColumnElement | None:
    if not values:
        return None
    return or_(*[column.ilike(f"%{value}%") for value in values])


def _ilike_none(column: ColumnElement, values: list[str]) -> ColumnElement | None:
    if not values:
        return None
    return and_(*[~column.ilike(f"%{value}%") for value in values])


def _include_exclude(column: ColumnElement, spec: Any) -> list[ColumnElement]:
    clauses: list[ColumnElement] = []
    if spec.include:
        clauses.append(or_(*[column == v for v in spec.include]))
    if spec.exclude:
        clauses.append(and_(*[column != v for v in spec.exclude]))
    return clauses


def build_where(spec: PostingFilterSpec) -> list[ColumnElement]:
    """All active axes as AND-able where-clauses. Empty spec → empty list."""
    clauses: list[ColumnElement] = []
    clauses.extend(_skills(spec))
    clauses.extend(_salary(spec))
    clauses.extend(_location(spec))
    clauses.extend(_companies(spec))
    clauses.extend(_seniority(spec))
    clauses.extend(_employment(spec))
    clauses.extend(_work_mode(spec))
    clauses.extend(_languages(spec))
    clauses.extend(_education(spec))
    clauses.extend(_posted_within(spec))
    clauses.extend(_match_score(spec))
    clauses.extend(_source(spec))
    clauses.extend(_saved(spec))
    clauses.extend(_description(spec))
    return [c for c in clauses if c is not None]


def _skills(spec: PostingFilterSpec) -> list[ColumnElement]:
    from app.models.posting_model import PostingSkill

    clauses: list[ColumnElement] = []
    posting_ids_include: Any = None
    posting_ids_exclude: Any = None
    if spec.skills.include:
        sq = (
            select(
                PostingSkill.posting_id, func.max(PostingSkill.required_level).label("max_level")
            )
            .where(PostingSkill.skill_key.in_(spec.skills.include))
            .group_by(PostingSkill.posting_id)
        )
        if spec.skills.min_level is not None:
            sq = sq.having(func.max(PostingSkill.required_level) >= spec.skills.min_level)
        posting_ids_include = select(sq.subquery().c.posting_id)
    if spec.skills.exclude:
        sq = (
            select(PostingSkill.posting_id)
            .where(PostingSkill.skill_key.in_(spec.skills.exclude))
            .distinct()
        )
        posting_ids_exclude = select(sq.subquery().c.posting_id)
    if posting_ids_include is not None:
        clauses.append(JobPosting.id.in_(posting_ids_include))
    if posting_ids_exclude is not None:
        clauses.append(~JobPosting.id.in_(posting_ids_exclude))
    return clauses


def _salary(spec: PostingFilterSpec) -> list[ColumnElement]:
    if not any([spec.salary.min is not None, spec.salary.max is not None, spec.salary.currency]):
        return []
    clauses: list[ColumnElement] = []
    if spec.salary.currency:
        clauses.append(JobPosting.salary_currency == spec.salary.currency.upper())
    if spec.salary.min is not None:
        clauses.append(
            func.coalesce(JobPosting.salary_normalized_min, JobPosting.salary_min)
            >= spec.salary.min
        )
    if spec.salary.max is not None:
        clauses.append(
            func.coalesce(JobPosting.salary_normalized_max, JobPosting.salary_max)
            <= spec.salary.max
        )
    return clauses


def _location(spec: PostingFilterSpec) -> list[ColumnElement]:
    clauses: list[ColumnElement] = []
    location_text = func.lower(cast(JobPosting.location, String))
    inc = _ilike_any(location_text, [v.lower() for v in spec.location.include])
    exc = _ilike_none(location_text, [v.lower() for v in spec.location.exclude])
    if inc is not None:
        clauses.append(inc)
    if exc is not None:
        clauses.append(exc)
    if spec.location.remote_only is True:
        clauses.append(JobPosting.onsite_policy == "remote")
    elif spec.location.remote_only is False:
        clauses.append(JobPosting.onsite_policy != "remote")
    return clauses


def _companies(spec: PostingFilterSpec) -> list[ColumnElement]:
    clauses: list[ColumnElement] = []
    inc = _ilike_any(func.lower(JobPosting.org), [v.lower() for v in spec.companies.include])
    exc = _ilike_none(func.lower(JobPosting.org), [v.lower() for v in spec.companies.exclude])
    if inc is not None:
        clauses.append(inc)
    if exc is not None:
        clauses.append(exc)
    for attr, values in (
        ("industries_include", spec.companies.industries_include),
        ("industries_exclude", spec.companies.industries_exclude),
    ):
        if not values:
            continue
        org_sq = select(Organization.id).where(
            or_(*[Organization.name.ilike(f"%{v}%") for v in values])
        )
        cond = JobPosting.org_id.in_(org_sq)
        clauses.append(cond if attr == "industries_include" else ~cond)
    return clauses


def _seniority(spec: PostingFilterSpec) -> list[ColumnElement]:
    return _include_exclude(JobPosting.seniority, spec.seniority)


def _employment(spec: PostingFilterSpec) -> list[ColumnElement]:
    return _include_exclude(JobPosting.employment_type, spec.employment)


def _work_mode(spec: PostingFilterSpec) -> list[ColumnElement]:
    return _include_exclude(JobPosting.onsite_policy, spec.work_mode)


def _languages(spec: PostingFilterSpec) -> list[ColumnElement]:
    if not (spec.languages.include or spec.languages.exclude):
        return []
    clauses: list[ColumnElement] = []
    langs = cast(JobPosting.extract, String)
    for value in spec.languages.include:
        clauses.append(langs.ilike(f'%"{value}"%'))
    for value in spec.languages.exclude:
        clauses.append(~langs.ilike(f'%"{value}"%'))
    return clauses


def _education(spec: PostingFilterSpec) -> list[ColumnElement]:
    if not (spec.education.include or spec.education.exclude):
        return []
    clauses: list[ColumnElement] = []
    edu = cast(JobPosting.extract, String)
    for value in spec.education.include:
        clauses.append(edu.ilike(f'%"{value}"%'))
    for value in spec.education.exclude:
        clauses.append(~edu.ilike(f'%"{value}"%'))
    return clauses


def _posted_within(spec: PostingFilterSpec) -> list[ColumnElement]:
    if spec.posted_within.days is None:
        return []
    cutoff = datetime.now(UTC) - timedelta(days=spec.posted_within.days)
    return [JobPosting.posted_at >= cutoff]


def _match_score(spec: PostingFilterSpec) -> list[ColumnElement]:
    if spec.match_score.min is None and spec.match_score.max is None:
        return []
    from app.models.posting_model import PostingFit

    fit_sq = select(PostingFit.posting_id, PostingFit.score)
    if spec.match_score.min is not None:
        fit_sq = fit_sq.where(PostingFit.score >= spec.match_score.min)
    if spec.match_score.max is not None:
        fit_sq = fit_sq.where(PostingFit.score <= spec.match_score.max)
    return [JobPosting.id.in_(select(fit_sq.subquery().c.posting_id))]


def _source(spec: PostingFilterSpec) -> list[ColumnElement]:
    if not (spec.source.include or spec.source.exclude):
        return []
    from app.models.posting_model import JobSource

    keys = list(set(spec.source.include + spec.source.exclude))
    source_sq = select(JobSource.id).where(JobSource.key.in_(keys))
    id_map = dict(
        (source.key, source.id)
        for source in []  # resolved at call time by the caller
    )
    # The builder works on source KEYS; the caller resolves them to ids
    # via a subquery so we never need a round-trip here.
    clauses: list[ColumnElement] = []
    if spec.source.include:
        inc_sq = select(JobSource.id).where(JobSource.key.in_(spec.source.include))
        clauses.append(JobPosting.source_id.in_(inc_sq))
    if spec.source.exclude:
        exc_sq = select(JobSource.id).where(JobSource.key.in_(spec.source.exclude))
        clauses.append(~JobPosting.source_id.in_(exc_sq))
    return clauses


def _saved(spec: PostingFilterSpec) -> list[ColumnElement]:
    if spec.saved.value is None:
        return []
    from app.models.posting_model import PostingInteraction

    saved_sq = select(PostingInteraction.posting_id).where(PostingInteraction.saved_at.isnot(None))
    if spec.saved.value:
        return [JobPosting.id.in_(saved_sq)]
    return [~JobPosting.id.in_(saved_sq)]


def _description(spec: PostingFilterSpec) -> list[ColumnElement]:
    if not spec.description.text:
        return []
    raw = cast(JobPosting.raw, String)
    return [raw.ilike(f"%{spec.description.text}%")]
