"""NACE competency evidence schemas (plan 212 S3.5)."""

from typing import Literal

from pydantic import BaseModel, Field

EvidenceKind = Literal["experience", "achievement", "skill", "certification"]


class CompetencyEvidenceOut(BaseModel):
    id: str
    kind: EvidenceKind
    label: str
    quote: str = ""


class CompetencyOut(BaseModel):
    key: str
    evidence: list[CompetencyEvidenceOut] = Field(default_factory=list)


class CompetenciesOut(BaseModel):
    competencies: list[CompetencyOut] = Field(default_factory=list)
