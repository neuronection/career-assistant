"""Golden eval cases — per-task fixtures run against the mock
provider in CI.

Each case pins the prompt version it was blessed at: a prompt bump without
re-blessing (updating ``prompt_version`` + re-verifying the content
assertions) fails the eval suite, the same way ruff/pytest block commits.
Content assertions cover schema invariants plus the key behaviours the
mock fixtures encode; live-provider spot-checks stay an admin action
(costs money, never in CI).
"""

from dataclasses import dataclass
from typing import Any, Callable, Type

from pydantic import BaseModel

from app.ai.agents.posting_extractor import PostingExtract
from app.ai.prompt_versions import prompt_version
from app.models.enums import AITaskType
from app.ai.schemas import (
    ChatReply,
    JobDraftSet,
    MatchResult,
    ProfileInsight,
    UniversityExtraction,
)
from app.schemas.cv_extract import CvExtract


@dataclass(frozen=True)
class GoldenCase:
    """One blessed agent-task fixture."""

    task: str
    schema: Type[BaseModel]
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


def _build_cases() -> list[GoldenCase]:
    from app.ai.agents.chatbot import CHATBOT  # noqa: F401 — fixture side effects
    import app.ai.agents  # noqa: F401 — registers every mock fixture

    from app.ai.agents.job_generator import JOB_GENERATOR
    from app.ai.agents.prompts import MATCH_SCORER, PROFILE_ANALYST, UNIVERSITY_PARSER
    from app.schemas.cv_extract import CvExtract
    from app.ai.agents.posting_extractor import PostingExtract
    from app.ai.agents.cv_parser import build_extraction_prompt

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
    ]
    return cases


GOLDEN_CASES: list[GoldenCase] = _build_cases()
