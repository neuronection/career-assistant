"""Seed catalog: job families, jobs with structured attributes, typed relations."""

from pydantic import TypeAdapter

from app.seeds.data import (
    CareerPath,
    Family,
    Job,
    Relation,
    load_seed,
    seed_list,
)

FAMILIES: list[dict] = seed_list(Family, "catalog", "FAMILIES")


JOBS: list[dict] = seed_list(Job, "catalog", "JOBS")

RELATIONS: list[dict] = seed_list(Relation, "catalog", "RELATIONS")


PATHS: list[dict] = seed_list(CareerPath, "catalog", "PATHS")


# Typical years of relevant experience per job (min, max) — fit input (22).
EXPERIENCE_YEARS: dict[str, tuple[int, int]] = TypeAdapter(
    dict[str, tuple[int, int]]
).validate_python(load_seed("catalog")["EXPERIENCE_YEARS"])
