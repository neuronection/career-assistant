from datetime import datetime
from typing import Literal, Optional
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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
    entry: Optional[MoneyRange] = None
    median: Optional[MoneyRange] = None
    senior: Optional[MoneyRange] = None


class DemandInfo(BaseModel):
    outlook: DemandOutlook = DemandOutlook.STABLE
    note: str = ""
    sources: dict = Field(default_factory=dict)


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
    experience_typical_years: Optional[tuple[float, float]] = None
    work_style: WorkStyle = Field(default_factory=WorkStyle)
    education: EducationRequirement = Field(default_factory=EducationRequirement)
    physical: PhysicalRequirement = Field(default_factory=PhysicalRequirement)
    salary: SalaryInfo = Field(default_factory=SalaryInfo)
    demand: DemandInfo = Field(default_factory=DemandInfo)
    environments: list[Environment] = Field(default_factory=list, max_length=6)
    typical_positives: list[Aspect] = Field(default_factory=list, max_length=8)
    typical_negatives: list[Aspect] = Field(default_factory=list, max_length=8)


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
    parent_id: Optional[UUID]
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
    title: Optional[str] = Field(default=None, min_length=2, max_length=160)
    short_description: Optional[str] = Field(default=None, max_length=2000)
    family_key: Optional[str] = None
    attributes: Optional[JobAttributes] = None
    interest_keys: Optional[list[str]] = Field(default=None, max_length=12)
    skills: Optional[list[JobSkillIn]] = Field(default=None, max_length=15)
    links: Optional[list[JobLink]] = Field(default=None, max_length=10)
    status: Optional[JobStatus] = None


class JobOut(BaseModel):
    id: UUID
    code: str
    title: str
    family_key: str = ""
    short_description: str
    status: JobStatus
    source: JobSource
    attributes: JobAttributes
    interests: list[InterestRefOut] = Field(default_factory=list)
    skills: list[JobSkillOut] = Field(default_factory=list)
    links: list[JobLink] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, job: "Job") -> "JobOut":  # noqa: F821
        """Build an API representation from the ORM model."""
        return cls(
            id=job.id,
            code=job.code,
            title=job.title,
            family_key=job.family.key if job.family else "",
            short_description=job.short_description,
            status=JobStatus(job.status),
            source=JobSource(job.source),
            attributes=JobAttributes.model_validate(job.attributes or {}),
            interests=[
                InterestRefOut(key=link.tag.key, label=link.tag.label)
                for link in job.tag_links
            ],
            skills=[
                JobSkillOut(
                    skill_id=link.skill_id,
                    key=link.skill.key,
                    label=link.skill.label,
                    required_level=link.required_level,
                    importance=JobSkillImportance(link.importance),
                    rationale=link.rationale,
                )
                for link in job.skill_links
            ],
            links=[JobLink.model_validate(link) for link in job.links or []],
            created_at=job.created_at,
        )


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
    demand: Optional[str] = None


class GraphEdge(BaseModel):
    from_code: str
    to_code: str
    relation_type: RelationType
    weight: float


class JobGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
