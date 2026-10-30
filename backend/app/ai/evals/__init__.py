"""Golden eval cases — per-task fixtures run against the mock
provider in CI.

Each case pins the prompt version it was blessed at: a prompt bump without
re-blessing (updating ``prompt_version`` + re-verifying the content
assertions) fails the eval suite, the same way ruff/pytest block commits.
Content assertions cover schema invariants plus the key behaviours the
mock fixtures encode; live-provider spot-checks stay an admin action
(costs money, never in CI).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.ai.agents.posting_extractor import PostingExtract
from app.ai.agents.skill_relation_suggest import SkillEdgeVerdictSet
from app.ai.prompt_versions import prompt_version
from app.ai.schemas import (
    ChatReply,
    Curation,
    CvBuildCritique,
    JobDraftSet,
    MatchResult,
    ProfileInsight,
    SearchPlan,
    UniversityExtraction,
)
from app.models.enums import AITaskType
from app.schemas.cv_extract import CvExtract


@dataclass(frozen=True)
class GoldenCase:
    """One blessed agent-task fixture."""

    task: str
    schema: type[BaseModel]
    system: str
    user: str
    prompt_version: str
    check: Callable[[Any], None]


def _blessed(task: str) -> str:
    return prompt_version(task)


def _check_chat(reply: ChatReply) -> None:
    assert reply.answer
    assert "nurse" in reply.answer
    assert reply.referenced_job_codes == ["nurse", "teacher"]


def _check_chat_add_project(reply: ChatReply) -> None:
    assert not reply.profile_ops or reply.profile_ops[0].kind == "experience_item"


def _check_chat_language_op(reply: ChatReply) -> None:
    ops = reply.profile_ops
    assert len(ops) == 1
    op = ops[0]
    assert op.kind == "profile_section" and op.action == "update"
    assert op.payload["section"] == "academics"
    languages = op.payload["value"]["languages"]
    assert {"code": "de", "level": "native"} in languages


def _check_chat_edit_without_read_is_dropped(reply: ChatReply) -> None:
    """Plan 99.1: update ops without the target's full content in
    context are never proposed (the server discards them)."""
    assert not reply.profile_ops


def _check_chat_delete_cert(reply: ChatReply) -> None:
    ops = reply.profile_ops
    assert len(ops) == 1
    op = ops[0]
    assert op.kind == "certification" and op.action == "delete"
    assert op.entity_id == "cert-1"


def _check_chat_cv_reference(reply: ChatReply) -> None:
    assert "Backend CV" in reply.answer
    assert "Reference only" in reply.answer
    assert not reply.profile_ops


def _check_match(result: MatchResult) -> None:
    assert 0 <= result.score <= 10
    assert 0 <= result.confidence <= 1
    assert result.summary
    assert all(0 <= a.weight <= 1 for a in result.positives + result.negatives)
    assert all(p.status in ("met", "unmet", "unknown") for p in result.prerequisites)


def _check_profile(insight: ProfileInsight) -> None:
    assert insight.summary
    assert "technology-software" not in insight.suggested_interest_keys
    assert all(k for k in insight.suggested_skill_keys)


def _check_job_drafts(drafts: JobDraftSet) -> None:
    assert drafts.drafts
    codes = [d.code for d in drafts.drafts]
    assert len(codes) == len(set(codes))
    assert all(d.family_key for d in drafts.drafts)


def _check_universities(extraction: UniversityExtraction) -> None:
    assert extraction.universities
    uni = extraction.universities[0]
    assert uni.departments
    admissions = uni.departments[0].admissions
    assert admissions and admissions[0].baseline_score is not None


def _check_posting_extract(extract: PostingExtract) -> None:
    assert extract.title_norm == "Backend Developer"
    assert extract.skills
    for skill in extract.skills:
        assert skill.skill_key or skill.raw_label
        assert 1 <= skill.required_level <= 10
        assert skill.evidence_quote


def _check_cv_extract(extract: CvExtract) -> None:
    assert extract.basics.full_name == "Jane Doe"
    assert extract.summary
    assert {s.name for s in extract.skills} == {"Python", "SQL"}
    assert all(s.level_claim is not None for s in extract.skills)


def _check_build_review(critique: CvBuildCritique) -> None:
    issues = critique.issues
    assert issues, "the mock flags the fail-level lint check"
    issue = issues[0]
    assert issue.level == "fail"
    assert issue.area == "content"
    assert critique.coverage.missing == ["skill-1"], (
        "the coverage echo mirrors the matrix ids it received"
    )


def _check_skill_edge_verdicts(reply: SkillEdgeVerdictSet) -> None:
    assert reply.verdicts
    by_ref = {v.pair_ref: v for v in reply.verdicts}
    assert by_ref["p1"].relation == "related_to"
    assert by_ref["p2"].relation == "synonym"
    assert all(0.0 <= v.confidence <= 1.0 for v in reply.verdicts)
    assert all(v.rationale for v in reply.verdicts)
    assert "Evidence quote: ML required" in by_ref["p2"].rationale


_AUTOPILOT_STATE = {
    "goal_text": "junior data analyst role, remote, where I can use programming",
    "constraints": {
        "must_terms": ["sql"],
        "never_terms": ["sales"],
        "seniority": ["junior"],
        "top_n": 5,
    },
    "profile_context": {
        "skills": [{"key": "programming", "level": 7}],
        "education_level": "high_school",
        "country": "Greece",
        "city": "Athens",
        "target_seniority": ["junior"],
    },
}

_AUTOPILOT_VOCABULARY = {
    "skills": ["programming", "data-analysis", "problem-solving"],
    "families": ["technology"],
    "sources": ["synth"],
}

_AUTOPILOT_POOL = [
    {
        "posting_id": "11111111-1111-1111-1111-111111111111",
        "title": "Junior Data Analyst",
        "org": "ExtractCo",
        "location": {"city": "Athens", "country": "Greece"},
        "seniority": "junior",
        "salary_min": 28000,
        "salary_currency": "EUR",
        "posted_at": "2026-10-28T00:00:00+00:00",
        "fit": 8.4,
        "must_hits": 1,
        "breakdown": {"skills": {"score": 8.0, "detail": "programming 7/8"}},
        "skills": [{"key": "programming", "level": 6, "priority": "must_have"}],
        "responsibilities": [{"text": "Build dashboards"}],
        "snippet": "We need programming and sql daily. Salary: 28000-36000 EUR per year.",
    },
    {
        "posting_id": "22222222-2222-2222-2222-222222222222",
        "title": "Reporting Analyst",
        "org": "Numbers Ltd",
        "location": {"city": "Athens", "country": "Greece"},
        "seniority": "mid",
        "salary_min": 32000,
        "salary_currency": "EUR",
        "posted_at": "2026-10-27T00:00:00+00:00",
        "fit": 6.1,
        "must_hits": 0,
        "breakdown": {"skills": {"score": 5.0, "detail": "python 4/8"}},
        "skills": [{"key": "data-analysis", "level": 5, "priority": "nice_to_have"}],
        "responsibilities": [{"text": "Own the weekly pack"}],
        "snippet": "Monthly reporting for the finance team.",
    },
]


def _autopilot_planner_prompt() -> tuple[str, str]:
    from app.ai.graphs.autopilot import _plan_system, _plan_user_prompt

    return _plan_system(), _plan_user_prompt(_AUTOPILOT_STATE, _AUTOPILOT_VOCABULARY)


def _autopilot_curator_prompt() -> tuple[str, str]:
    from app.ai.graphs.autopilot import _curate_system, _curate_user_prompt

    return _curate_system(5), _curate_user_prompt(_AUTOPILOT_STATE, _AUTOPILOT_POOL)


def _check_autopilot_plan(plan: SearchPlan) -> None:
    """The planner emits explore-vocabulary variants with keyword-style
    queries (plan 158 S1)."""
    from app.services.postings.explore_service import ALLOWED_FILTER_KEYS

    assert plan.variants
    for variant in plan.variants:
        assert set(variant.filters or {}) <= ALLOWED_FILTER_KEYS, (
            f"unknown filter key in variant {variant.rationale!r}"
        )
    keyword_variants = [v for v in plan.variants if "keywords" in (v.filters or {})]
    assert keyword_variants, "at least one variant searches by escaped keywords"
    for variant in keyword_variants:
        keywords = variant.filters["keywords"]
        assert isinstance(keywords, list) and keywords
        assert all(isinstance(keyword, str) and " " not in keyword for keyword in keywords)
    assert any("skills" in (v.filters or {}) for v in plan.variants), (
        "the user's skill neighbourhood is used"
    )


def _check_autopilot_curation(curation: Curation) -> None:
    assert curation.findings
    for finding in curation.findings:
        assert 0 <= finding.index < len(_AUTOPILOT_POOL)
        assert " at " in finding.why
        assert finding.quotes, "curation quotes candidate text verbatim"


def _build_cases() -> list[GoldenCase]:
    import app.ai.agents
    import app.ai.agents.cv_build_reviewer  # noqa: F401 — fixture side effect
    from app.ai.agents.cv_parser import build_extraction_prompt
    from app.ai.agents.job_generator import JOB_GENERATOR
    from app.ai.agents.posting_extractor import PostingExtract
    from app.ai.agents.prompts import CHATBOT, MATCH_SCORER, PROFILE_ANALYST, UNIVERSITY_PARSER
    from app.ai.agents.skill_relation_suggest import build_pair_prompt
    from app.schemas.cv_extract import CvExtract

    cases = [
        GoldenCase(
            task=AITaskType.CHAT.value,
            schema=ChatReply,
            system=CHATBOT,
            user=(
                'CONTEXT_JSON: {"message": "nurse or teacher jobs?", '
                '"tool_results": {"search_jobs": [{"code": "nurse", "title": '
                '"Nurse", "family": "health", "description": "care"}, '
                '{"code": "teacher", "title": "Teacher", "family": '
                '"education", "description": "teach"}]}}'
            ),
            prompt_version=_blessed(AITaskType.CHAT.value),
            check=_check_chat,
        ),
        GoldenCase(
            task=AITaskType.CHAT.value,
            schema=ChatReply,
            system=CHATBOT,
            user=(
                'CONTEXT_JSON: {"message": "please add a new project: crew '
                'AI chatbot", "tool_results": {"my_experience": '
                '{"items": []}}}'
            ),
            prompt_version=_blessed(AITaskType.CHAT.value),
            check=_check_chat_add_project,
        ),
        GoldenCase(
            task=AITaskType.CHAT.value,
            schema=ChatReply,
            system=CHATBOT,
            user=(
                'CONTEXT_JSON: {"message": "set german to native please", '
                '"tool_results": {"my_profile_digest": {"full_name": "Ann", '
                '"languages": [{"code": "en", "level": "native"}], '
                '"counts": {}, "sections": []}, "read_profile_section": '
                '[{"kind": "profile_section", "section": "academics", '
                '"content": {"languages": [{"code": "en", "level": '
                '"native"}]}}]}}'
            ),
            prompt_version=_blessed(AITaskType.CHAT.value),
            check=_check_chat_language_op,
        ),
        GoldenCase(
            task=AITaskType.CHAT.value,
            schema=ChatReply,
            system=CHATBOT,
            user=(
                'CONTEXT_JSON: {"message": "set german to native please", '
                '"tool_results": {"my_profile_digest": {"full_name": "Ann", '
                '"languages": [{"code": "en", "level": "native"}], '
                '"counts": {}, "sections": []}}}'
            ),
            prompt_version=_blessed(AITaskType.CHAT.value),
            check=_check_chat_edit_without_read_is_dropped,
        ),
        GoldenCase(
            task=AITaskType.CHAT.value,
            schema=ChatReply,
            system=CHATBOT,
            user=(
                'CONTEXT_JSON: {"message": "delete that certification", '
                '"tool_results": {"my_education": {"education": [], '
                '"certifications": [{"id": "cert-1", "name": "AWS CCP", '
                '"issuer": "Amazon", "issued": null, "expires": null, '
                '"status": "active"}], "achievements": []}, '
                '"read_profile_item": [{"kind": "certification", '
                '"entity_id": "cert-1", "content": {"name": "AWS CCP"}}]}}'
            ),
            prompt_version=_blessed(AITaskType.CHAT.value),
            check=_check_chat_delete_cert,
        ),
        GoldenCase(
            task=AITaskType.CHAT.value,
            schema=ChatReply,
            system=CHATBOT,
            user=(
                'CONTEXT_JSON: {"message": "which jobs fit this CV?", '
                '"tool_results": {}, "cv_references": [{"cv_id": "c1", '
                '"title": "Backend CV", "text": "EXPERIENCE\\nBackend '
                'Intern - Sample Corp", "earlier": false}]}'
            ),
            prompt_version=_blessed(AITaskType.CHAT.value),
            check=_check_chat_cv_reference,
        ),
        GoldenCase(
            task=AITaskType.MATCH_SCORE.value,
            schema=MatchResult,
            system=MATCH_SCORER,
            user=(
                'CONTEXT_JSON: {"profile": {"user_id": "u1", "interests": '
                '[{"tag_key": "technology-software", "weight": 5}]}, '
                '"job": {"code": "software-developer", "title": "Software '
                'Developer", "interests": ["technology-software"]}}'
            ),
            prompt_version=_blessed(AITaskType.MATCH_SCORE.value),
            check=_check_match,
        ),
        GoldenCase(
            task=AITaskType.PROFILE_ANALYZE.value,
            schema=ProfileInsight,
            system=PROFILE_ANALYST,
            user=(
                'CONTEXT_JSON: {"profile": {"interests": [{"tag_key": '
                '"technology-software", "weight": 5}, {"tag_key": '
                '"health-nursing", "weight": 3}]}, "interest_taxonomy": '
                '["technology-data", "health-nursing"], "skill_taxonomy": '
                '["programming", "problem-solving"]}'
            ),
            prompt_version=_blessed(AITaskType.PROFILE_ANALYZE.value),
            check=_check_profile,
        ),
        GoldenCase(
            task=AITaskType.JOB_GENERATE.value,
            schema=JobDraftSet,
            system=JOB_GENERATOR,
            user=(
                'CONTEXT_JSON: {"mode": "general", "count": 2, '
                '"family_keys": ["technology"], "interest_keys": '
                '["technology-software"], "skill_keys": ["programming"], '
                '"existing_codes": []}'
            ),
            prompt_version=_blessed(AITaskType.JOB_GENERATE.value),
            check=_check_job_drafts,
        ),
        GoldenCase(
            task=AITaskType.POSTING_EXTRACT.value,
            schema=PostingExtract,
            system="Extract the posting into the JSON schema.",
            user=(
                'CONTEXT_JSON: {"title": "Backend Developer", '
                '"posting_text": "We need programming and sql daily", '
                '"skill_taxonomy": ["programming", "sql"], '
                '"skills_raw": ["docker"]}'
            ),
            prompt_version=_blessed(AITaskType.POSTING_EXTRACT.value),
            check=_check_posting_extract,
        ),
        GoldenCase(
            task=AITaskType.CV_PARSE.value,
            schema=CvExtract,
            system=build_extraction_prompt(),
            user=(
                'CONTEXT_JSON: {"cv_text": "NAME: Jane Doe\\nHEADLINE: '
                "Software engineer\\nSKILL: Python: 4\\nSKILL: SQL: 3\\n"
                'LANGUAGE: en advanced\\nSUMMARY: Builder of things."}'
            ),
            prompt_version=_blessed(AITaskType.CV_PARSE.value),
            check=_check_cv_extract,
        ),
        GoldenCase(
            task=AITaskType.UNIVERSITY_PARSE.value,
            schema=UniversityExtraction,
            system=UNIVERSITY_PARSER,
            user=(
                'CONTEXT_JSON: {"document_text": "UNIVERSITY OF THE GOLDEN '
                "TEXT\\nSchool of Computing — baseline 2024: 81.5 points, "
                'quota 120\\nDeadline: 2026-04-30\\n"}'
            ),
            prompt_version=_blessed(AITaskType.UNIVERSITY_PARSE.value),
            check=_check_universities,
        ),
        GoldenCase(
            task=AITaskType.CV_BUILD_REVIEW.value,
            schema=CvBuildCritique,
            system=(
                "You review a generated CV for a final professional pass; "
                "suggest only existing BuilderOps."
            ),
            user=(
                'CONTEXT_JSON: {"lint": {"checks": [{"id": "contact_email", '
                '"level": "fail", "message": "No email in the header."}], '
                '"empty_blocks": []}, '
                '"coverage": {"included": [{"item_id": "skill-2"}], '
                '"missing": [{"source_key": "skills", "item_id": "skill-1", '
                '"label": "SQL"}], "dropped": []}, '
                '"blocks": [{"kind": "skills", "props": {"title": "Skills"}}], '
                '"iteration": 0}'
            ),
            prompt_version=_blessed(AITaskType.CV_BUILD_REVIEW.value),
            check=_check_build_review,
        ),
        GoldenCase(
            task=AITaskType.SKILL_RELATION_SUGGEST.value,
            schema=SkillEdgeVerdictSet,
            system=("Decide which typed relation, if any, holds between each skill pair."),
            user=build_pair_prompt(
                [
                    {
                        "pair_ref": "p1",
                        "hypothesis": "related_to",
                        "signals": {"cooccurrence": {"postings": 3, "jobs": 1}},
                        "skills": [
                            {
                                "key": "typescript",
                                "label": "TypeScript",
                                "aliases": ["ts"],
                                "category": "programming",
                                "parent_key": None,
                                "evidence_quote": "TypeScript experience required",
                            },
                            {
                                "key": "javascript",
                                "label": "JavaScript",
                                "aliases": ["js"],
                                "category": "programming",
                                "parent_key": None,
                                "evidence_quote": None,
                            },
                        ],
                    },
                    {
                        "pair_ref": "p2",
                        "hypothesis": "synonym",
                        "signals": {"label_match": {"kind": "initialism"}},
                        "skills": [
                            {
                                "key": "ml",
                                "label": "ML",
                                "aliases": [],
                                "category": "data",
                                "parent_key": None,
                                "evidence_quote": "ML required",
                            },
                            {
                                "key": "machine-learning",
                                "label": "Machine Learning",
                                "aliases": [],
                                "category": "data",
                                "parent_key": None,
                                "evidence_quote": None,
                            },
                        ],
                    },
                ]
            ),
            prompt_version=_blessed(AITaskType.SKILL_RELATION_SUGGEST.value),
            check=_check_skill_edge_verdicts,
        ),
    ]
    planner_system, planner_user = _autopilot_planner_prompt()
    curator_system, curator_user = _autopilot_curator_prompt()
    cases.extend(
        [
            GoldenCase(
                task=AITaskType.AUTOPILOT_RUN.value,
                schema=SearchPlan,
                system=planner_system,
                user=planner_user,
                prompt_version=_blessed(AITaskType.AUTOPILOT_RUN.value),
                check=_check_autopilot_plan,
            ),
            GoldenCase(
                task=AITaskType.AUTOPILOT_RUN.value,
                schema=Curation,
                system=curator_system,
                user=curator_user,
                prompt_version=_blessed(AITaskType.AUTOPILOT_RUN.value),
                check=_check_autopilot_curation,
            ),
        ]
    )
    return cases


GOLDEN_CASES: list[GoldenCase] = _build_cases()
