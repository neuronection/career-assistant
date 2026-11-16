"""Discipline -> job-family suggestion schemas (plan 212 S3.3)."""

from typing import Literal

from pydantic import BaseModel, Field

DegreeRoleReason = Literal["matched", "parent", "family_expansion"]


class DegreeRoleMatchOut(BaseModel):
    family_key: str
    family_title: str
    matched_terms: list[str] = Field(default_factory=list)
    reason: DegreeRoleReason
    depth: int


class DegreeRolesOut(BaseModel):
    """Structured suggestions; the UI localizes reason codes into sentences."""

    matches: list[DegreeRoleMatchOut] = Field(default_factory=list)
