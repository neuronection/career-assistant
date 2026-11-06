"""Structured job-type proposals (plan 202).

The proposer answers one question for an unmapped posting: is there an
existing catalog job type this posting belongs to, or does the catalog need
a new occupation archetype? It never writes the catalog — the admin remains
the gate.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import RunRef, ainvoke_structured, register_mock_fixture
from app.core.errors import AINotConfiguredError
from app.models.enums import AITaskType
from app.services.postings.job_type_text import (
    job_type_title_issue,
    strip_level_prefix,
)


class JobTypeDecision(StrEnum):
    MAP_EXISTING = "map_existing"
    CREATE = "create"
    NONE = "none"


class JobTypeProposalOut(BaseModel):
    """One typed proposal from the ``job_type_proposal`` task."""

    action: JobTypeDecision
    existing_job_code: str | None = None
    title: str | None = None
    family_key: str | None = None
    short_description: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _action_shape(self) -> JobTypeProposalOut:
        if self.action is JobTypeDecision.MAP_EXISTING and not self.existing_job_code:
            raise ValueError("map_existing requires existing_job_code")
        if self.action is JobTypeDecision.CREATE and (
            not self.title or not self.family_key or not self.short_description
        ):
            raise ValueError("create requires title, family_key and short_description")
        if self.action is JobTypeDecision.NONE:
            self.existing_job_code = None
            self.title = None
            self.family_key = None
            self.short_description = None
        return self


JOB_TYPE_POLICY = """You classify one job posting into a catalog job type.

A job type is the KIND OF WORK someone is hired to do, reusable across
employers — an occupation archetype, not a posting title.
- Title case, 2-6 words, the catalog's existing style.
- NEVER include a level qualifier when the occupation noun remains:
  Senior, Junior, Lead, Principal, Staff, III, Head of.
  ("Principal Software Engineer" -> "Software Engineer")
- An employment/level word that IS the role noun is kept or converted:
  "Marketing Intern" -> "Marketing Intern" or "Marketing Assistant" (never
  just "Marketing"); "Working Student, Finance" -> "Finance Working Student".
- NEVER include employment type as a separate qualifier, location/territory
  (Southeast, EMEA, United States, Berlin), company/product/team/platform/
  vendor names (MuleSoft, NetSuite, Salesforce, Dropbox, Product
  Engineering, Integrations), or requisition ids.
- A domain specialization is allowed when it names a recognized occupation
  (Security Engineer, Credit Risk Analyst, Mechanical Design Engineer).
- PREFER an existing catalog type: answer map_existing when a candidate
  covers the occupation. Answer create only when the occupation is genuinely
  uncovered.
- Answer none when the text does not describe a real occupation (a
  department-only page, a noisy scrape, a multi-role dump). If the posting
  describes several roles, classify the role the posting title names; if
  the title is genuinely ambiguous, answer none instead of blending them.
- short_description (for create): 2-3 present-tense sentences describing the
  archetype. No company, team, product, level, location or compensation, and
  never "The <level> will...".

Examples:
- "Principal Software Engineer, Product Engineering" -> Software Engineer
- "Software Development Engineer III, MuleSoft" -> Software Development
  Engineer or Integration Engineer (never MuleSoft)
- "Marketing Intern" -> Marketing Intern or Marketing Assistant (never
  Marketing)
- "Principal Engineer - Identity & Privacy" -> Security Engineer or Privacy
  Engineer (never just Engineer)
- "Account Executive - Southeast" -> Account Executive
- "Commercial Counsel, Bridge" -> Commercial Counsel
- "Support Delivery Lead - Toronto" -> Support Engineer or Customer Support
  Manager (never Support Delivery)
- "Mechanical Engineer - Design & Simulation" -> Mechanical Engineer or
  Mechanical Design Engineer"""


def _candidate_payload(candidates) -> list[dict]:
    return [
        {
            "code": candidate.code,
            "title": candidate.title,
            "family": candidate.family_key,
            "short_description": (candidate.short_description or "")[:200],
            "score": round(candidate.score, 3),
            "source": candidate.source,
        }
        for candidate in candidates
    ]


def build_user_prompt(
    *,
    raw_title: str,
    title_norm: str,
    seniority: str | None,
    description: str,
    skills: list[dict],
    candidates,
    family_keys: dict,
    language_name: str,
) -> str:
    """The bounded proposer context — no raw catalog text beyond 200 chars."""
    return context_json(
        {
            "posting_title": raw_title,
            "title_norm": title_norm,
            "seniority": seniority,
            "description": (description or "")[:4000],
            "skills": skills[:20],
            "candidates": _candidate_payload(candidates),
            "published_job_types": [entry["title"] for entry in family_keys["job_types"]][:200],
            "family_keys": [
                {"key": entry["key"], "label": entry["label"]} for entry in family_keys["families"]
            ],
            "language": language_name,
        }
    )


def _mock_proposal(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    candidates = ctx.get("candidates") or []
    title_norm = str(ctx.get("title_norm") or "")
    lowered = title_norm.casefold()
    if candidates:
        return {
            "action": JobTypeDecision.MAP_EXISTING.value,
            "existing_job_code": candidates[0]["code"],
            "confidence": 0.8,
            "rationale": "The catalog already covers this occupation.",
        }
    if "identity" in lowered or "privacy" in lowered:
        title = "Privacy Engineer"
    elif "mulesoft" in lowered:
        title = "Software Development Engineer"
    elif "marketing intern" in lowered:
        title = "Marketing Intern"
    else:
        title = strip_level_prefix(title_norm) or title_norm
        title = re.split(r"\s+[-\u2013\u2014,]\s+", title, maxsplit=1)[0].strip() or title
    families = ctx.get("family_keys") or []
    family_key = families[0]["key"] if families else None
    if job_type_title_issue(title) is not None or not family_key:
        return {
            "action": JobTypeDecision.NONE.value,
            "confidence": 0.2,
            "rationale": "The text does not name a reusable occupation.",
        }
    return {
        "action": JobTypeDecision.CREATE.value,
        "title": title,
        "family_key": family_key,
        "short_description": (
            f"{title}s do the core work of this occupation across employers, "
            "applying its methods, tools and judgement to the problems the "
            "role exists to solve."
        ),
        "confidence": 0.55,
        "rationale": "No existing catalog type covers this occupation.",
    }


register_mock_fixture(AITaskType.JOB_TYPE_PROPOSAL, _mock_proposal)


def _finalize(result: JobTypeProposalOut, candidates, family_keys: dict) -> JobTypeProposalOut:
    codes = {candidate.code for candidate in candidates}
    if result.action is JobTypeDecision.MAP_EXISTING and result.existing_job_code not in codes:
        return JobTypeProposalOut(
            action=JobTypeDecision.NONE,
            confidence=result.confidence,
            rationale="The proposed existing_job_code was not in the candidate set.",
        )
    if result.action is JobTypeDecision.CREATE:
        known_families = {entry["key"] for entry in family_keys["families"]}
        if result.family_key not in known_families:
            result.family_key = None
    return result


def _prompt(
    posting,
    extract: dict,
    candidates,
    family_keys: dict,
    language_name: str,
) -> str:
    return build_user_prompt(
        raw_title=posting.title,
        title_norm=str(extract.get("title_norm") or ""),
        seniority=extract.get("seniority"),
        description=str(extract.get("description_clean") or ""),
        skills=list(extract.get("skills") or []),
        candidates=candidates,
        family_keys=family_keys,
        language_name=language_name,
    )


async def propose_job_type(
    db: AsyncSession,
    posting,
    extract: dict,
    candidates,
    family_keys: dict,
    language_name: str,
    *,
    run: RunRef | None = None,
) -> JobTypeProposalOut | None:
    """Run the bounded job-type proposal task, or ``None`` when unavailable."""
    try:
        result = await ainvoke_structured(
            db,
            AITaskType.JOB_TYPE_PROPOSAL,
            JobTypeProposalOut,
            system=JOB_TYPE_POLICY,
            user=_prompt(posting, extract, candidates, family_keys, language_name),
            run=run,
        )
    except AINotConfiguredError:
        return None
    return _finalize(result, candidates, family_keys)


async def propose_job_type_with_audit(
    db: AsyncSession,
    posting,
    extract: dict,
    candidates,
    family_keys: dict,
    language_name: str,
    *,
    run: RunRef | None = None,
) -> tuple[JobTypeProposalOut | None, dict | None]:
    """The same call, returning the gateway audit summary for the journal."""
    try:
        result, audit = await ainvoke_structured(
            db,
            AITaskType.JOB_TYPE_PROPOSAL,
            JobTypeProposalOut,
            system=JOB_TYPE_POLICY,
            user=_prompt(posting, extract, candidates, family_keys, language_name),
            run=run,
            with_audit_ref=True,
        )
    except AINotConfiguredError:
        return None, None
    return _finalize(result, candidates, family_keys), audit


__all__ = [
    "JOB_TYPE_POLICY",
    "JobTypeDecision",
    "JobTypeProposalOut",
    "build_user_prompt",
    "propose_job_type",
    "propose_job_type_with_audit",
]
