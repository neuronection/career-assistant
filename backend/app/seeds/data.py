"""Seed data loading (plan 123.5): JSON files, pydantic-validated at load.

The literal catalog/assessment/template/metric vocabularies live in
``app/data/seeds/*.json`` (bundled with the desktop app via the
packaging spec's ``app/data`` entry). Every structure is validated
through pydantic models at import time — a malformed seed file fails
loudly at boot instead of seeding half a catalog. Nested JSONB payloads
(``options``, ``content``, ``sources``) stay schema-free by design
(plan 42: the JSONB shapes are disciplined; no blanket cleanup).
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

SEEDS_DIR = Path(__file__).resolve().parents[1] / "data" / "seeds"


def load_seed(name: str) -> dict[str, Any]:
    """Read one seed JSON file (raw parsed payload)."""
    return json.loads((SEEDS_DIR / f"{name}.json").read_text(encoding="utf-8"))


class _SeedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)


class InterestTag(_SeedModel):
    key: str
    label: str
    category: str


class SkillTag(_SeedModel):
    key: str
    label: str
    category: str


class Family(_SeedModel):
    key: str
    label: str
    description: str | None = None
    parent: str | None = None


class WorkStyle(_SeedModel):
    teamwork: int
    environment: int
    structure: int
    pace: int
    leadership: int
    physical_activity: str


class JobEducation(_SeedModel):
    level: str
    fields: list[str]


class JobPhysical(_SeedModel):
    activity: str
    requirements: list[str]


class JobSalary(_SeedModel):
    currency: str
    entry: list[int]
    median: list[int]
    senior: list[int]


class JobDemand(_SeedModel):
    outlook: str
    note: str
    sources: dict[str, Any]


class Aspect(_SeedModel):
    title: str
    detail: str
    weight: float | None = None


class Job(_SeedModel):
    code: str
    title: str
    family: str
    description: str
    interests: list[str]
    skills: list[str]
    subjects: list[str]
    work_style: WorkStyle
    education: JobEducation
    physical: JobPhysical
    salary: JobSalary
    demand: JobDemand
    environments: list[str]
    positives: list[Aspect]
    negatives: list[Aspect]


class Relation(_SeedModel):
    from_job: str = Field(alias="from")
    to_job: str = Field(alias="to")
    type: str
    weight: float
    rationale: str


class PathStep(_SeedModel):
    # step payloads vary by kind (education_level / skill_key / optional / …);
    # known keys stay typed, the rest pass through untouched.
    model_config = ConfigDict(extra="allow")

    kind: str
    label: str
    education_level: str | None = None
    detail: str | None = None


class CareerPath(_SeedModel):
    job: str
    title: str
    description: str
    steps: list[PathStep]


class MetricDimension(_SeedModel):
    key: str
    label: str
    group: str
    description: str
    sources: list[str]
    consumers: list[str]


class BankQuestion(_SeedModel):
    phase: int
    kind: str
    prompt: str
    help: str
    options: list[dict[str, Any]]


class BankTemplate(_SeedModel):
    key: str
    title: str
    description: str
    version: int
    page_size: str
    ats_safe: bool
    content: dict[str, Any]


class BankPack(_SeedModel):
    key: str
    task: str
    title: str
    instructions: str


def _validated(adapter: TypeAdapter[Any], name: str, key: str) -> Any:
    payload = load_seed(name)[key]
    try:
        return adapter.validate_python(payload)
    except ValidationError as exc:
        raise SystemExit(f"seed data {name}.json[{key!r}] failed validation: {exc}") from exc


def seed_list(model: type[BaseModel], name: str, key: str) -> list[dict]:
    """Load + validate a list-of-objects seed; plain dicts come back out.

    ``exclude_unset`` keeps the round-trip byte-faithful: optionals the
    JSON omits stay omitted (validation may reject, never rewrite).
    """
    adapter = TypeAdapter(list[model])  # type: ignore[valid-type]
    return [
        item.model_dump(by_alias=True, exclude_unset=True)
        for item in _validated(adapter, name, key)
    ]


def seed_mapping(model: type[BaseModel], name: str, key: str) -> dict:
    """Load + validate a str-keyed mapping seed."""
    adapter = TypeAdapter(dict[str, model])  # type: ignore[valid-type]
    return {
        k: v.model_dump(by_alias=True, exclude_unset=True)
        for k, v in _validated(adapter, name, key).items()
    }
