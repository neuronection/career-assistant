"""Autopilot API schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.core.errors import ValidationError

SENIORITY_VALUES = ("intern", "junior", "mid", "senior", "lead", "principal")


def _clean_term(value: str) -> str:
    return str(value).strip().lower()[:60]


class AutopilotConstraints(BaseModel):
    """The structured constraint set the agent must honor (goal JSONB).

    Referenced by stable keys (family keys, seniority values) — never
    labels. Learned terms land here too and are echoed back explicitly.
    """

    must_terms: list[str] = Field(default_factory=list, max_length=10)
    never_terms: list[str] = Field(default_factory=list, max_length=20)
    family_keys: list[str] = Field(default_factory=list, max_length=10)
    source_keys: list[str] = Field(default_factory=list, max_length=10)
    remote: Optional[bool] = None
    salary_min: Optional[float] = Field(default=None, ge=0)
    seniority: list[str] = Field(default_factory=list, max_length=6)
    exclude_seen: bool = True
    cooldown_days: int = Field(default=7, ge=0, le=90)
    top_n: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def _normalize(self) -> "AutopilotConstraints":
        self.must_terms = list(
            dict.fromkeys(t for t in (_clean_term(t) for t in self.must_terms) if t)
        )
        self.never_terms = list(
            dict.fromkeys(t for t in (_clean_term(t) for t in self.never_terms) if t)
        )
        self.family_keys = [
            str(k).strip()[:80] for k in self.family_keys if str(k).strip()
        ]
        self.source_keys = [
            str(k).strip()[:80] for k in self.source_keys if str(k).strip()
        ]
        overlap = set(self.must_terms) & set(self.never_terms)
        if overlap:
            raise ValidationError(
                f"'{sorted(overlap)[0]}' cannot be both a must-term and a never-term"
            )
        if self.seniority:
            unknown = [s for s in self.seniority if s not in SENIORITY_VALUES]
            if unknown:
                raise ValidationError(
                    "seniority must be one of: " + ", ".join(SENIORITY_VALUES)
                )
        return self


class AutopilotBudget(BaseModel):
    """Run-level cap layered over ai_budgets."""

    max_tokens: Optional[int] = Field(default=None, ge=1)
    max_calls: Optional[int] = Field(default=None, ge=1, le=20)


class AutopilotGoalCreate(BaseModel):
    goal_text: str = Field(min_length=3, max_length=2000)
    constraints: AutopilotConstraints = Field(default_factory=AutopilotConstraints)
    budget: AutopilotBudget = Field(default_factory=AutopilotBudget)
    cadence: Optional[dict] = None


class AutopilotGoalUpdate(BaseModel):
    goal_text: Optional[str] = Field(default=None, min_length=3, max_length=2000)
    constraints: Optional[AutopilotConstraints] = None
    budget: Optional[AutopilotBudget] = None
    status: Optional[Literal["active", "paused"]] = None
    cadence: Optional[dict] = None
    remove_cadence: bool = False


class AutopilotFeedbackIn(BaseModel):
    feedback: Literal["more_like_this", "hide_like_this"]
