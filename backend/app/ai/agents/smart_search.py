"""Smart search (plan 179): one small cached call per unique free-text
query, mapping it onto the explore filter vocabulary — nothing else.

The output is UNTRUSTED model output bounded twice: the pydantic spec is
closed (``extra="forbid"``, enum-valued axes, bounded lists) and the
service's ``parse_explore_filters`` run rejects any unknown filter key —
the filter set stays data, never free text. Skill labels are free text
on purpose; the deterministic resolver (``services/postings``) maps them
onto taxonomy keys, dropping what it cannot resolve.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.analytics.time_buckets import POSTED_WINDOWS
from app.services.postings.explore_service import REMOTE_VALUES, SENIORITY_VALUES

MAX_SKILL_LABELS = 6
MAX_FILTER_VALUES = 6
MAX_INTERPRETED_CHARS = 300
MAX_QUERY_CHARS = 300

SMART_SEARCH_SYSTEM = (
    "You map a job-search sentence onto a FIXED filter vocabulary for a "
    "student job board. Extract only what the sentence clearly says.\n"
    "Closed filter keys and their allowed values:\n"
    f"- seniority: list from {', '.join(SENIORITY_VALUES)}\n"
    f"- remote_policy: list from {', '.join(REMOTE_VALUES)}\n"
    f"- posted_within: one of {', '.join(POSTED_WINDOWS)} (empty when the "
    "sentence says nothing about recency)\n"
    "- city / country: single strings, verbatim from the sentence\n"
    "- employment_type: free strings the sentence states (full-time, "
    "internship, ...)\n"
    "- salary_min: a number, only when the sentence states a floor\n"
    "- mapped_family: catalog family keys (technology, health, education, "
    "finance, engineering) — only when the sentence names a field of work\n"
    "- skill_labels: up to 6 free-text skill names mentioned (tools, "
    "languages, technologies) — never inferred, only stated\n"
    "Rules:\n"
    "- Use ONLY the keys above; never invent keys or values.\n"
    '- Map everyday phrasings onto the vocabulary ("work from home" -> '
    'remote_policy [remote]; "last week" -> posted_within 7d).\n'
    "- Omit every dimension the sentence does not clearly state — empty "
    "means don't care.\n"
    '- "interpreted": one short sentence (max 300 chars) restating what '
    "you filtered on, for the user to verify.\n"
    "- You never see or use any personal data; the same sentence must "
    "always produce the same filters.\n"
)


def build_smart_search_prompt(query: str) -> str:
    """The user message: the free-text query as typed context JSON."""
    import json

    return "CONTEXT_JSON: " + json.dumps({"query": query}, ensure_ascii=False)


class SmartSearchSpec(BaseModel):
    """Closed explore-filter projection of one free-text query.

    Extra keys are rejected (the vocabulary is data); the enum axes
    validate their values so a hallucinated band cannot silently match
    nothing downstream.
    """

    model_config = ConfigDict(extra="forbid")

    seniority: list[str] = Field(default_factory=list)
    remote_policy: list[str] = Field(default_factory=list)
    posted_within: str | None = None
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    employment_type: list[str] = Field(default_factory=list)
    salary_min: float | None = Field(default=None, ge=0)
    mapped_family: list[str] = Field(default_factory=list)
    skill_labels: list[str] = Field(default_factory=list)
    interpreted: str = ""

    @field_validator("seniority")
    @classmethod
    def _seniority_values(cls, value: list[str]) -> list[str]:
        bad = [v for v in value if v not in SENIORITY_VALUES]
        if bad:
            raise ValueError(f"seniority values must be one of {', '.join(SENIORITY_VALUES)}")
        return value[:MAX_FILTER_VALUES]

    @field_validator("remote_policy")
    @classmethod
    def _remote_values(cls, value: list[str]) -> list[str]:
        bad = [v for v in value if v not in REMOTE_VALUES]
        if bad:
            raise ValueError(f"remote_policy values must be one of {', '.join(REMOTE_VALUES)}")
        return value[:MAX_FILTER_VALUES]

    @field_validator("posted_within")
    @classmethod
    def _posted_within_values(cls, value: str | None) -> str | None:
        if value is not None and value not in POSTED_WINDOWS:
            raise ValueError(f"posted_within must be one of {', '.join(POSTED_WINDOWS)}")
        return value

    @field_validator("employment_type", "mapped_family", "skill_labels")
    @classmethod
    def _bounded_labels(cls, value: list[str]) -> list[str]:
        cleaned = [str(v).strip()[:60] for v in value if str(v).strip()]
        return cleaned[:MAX_SKILL_LABELS]

    @field_validator("interpreted")
    @classmethod
    def _bounded_interpreted(cls, value: str) -> str:
        return str(value).strip()[:MAX_INTERPRETED_CHARS]
