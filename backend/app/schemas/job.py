from datetime import datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from app.models.job_model import Job

from app.models.enums import (
    DemandOutlook,
    EducationLevel,
    Environment,
    JobLinkKind,
    JobSkillImportance,
    JobSource,
    JobStatus,
    PhysicalActivity,
    RelationType,
)

MoneyRange = tuple[int, int]


class SalaryInfo(BaseModel):
    currency: str = "USD"
    entry: MoneyRange | None = None
    median: MoneyRange | None = None
    senior: MoneyRange | None = None


class DemandInfo(BaseModel):
    outlook: DemandOutlook = DemandOutlook.STABLE
    note: str = ""
    sources: dict = Field(default_factory=dict)


# ---- v2 vocabulary: archetypes speak the same language as
# posting extraction. Curated rows may fill these; the AI enrichment
# sweep only ever proposes them (deterministic fields stay human-owned).
CONTRACT_TYPES = Literal[
    "permanent",
    "temporary",
    "contract",
    "freelance",
    "b2b",
    "internship",
    "apprenticeship",
]
SCHEDULE_CUES = Literal[
    "shift_work",
    "on_call",
    "nights",
    "weekends",
    "flexible",
]
BENEFIT_KINDS = Literal[
    "healthcare",
    "pension",
    "leave",
    "remote_budget",
    "learning",
    "equity",
    "meals",
    "transport",
    "other",
]


class CatalogWorkHours(BaseModel):
    pattern: Literal["full_time", "part_time"]
    hours_per_week_min: int | None = Field(default=None, ge=1, le=80)
    hours_per_week_max: int | None = Field(default=None, ge=1, le=80)


class CatalogTravel(BaseModel):
    level: Literal["none", "occasional", "frequent"]
    days_per_month: int | None = Field(default=None, ge=0, le=31)


class WorkStyle(BaseModel):
    teamwork: Literal[1, 2, 3, 4, 5] = 3
    environment: Literal[1, 2, 3, 4, 5] = 3
    structure: Literal[1, 2, 3, 4, 5] = 3
    pace: Literal[1, 2, 3, 4, 5] = 3
    leadership: Literal[1, 2, 3, 4, 5] = 3
    physical_activity: PhysicalActivity = PhysicalActivity.LIGHT


class EducationRequirement(BaseModel):
    level: EducationLevel = EducationLevel.HIGH_SCHOOL
    fields: list[str] = Field(default_factory=list, max_length=10)


class PhysicalRequirement(BaseModel):
    activity: PhysicalActivity = PhysicalActivity.LIGHT
    requirements: list[str] = Field(default_factory=list, max_length=10)


class Aspect(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    detail: str = Field(default="", max_length=800)


class JobAttributes(BaseModel):
    subjects: list[str] = Field(default_factory=list, max_length=10)
    # Typical years of experience band (min, max) — feeds the fit engine's
    # experience dimension (Phase 22). Absent ⇒ neutral "no signal".
    experience_typical_years: tuple[float, float] | None = None
    work_style: WorkStyle = Field(default_factory=WorkStyle)
    education: EducationRequirement = Field(default_factory=EducationRequirement)
    physical: PhysicalRequirement = Field(default_factory=PhysicalRequirement)
    salary: SalaryInfo = Field(default_factory=SalaryInfo)
    demand: DemandInfo = Field(default_factory=DemandInfo)
    environments: list[Environment] = Field(default_factory=list, max_length=6)
    typical_positives: list[Aspect] = Field(default_factory=list, max_length=8)
    typical_negatives: list[Aspect] = Field(default_factory=list, max_length=8)
    contract_type: CONTRACT_TYPES | None = None
    work_hours: CatalogWorkHours | None = None
    schedule_cues: list[SCHEDULE_CUES] = Field(default_factory=list, max_length=5)
    travel_required: CatalogTravel | None = None
    benefits_kinds: list[BENEFIT_KINDS] = Field(default_factory=list, max_length=9)


class JobSkillIn(BaseModel):
    """Skill requirement attached to a job create/update payload."""

    skill_key: str = Field(min_length=1, max_length=80)
    required_level: int = Field(default=5, ge=1, le=10)
    importance: JobSkillImportance = JobSkillImportance.IMPORTANT
    rationale: str = Field(default="", max_length=500)


class JobLink(BaseModel):
    """Curated outbound link (Phase 24); https-only by allowlist."""

    label: str = Field(min_length=1, max_length=160)
    url: str = Field(max_length=500)
    kind: JobLinkKind = JobLinkKind.LEARN

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("link urls must be absolute https:// urls")
        return value


class JobSkillOut(BaseModel):
    skill_id: UUID
    key: str
    label: str
    required_level: int
    importance: JobSkillImportance
    rationale: str = ""


class InterestRefOut(BaseModel):
    """Embedded typed reference: label is display-only, key is stable."""

    key: str
    label: str


class JobFamilyOut(BaseModel):
    id: UUID
    key: str
    label: str
    parent_id: UUID | None
    path: str
    level: int
    description: str
    job_count: int = 0
    children: list["JobFamilyOut"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class JobCreate(BaseModel):
    code: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: str = Field(min_length=2, max_length=160)
    family_key: str
    short_description: str = Field(default="", max_length=2000)
    attributes: JobAttributes = Field(default_factory=JobAttributes)
    interest_keys: list[str] = Field(default_factory=list, max_length=12)
    skills: list[JobSkillIn] = Field(default_factory=list, max_length=15)
    links: list[JobLink] = Field(default_factory=list, max_length=10)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    short_description: str | None = Field(default=None, max_length=2000)
    family_key: str | None = None
    attributes: JobAttributes | None = None
    interest_keys: list[str] | None = Field(default=None, max_length=12)
    skills: list[JobSkillIn] | None = Field(default=None, max_length=15)
    links: list[JobLink] | None = Field(default=None, max_length=10)
    status: Literal["draft", "published"] | None = None


class JobRetiredIntoOut(BaseModel):
    code: str
    title: str = ""


class JobOut(BaseModel):
    id: UUID
    code: str
    title: str
    family_key: str = ""
    family_label: str = ""
    short_description: str
    status: JobStatus
    source: JobSource
    attributes: JobAttributes
    interests: list[InterestRefOut] = Field(default_factory=list)
    skills: list[JobSkillOut] = Field(default_factory=list)
    links: list[JobLink] = Field(default_factory=list)
    created_at: datetime
    open_roles: int | None = None
    retired_into: JobRetiredIntoOut | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(
        cls,
        job: "Job",
        overlay: dict[str, str] | None = None,
        skill_labels: dict | None = None,
        family_label: str | None = None,
    ) -> "JobOut":
        """Build an API representation from the ORM model.

        ``overlay`` carries approved localized field values (``label`` ->
        title, ``short_description`` -> summary) and ``skill_labels`` maps
        skill ids to approved localized labels. Base values are untouched.
        """
        localized = overlay or {}
        skill_map = skill_labels or {}
        return cls(
            id=job.id,
            code=job.code,
            title=localized.get("label") or job.title,
            family_key=job.family.key if job.family else "",
            family_label=family_label
            if family_label is not None
            else (job.family.label if job.family else ""),
            short_description=localized.get("short_description") or job.short_description,
            status=JobStatus(job.status),
            source=JobSource(job.source),
            attributes=JobAttributes.model_validate(job.attributes or {}),
            interests=[
                InterestRefOut(key=link.tag.key, label=link.tag.label) for link in job.tag_links
            ],
            skills=[
                JobSkillOut(
                    skill_id=link.skill_id,
                    key=link.skill.key,
                    label=skill_map.get(link.skill_id) or link.skill.label,
                    required_level=link.required_level,
                    importance=JobSkillImportance(link.importance),
                    rationale=link.rationale,
                )
                for link in job.skill_links
            ],
            links=[JobLink.model_validate(link) for link in job.links or []],
            created_at=job.created_at,
            retired_into=JobRetiredIntoOut(
                code=str((job.ai_metadata or {}).get("retired_into")),
                title=str((job.ai_metadata or {}).get("retired_into_title") or ""),
            )
            if (job.ai_metadata or {}).get("retired_into")
            else None,
        )


class JobsPageOut(BaseModel):
    """A catalog page with the self-excluding facet counts the rail renders."""

    items: list[JobOut] = Field(default_factory=list)
    total: int = 0
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)


class RelationOut(BaseModel):
    id: UUID
    from_code: str
    to_code: str
    from_title: str
    to_title: str
    relation_type: RelationType
    weight: float
    rationale: str
    source: str


class GraphNode(BaseModel):
    id: str
    code: str
    title: str
    family_key: str
    demand: str | None = None


class GraphEdge(BaseModel):
    from_code: str
    to_code: str
    relation_type: RelationType
    weight: float


class JobGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class SimilarJobOut(BaseModel):
    """One similar catalog job from the job↔job match (plan 50 §7.3)."""

    code: str
    title: str
    family_key: str | None = None
    family_label: str | None = None
    score: float = 0.0
    #: Per-view cosines behind the score (semantic hits only).
    per_view: dict[str, float] = Field(default_factory=dict)
    #: ``semantic`` (vector match) or ``skill_overlap`` (lexical fallback).
    source: Literal["semantic", "skill_overlap"] = "skill_overlap"


class SimilarJobsOut(BaseModel):
    """A page of similar jobs plus the honest degradation reason, if any."""

    items: list[SimilarJobOut] = Field(default_factory=list)
    source: Literal["semantic", "skill_overlap"] = "skill_overlap"
    degraded: str | None = None
    space_key: str | None = None


class JobPostingMatchOut(BaseModel):
    """One live posting ranked against a catalog job (plan 50 §7.3)."""

    id: UUID
    ref: str
    title: str
    org: str = ""
    posted_at: datetime | None = None
    status: str
    catalog_job_id: UUID | None = None
    score: float = 0.0
    #: Per-view cosines behind the score (semantic hits only).
    per_view: dict[str, float] = Field(default_factory=dict)
    #: ``semantic`` (vector match) or ``catalog`` (the mapped postings).
    source: Literal["semantic", "catalog"] = "catalog"


class JobPostingsOut(BaseModel):
    """A page of live postings for a job plus the degradation reason."""

    items: list[JobPostingMatchOut] = Field(default_factory=list)
    source: Literal["semantic", "catalog"] = "catalog"
    degraded: str | None = None
