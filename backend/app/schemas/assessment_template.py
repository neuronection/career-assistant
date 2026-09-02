"""Assessment template content schemas (plan 37).

Templates are content, not code: a pydantic-validated package that
compiles onto the plan-23 engine. Every referenced `skill_key` must
resolve to a taxonomy id at save/import time (plan-21 discipline);
evidence-only kinds must not carry deltas; scoring deltas are bounded.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

MAX_PHASES = 8
MAX_QUESTIONS_PER_TEMPLATE = 40
DELTA_BOUND = 10.0

QuestionKind = Literal[
    "scenario_mcq",
    "single_select",
    "multi_select",
    "time_allocation",
    "ranking",
    "slider",
    "forced_choice",
    "likert_matrix",
    "numeric_input",
    "eligibility_gate",
    "short_text",
]

EVIDENCE_ONLY_KINDS = {"short_text"}
OPTION_KINDS = {
    "scenario_mcq",
    "single_select",
    "multi_select",
    "time_allocation",
    "ranking",
    "forced_choice",
    "eligibility_gate",
}


class OptionScores(BaseModel):
    skill_levels: dict[str, float] = Field(default_factory=dict)
    interest_keys: list[str] = Field(default_factory=list, max_length=10)
    constraint_value: Optional[str] = Field(default=None, max_length=80)


class TemplateOption(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=300)
    detail: str = Field(default="", max_length=500)
    scores: OptionScores = Field(default_factory=OptionScores)


class Statement(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=300)
    reverse: bool = False
    scores: OptionScores = Field(default_factory=OptionScores)


class TemplateQuestion(BaseModel):
    kind: QuestionKind
    prompt: str = Field(min_length=1, max_length=500)
    help: str = Field(default="", max_length=500)
    options: list[TemplateOption] = Field(default_factory=list, max_length=12)
    statements: list[Statement] = Field(default_factory=list, max_length=15)
    min_select: Optional[int] = Field(default=None, ge=0)
    max_select: Optional[int] = Field(default=None, ge=1)
    numeric_min: Optional[float] = None
    numeric_max: Optional[float] = None
    numeric_unit: str = Field(default="", max_length=30)
    skill_key: Optional[str] = Field(default=None, max_length=80)
    per_unit: float = Field(default=1.0, ge=0, le=10)
    cap: float = Field(default=10.0, ge=0, le=10)
    constraint_key: Optional[str] = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def _kind_shape(self):
        if self.kind in OPTION_KINDS and len(self.options) < 2:
            raise ValueError(f"{self.kind} needs at least 2 options")
        if self.kind == "forced_choice" and not 2 <= len(self.options) <= 4:
            raise ValueError("forced_choice needs 2–4 blocks")
        if self.kind == "likert_matrix" and len(self.statements) < 2:
            raise ValueError("likert_matrix needs at least 2 statements")
        if self.kind == "multi_select":
            if self.min_select is None or self.max_select is None:
                raise ValueError("multi_select needs min_select/max_select")
            if self.min_select > self.max_select:
                raise ValueError("min_select cannot exceed max_select")
            if self.max_select > len(self.options):
                raise ValueError("max_select exceeds the option count")
        if self.kind in EVIDENCE_ONLY_KINDS:
            if self.options or self.statements:
                raise ValueError("evidence-only kinds carry no options/statements")
        self._validate_scores(self.options)
        for statement in self.statements:
            self._validate_scores([statement])
        return self

    @staticmethod
    def _validate_scores(items) -> None:
        for item in items:
            scores = item.scores
            if isinstance(item, Statement) and item.reverse:
                pass
            for key, value in (scores.skill_levels or {}).items():
                if not key or len(key) > 80:
                    raise ValueError(f"invalid skill key: {key!r}")
                if abs(value) > DELTA_BOUND:
                    raise ValueError(f"delta {value} for {key} exceeds ±{DELTA_BOUND}")
            if scores.constraint_value is not None and scores.skill_levels:
                raise ValueError("a gate option mixes constraint and skill deltas")


class TemplatePhase(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    questions: list[TemplateQuestion] = Field(default_factory=list, max_length=20)


class Normalization(BaseModel):
    """Raw accumulated deltas → clamped levels + result bands."""

    multiplier: float = Field(default=1.0, ge=0.1, le=10)
    clamp_min: float = Field(default=1.0, ge=0, le=10)
    clamp_max: float = Field(default=10.0, ge=1, le=10)
    bands: list["ResultBand"] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _sane(self):
        if self.clamp_min >= self.clamp_max:
            raise ValueError("clamp_min must be below clamp_max")
        return self


class ResultBand(BaseModel):
    min: float
    max: float
    label: str = Field(min_length=1, max_length=80)
    summary: str = Field(default="", max_length=1000)
    suggested_levels: dict[str, int] = Field(default_factory=dict, max_length=15)
    next_actions: list[dict] = Field(default_factory=list, max_length=5)


class TemplateContent(BaseModel):
    """The validated package stored in `assessment_templates.content`.

    `normalization.bands` double as the human-readable results: the band
    the run lands in carries the summary, suggested levels and next
    actions.
    """

    schema_version: int = Field(default=1, ge=1, le=99)
    phases: list[TemplatePhase] = Field(min_length=1, max_length=MAX_PHASES)
    normalization: Normalization = Field(default_factory=Normalization)

    @model_validator(mode="after")
    def _non_empty(self):
        if not any(p.questions for p in self.phases):
            raise ValueError("a template needs at least one question")
        total = sum(len(p.questions) for p in self.phases)
        if total > MAX_QUESTIONS_PER_TEMPLATE:
            raise ValueError(
                f"a template carries at most {MAX_QUESTIONS_PER_TEMPLATE} questions"
            )
        return self
