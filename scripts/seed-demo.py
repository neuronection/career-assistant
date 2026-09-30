#!/usr/bin/env python
"""Seed synthetic demo data into a Career Assistant **demo** instance (P3e).

Demo data (synthetic user content) may only be seeded by this explicit
script, only on a `demo_mode=true` instance, only into the demo database
(`neuronection_career_demo`) / an isolated demo data dir (identity-auth §13,
deployment.md). **The seeder refuses anything else** — loudly, non-zero:

* target guard: a PostgreSQL target must be a database named `*_demo`
  (deployment.md: `neuronection_career_demo`); a SQLite target must sit inside an
  explicitly named `--demo-dir` (the isolated demo data dir). Anything
  else is refused before the database is touched.
* schema guard: a target without the schema needs `--init-demo` — the
  seeder never silently initializes an undeclared target.
* instance guard: `instance_settings.demo_mode` must be `true`.
  `--init-demo` may initialize it — but only on an EMPTY demo database
  (no `instance_settings`, `users` or `profiles` rows); anything else is
  refused.

Reference data is not demo data: the starter catalogs (taxonomy, job
catalog, career paths, assessment bank, CV templates) live in
`backend/app/seeds/*` and stay reference data — this script only
*ensures* they exist (the product's idempotent `app.seeds.run`), so the
synthetic experience rows can link to real skill ids. Catalog rows are
never removed by `--reset`.

Usage (interpreter with the app's dependencies, e.g. `backend/venv/bin/python`):

    # PostgreSQL demo database (the docker demo flavor):
    DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/neuronection_career_demo \\
        python scripts/seed-demo.py

    # Isolated demo data dir (SQLite), first run on an empty database:
    python scripts/seed-demo.py --demo-dir /srv/career-demo/data --init-demo

    # Reset the demo workspace to its pristine synthetic state, then reseed:
    python scripts/seed-demo.py --demo-dir /srv/career-demo/data --reset

Flags: `--database-url` (explicit target URL — wins over everything),
`--demo-dir` (the isolated demo data dir: with no `--database-url` it
selects the SQLite target `career.sqlite3` inside it), `--init-demo`,
`--reset`. Without either, `DATABASE_URL` / the Settings value is the
target — which the guards then judge. The run is idempotent: re-running
changes no counts.

The seeded workspace is synthetic-only — clearly fictional coached
people (profiles with full JSON sections, experiences, education,
certifications, CV drafts) and fictional job postings with application
pipelines. The demo users share the documented demo password
`DemoCareer!2026`; on demo instances the credential-free `demo` principal
(POST /api/v1/auth/demo) works as well.

Exit codes: 0 seeded (or already seeded), 2 refused by a guard rail,
1 unexpected error.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

REPO_ROOT = Path(__file__).resolve().parent.parent
# Repo checkout: `<repo>/backend`. Docker image: the app package and the
# alembic tree sit at the image root (`/app/app`, `/app/alembic`) — the
# seeder is bind-mounted at `/app/scripts/seed-demo.py` (demo compose).
_BACKEND_CANDIDATES = (REPO_ROOT / "backend", REPO_ROOT)
BACKEND_DIR = next(
    (
        candidate
        for candidate in _BACKEND_CANDIDATES
        if (candidate / "app" / "models").is_dir()
        and (candidate / "alembic.ini").is_file()
    ),
    REPO_ROOT / "backend",
)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, delete, event, func, inspect, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models.cv_model import CvDocument  # noqa: E402
from app.models.cv_template_model import CvTemplate  # noqa: E402
from app.models.experience_model import (  # noqa: E402
    ExperienceAchievement,
    ExperienceItem,
    ExperienceSkill,
)
from app.models.identity_model import AuthSession, InstanceSetting  # noqa: E402
from app.models.job_model import Job  # noqa: E402
from app.models.posting_model import (  # noqa: E402
    JobPosting,
    JobSource,
    PostingFit,
    PostingInteraction,
    PostingSkill,
)
from app.models.profile_entities_model import (  # noqa: E402
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.taxonomy_model import Skill  # noqa: E402
from app.models.user_model import Profile, User  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2

DEMO_PASSWORD = "DemoCareer!2026"
DEMO_NAMESPACE = uuid5(NAMESPACE_URL, "https://demo.career-assistant.invalid/seed")
# The credential-free §13 demo principal (nx_auth `demo_user_id`).
DEMO_PRINCIPAL_ID = "00000000-0000-4000-8000-00000000d0e0"
DEMO_EMAIL_DOMAIN = "@demo.career.local"
DEMO_SOURCE_KEY = "demo-postings"


class Refusal(Exception):
    """A guard rail refused the run — print loud, exit non-zero."""


def demo_id(kind: str, key: str) -> str:
    return str(uuid5(DEMO_NAMESPACE, f"{kind}:{key}"))


# --------------------------------------------------------------------------
# Synthetic fixture — clearly fictional people and career content only.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AchievementSpec:
    text: str
    metric: dict | None = None


@dataclass(frozen=True)
class SkillSpec:
    """A participation in one experience, keyed by a REFERENCE skill key.

    The skill rows themselves are reference data (`app/seeds/taxonomy.py`)
    and are never created here — unknown keys are skipped, never invented.
    """

    key: str
    role: str = "primary"
    level: int | None = None


@dataclass(frozen=True)
class ExperienceSpec:
    key: str
    kind: str
    title: str
    org: str
    start: str | None
    end: str | None = None
    open_ended: bool = False
    description: str = ""
    skills: tuple[SkillSpec, ...] = ()
    achievements: tuple[AchievementSpec, ...] = ()


@dataclass(frozen=True)
class EducationSpec:
    key: str
    institution: str
    program: str
    level: str
    start: str | None = None
    end: str | None = None
    in_progress: bool = False
    focus_subjects: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class CertificationSpec:
    key: str
    name: str
    issuer: str
    issued: str | None = None
    expires: str | None = None
    credential_id: str = ""


@dataclass(frozen=True)
class HonorSpec:
    key: str
    title: str
    issuer: str
    date: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class CvSpec:
    key: str
    title: str
    kind: str = "resume"


@dataclass(frozen=True)
class ApplicationSpec:
    posting_key: str
    stage: str
    applied_days_ago: int
    notes: str = ""


@dataclass(frozen=True)
class ProfileSpec:
    key: str
    name: str
    color: str | None = None
    is_default: bool = False
    basics: dict = field(default_factory=dict)
    academics: dict = field(default_factory=dict)
    hobbies: tuple[dict, ...] = ()
    likes: tuple[dict, ...] = ()
    dislikes: tuple[dict, ...] = ()
    aspirations: tuple[dict, ...] = ()
    work_preferences: dict = field(default_factory=dict)
    constraints: dict = field(default_factory=dict)
    preferences: dict = field(default_factory=dict)


@dataclass(frozen=True)
class UserSpec:
    key: str
    full_name: str
    email: str
    is_admin: bool = False
    profiles: tuple[ProfileSpec, ...] = ()
    experiences: tuple[ExperienceSpec, ...] = ()
    education: tuple[EducationSpec, ...] = ()
    certifications: tuple[CertificationSpec, ...] = ()
    honors: tuple[HonorSpec, ...] = ()
    cvs: tuple[CvSpec, ...] = ()
    applications: tuple[ApplicationSpec, ...] = ()


@dataclass(frozen=True)
class PostingSpec:
    key: str
    ref: str
    external_id: str
    title: str
    org: str
    catalog_job_code: str | None
    description: str
    city: str
    country: str
    remote: bool
    seniority: str
    employment_type: str
    onsite_policy: str
    education_level: str
    salary_min: float | None
    salary_max: float | None
    posted_days_ago: int
    expires_in_days: int


# The shared synthetic posting pool (a fictional job board the personas
# apply to). `catalog_job_code` links onto the reference catalog when the
# code exists — mapping is a lookup, never a catalog write.
DEMO_POSTINGS: tuple[PostingSpec, ...] = (
    PostingSpec(
        key="data-analyst",
        ref="DE000001",
        external_id="DEMO-001",
        title="Junior Data Analyst",
        org="Fernlight Analytics AB",
        catalog_job_code="data-scientist",
        description=(
            "Turn ridership and ticketing extracts into dashboards for a "
            "fictional city transit team. Mentored role — career switchers welcome."
        ),
        city="Gothenburg",
        country="Sweden",
        remote=False,
        seniority="junior",
        employment_type="full_time",
        onsite_policy="hybrid",
        education_level="bachelor",
        salary_min=32000,
        salary_max=42000,
        posted_days_ago=12,
        expires_in_days=30,
    ),
    PostingSpec(
        key="dev-starter",
        ref="DE000002",
        external_id="DEMO-002",
        title="Software Developer (Career Starter)",
        org="Lumenforge Systems",
        catalog_job_code="software-developer",
        description=(
            "A fictional 12-month starter programme on a small internal-tools "
            "team, pairing weekly and shipping to real (fictional) users."
        ),
        city="Stockholm",
        country="Sweden",
        remote=True,
        seniority="intern",
        employment_type="full_time",
        onsite_policy="remote",
        education_level="vocational",
        salary_min=28000,
        salary_max=34000,
        posted_days_ago=7,
        expires_in_days=45,
    ),
    PostingSpec(
        key="sustainability-intern",
        ref="DE000003",
        external_id="DEMO-003",
        title="Sustainability Intern",
        org="Terra Nove Consulting",
        catalog_job_code="civil-engineer",
        description=(
            "Summer internship on water and waste audits — fieldwork, lab "
            "sampling and report writing for fictional municipal clients."
        ),
        city="Växjö",
        country="Sweden",
        remote=False,
        seniority="intern",
        employment_type="internship",
        onsite_policy="on_site",
        education_level="bachelor",
        salary_min=None,
        salary_max=None,
        posted_days_ago=3,
        expires_in_days=60,
    ),
    PostingSpec(
        key="ux-junior",
        ref="DE000004",
        external_id="DEMO-004",
        title="Junior UX Designer",
        org="Kite & Compass Studio",
        catalog_job_code="ux-designer",
        description=(
            "Small fictional design studio seeks a junior UX designer for "
            "service-mapping work — portfolio over pedigree."
        ),
        city="Malmö",
        country="Sweden",
        remote=False,
        seniority="junior",
        employment_type="full_time",
        onsite_policy="hybrid",
        education_level="no_formal",
        salary_min=30000,
        salary_max=38000,
        posted_days_ago=20,
        expires_in_days=14,
    ),
)


WREN = UserSpec(
    key="wren",
    full_name="Wren Ashgrove",
    email=f"wren.ashgrove{DEMO_EMAIL_DOMAIN}",
    is_admin=True,
    profiles=(
        ProfileSpec(
            key="default",
            name="Default",
            color="#4f7cff",
            is_default=True,
            basics={
                "birth_year": 1999,
                "education_level": "bachelor",
                "career_stage": "switching",
                "onboarding_path": "cv_import",
                "country": "Sweden",
                "city": "Gothenburg",
                "timezone": "Europe/Stockholm",
                "full_name": "Wren Ashgrove",
                "email": f"wren.ashgrove{DEMO_EMAIL_DOMAIN}",
                "phone": "+46 70 000 0001",
                "headline": "Retail ops turned aspiring data analyst",
                "links": [
                    {
                        "kind": "linkedin",
                        "url": "https://demo.career.local/in/wren-ashgrove",
                        "label": "LinkedIn",
                    }
                ],
            },
            academics={
                "favorite_subjects": [
                    {"key": "technology-data", "weight": 5},
                    {"key": "mathematics", "weight": 4},
                ],
                "languages": [
                    {"code": "en", "level": "native"},
                    {"code": "sv", "level": "intermediate"},
                ],
            },
            hobbies=(
                {"key": "arts-photo-video", "label": "Film photography", "weight": 3},
                {"key": "sports-outdoors", "label": "Hiking", "weight": 3},
            ),
            likes=({"key": "technology-data", "label": "Tidy datasets", "weight": 4},),
            dislikes=({"key": None, "label": "Unstructured meetings", "weight": 2},),
            aspirations=(
                {
                    "label": "Land a first data analyst role",
                    "tag_keys": ["technology-data"],
                    "notes": "Public sector or transit preferred.",
                },
            ),
            work_preferences={
                "teamwork": 4,
                "environment": 3,
                "structure": 3,
                "pace": 3,
                "leadership": 2,
                "remote_ok": True,
                "focus_areas": ["data"],
                "salary_priority": 3,
                "stability_priority": 4,
                "physical_activity": "light",
                "creativity_priority": 3,
            },
            constraints={
                "physical_conditions": [],
                "willing_to_relocate": False,
                "hours_available_per_week": 40,
                "salary_min": 28000,
                "salary_negotiable": True,
                "commute_radius_km": 30,
            },
            preferences={
                "scoring_weights": {
                    "skills": 4,
                    "location": 3,
                    "experience": 3,
                    "education": 2,
                    "interests": 3,
                    "values": 4,
                }
            },
        ),
        ProfileSpec(
            key="data-track",
            name="Data Track",
            color="#22c55e",
            basics={
                "birth_year": 1999,
                "education_level": "bachelor",
                "career_stage": "switching",
                "country": "Sweden",
                "city": "Gothenburg",
                "timezone": "Europe/Stockholm",
                "full_name": "Wren Ashgrove",
                "email": f"wren.ashgrove{DEMO_EMAIL_DOMAIN}",
                "headline": "Data track — analytics and ML focus",
            },
            academics={
                "favorite_subjects": [
                    {"key": "technology-ai", "weight": 5},
                    {"key": "technology-data", "weight": 5},
                ],
                "languages": [{"code": "en", "level": "native"}],
            },
            aspirations=(
                {
                    "label": "Move into machine learning within five years",
                    "tag_keys": ["technology-ai"],
                    "notes": "",
                },
            ),
            work_preferences={
                "teamwork": 3,
                "environment": 3,
                "structure": 2,
                "pace": 4,
                "leadership": 2,
                "remote_ok": True,
                "focus_areas": ["data", "ideas"],
                "salary_priority": 4,
                "stability_priority": 3,
                "physical_activity": "sedentary",
                "creativity_priority": 4,
            },
        ),
    ),
    experiences=(
        ExperienceSpec(
            key="retail-ops",
            kind="job",
            title="Retail Operations Assistant",
            org="Northwind Outfitters",
            start="2022-06-01",
            end="2024-08-31",
            description=(
                "Stock control, nightly counts and till reconciliation across "
                "two fictional stores."
            ),
            skills=(
                SkillSpec("organization", "primary", 6),
                SkillSpec("customer-service", "secondary", 5),
                SkillSpec("attention-to-detail", "secondary", 6),
            ),
            achievements=(
                AchievementSpec(
                    "Cut nightly stock-count time with a shared spreadsheet",
                    {"kind": "time_saved", "value": 2, "unit": "hours_per_week"},
                ),
                AchievementSpec(
                    "Trained 6 new starters on the till system",
                    {"kind": "scale", "value": 6, "unit": "people"},
                ),
            ),
        ),
        ExperienceSpec(
            key="price-tracker",
            kind="project",
            title="Neighbourhood Price Tracker",
            org="",
            start="2024-09-01",
            end="2025-03-31",
            description=(
                "Python + pandas pipeline that scrapes fictional grocery "
                "listings into one tidy weekly dataset."
            ),
            skills=(
                SkillSpec("programming", "primary", 5),
                SkillSpec("data-analysis", "primary", 5),
                SkillSpec("problem-solving", "secondary", None),
            ),
            achievements=(
                AchievementSpec(
                    "Cleaned and merged 12k listings into one dataset",
                    {"kind": "scale", "value": 12000, "unit": "rows"},
                ),
                AchievementSpec(
                    "Weekly report reached 40 neighbours",
                    {"kind": "scale", "value": 40, "unit": "readers"},
                ),
            ),
        ),
        ExperienceSpec(
            key="transit-internship",
            kind="internship",
            title="Data Intern",
            org="Gothenburg Transit Authority",
            start="2025-06-02",
            end="2025-09-12",
            description="Ridership dashboards and data-quality checks for open data.",
            skills=(
                SkillSpec("data-analysis", "primary", 6),
                SkillSpec("writing", "secondary", 5),
            ),
            achievements=(
                AchievementSpec(
                    "Automated a ridership report that took a day by hand",
                    {"kind": "time_saved", "value": 6, "unit": "hours_per_week"},
                ),
            ),
        ),
    ),
    education=(
        EducationSpec(
            key="bsc",
            institution="Northshore University",
            program="BSc Environmental Science",
            level="bachelor",
            start="2017-09-01",
            end="2020-06-15",
            focus_subjects=("science-earth", "mathematics"),
            description="Thesis on urban air-quality sensor placement.",
        ),
        EducationSpec(
            key="adult-data",
            institution="Växjö Adult Learning",
            program="Applied Data Analysis",
            level="vocational",
            start="2024-09-01",
            in_progress=True,
            focus_subjects=("technology-data",),
        ),
    ),
    certifications=(
        CertificationSpec(
            key="foda",
            name="Foundations of Data Analysis",
            issuer="Open Learning Institute",
            issued="2025-03-01",
            credential_id="DEMO-CERT-0001",
        ),
    ),
    honors=(
        HonorSpec(
            key="deans-list",
            title="Dean's list (fictional)",
            issuer="Northshore University",
            date="2019-06-01",
        ),
    ),
    cvs=(CvSpec(key="resume", title="Wren Ashgrove — CV"),),
    applications=(
        ApplicationSpec("data-analyst", "interview", 20, "Second round with the team."),
        ApplicationSpec("dev-starter", "applied", 5, ""),
    ),
)

PIPER = UserSpec(
    key="piper",
    full_name="Piper Moss",
    email=f"piper.moss{DEMO_EMAIL_DOMAIN}",
    profiles=(
        ProfileSpec(
            key="default",
            name="Default",
            color="#f59e0b",
            is_default=True,
            basics={
                "birth_year": 2004,
                "education_level": "bachelor",
                "grade": "Year 2",
                "career_stage": "student",
                "onboarding_path": "target",
                "country": "Sweden",
                "city": "Växjö",
                "timezone": "Europe/Stockholm",
                "full_name": "Piper Moss",
                "email": f"piper.moss{DEMO_EMAIL_DOMAIN}",
                "phone": "+46 70 000 0002",
                "headline": "Environmental engineering student",
            },
            academics={
                "favorite_subjects": [
                    {"key": "science-earth", "weight": 5},
                    {"key": "science-chemistry", "weight": 4},
                ],
                "languages": [
                    {"code": "en", "level": "advanced"},
                    {"code": "it", "level": "basic"},
                ],
            },
            hobbies=(
                {"key": "sports-fitness", "label": "Rowing", "weight": 4},
                {"key": "arts-music", "label": "Choir", "weight": 2},
            ),
            likes=({"key": "society-environment", "label": "Fieldwork", "weight": 5},),
            dislikes=({"key": None, "label": "Desk-only weeks", "weight": 3},),
            aspirations=(
                {
                    "label": "Summer internship in water or waste systems",
                    "tag_keys": ["society-environment"],
                    "notes": "Open to fieldwork.",
                },
            ),
            work_preferences={
                "teamwork": 5,
                "environment": 4,
                "structure": 3,
                "pace": 3,
                "leadership": 3,
                "remote_ok": False,
                "focus_areas": ["things", "data"],
                "salary_priority": 2,
                "stability_priority": 3,
                "physical_activity": "active",
                "creativity_priority": 3,
            },
            constraints={
                "physical_conditions": [],
                "willing_to_relocate": True,
                "hours_available_per_week": 20,
                "commute_radius_km": 20,
            },
            preferences={
                "scoring_weights": {
                    "skills": 3,
                    "location": 4,
                    "experience": 2,
                    "education": 4,
                    "interests": 4,
                    "values": 3,
                }
            },
        ),
        ProfileSpec(
            key="internships",
            name="Internships",
            color="#22d3ee",
            basics={
                "birth_year": 2004,
                "education_level": "bachelor",
                "grade": "Year 2",
                "career_stage": "student",
                "country": "Sweden",
                "city": "Växjö",
                "timezone": "Europe/Stockholm",
                "full_name": "Piper Moss",
                "email": f"piper.moss{DEMO_EMAIL_DOMAIN}",
                "headline": "Seeking summer 2026 internships",
            },
            aspirations=(
                {
                    "label": "Internship with lab or field sampling",
                    "tag_keys": ["science-earth"],
                    "notes": "",
                },
            ),
            constraints={
                "physical_conditions": [],
                "willing_to_relocate": True,
                "hours_available_per_week": 40,
                "commute_radius_km": 100,
            },
        ),
    ),
    experiences=(
        ExperienceSpec(
            key="river-cleanup",
            kind="volunteer",
            title="River Cleanup Coordinator",
            org="Bluebank River Trust",
            start="2023-05-01",
            end="2024-09-30",
            description="Volunteer coordination and safety briefings along the river.",
            skills=(
                SkillSpec("teamwork", "primary", 6),
                SkillSpec("organization", "secondary", 5),
                SkillSpec("public-speaking", "secondary", 4),
            ),
            achievements=(
                AchievementSpec(
                    "Organised 8 river cleanups with 120 volunteers",
                    {"kind": "scale", "value": 120, "unit": "volunteers"},
                ),
                AchievementSpec(
                    "Wrote the safety briefings used at every event",
                    None,
                ),
            ),
        ),
        ExperienceSpec(
            key="solar-dryer",
            kind="project",
            title="Solar Crop Dryer Prototype",
            org="",
            start="2024-10-01",
            end="2025-04-30",
            description="Course project: a low-cost solar dryer for small farms.",
            skills=(
                SkillSpec("engineering-design", "primary", 5),
                SkillSpec("mechanical-repair", "secondary", 4),
            ),
            achievements=(
                AchievementSpec(
                    "Built two working prototypes with a 3-student team",
                    {"kind": "scale", "value": 2, "unit": "units"},
                ),
                AchievementSpec(
                    "Cut drying time in the lab trial",
                    {"kind": "quality", "value": 30, "unit": "percent"},
                ),
            ),
        ),
        ExperienceSpec(
            key="barista",
            kind="job",
            title="Weekend Barista",
            org="Kettle & Crumb Cafe",
            start="2023-09-01",
            open_ended=True,
            description="Weekend shifts through term time.",
            skills=(
                SkillSpec("customer-service", "primary", 5),
                SkillSpec("teamwork", "secondary", 5),
            ),
            achievements=(
                AchievementSpec(
                    "Maintained a 4.8 average customer rating",
                    {"kind": "quality", "value": 4.8, "unit": "rating"},
                ),
            ),
        ),
    ),
    education=(
        EducationSpec(
            key="beng",
            institution="Westmoor Polytechnic",
            program="BEng Environmental Engineering",
            level="bachelor",
            start="2023-09-01",
            end="2027-06-30",
            in_progress=True,
            focus_subjects=("science-earth", "science-chemistry"),
        ),
        EducationSpec(
            key="sixth-form",
            institution="St. Ansgar Sixth Form",
            program="Science Track",
            level="high_school",
            start="2020-08-20",
            end="2023-06-10",
            focus_subjects=("science-chemistry", "science-biology"),
        ),
    ),
    cvs=(CvSpec(key="resume", title="Piper Moss — CV"),),
    applications=(
        ApplicationSpec("sustainability-intern", "applied", 3, "Take-home due soon."),
        ApplicationSpec("ux-junior", "applied", 10, ""),
    ),
)

SOL = UserSpec(
    key="sol",
    full_name="Sol Marchetti",
    email=f"sol.marchetti{DEMO_EMAIL_DOMAIN}",
    profiles=(
        ProfileSpec(
            key="default",
            name="Default",
            color="#a855f7",
            is_default=True,
            basics={
                "birth_year": 1984,
                "education_level": "vocational",
                "career_stage": "returning",
                "onboarding_path": "browse",
                "country": "Sweden",
                "city": "Trollhättan",
                "timezone": "Europe/Stockholm",
                "full_name": "Sol Marchetti",
                "email": f"sol.marchetti{DEMO_EMAIL_DOMAIN}",
                "phone": "+46 70 000 0003",
                "headline": "Robotics technician returning after a career break",
                "links": [
                    {
                        "kind": "other",
                        "url": "https://demo.career.local/portfolio/sol-marchetti",
                        "label": "Portfolio",
                    }
                ],
            },
            academics={
                "favorite_subjects": [
                    {"key": "technology-robots", "weight": 5},
                    {"key": "hands-electricity", "weight": 4},
                ],
                "languages": [
                    {"code": "en", "level": "intermediate"},
                    {"code": "it", "level": "native"},
                ],
            },
            hobbies=({"key": "hands-crafts", "label": "Furniture repair", "weight": 4},),
            likes=({"key": "hands-machines", "label": "Machine shops", "weight": 5},),
            dislikes=({"key": None, "label": "Night shifts", "weight": 4},),
            aspirations=(
                {
                    "label": "Return to industrial robotics maintenance",
                    "tag_keys": ["technology-robots"],
                    "notes": "Prefers 4-day weeks.",
                },
            ),
            work_preferences={
                "teamwork": 4,
                "environment": 2,
                "structure": 4,
                "pace": 2,
                "leadership": 3,
                "remote_ok": False,
                "focus_areas": ["things"],
                "salary_priority": 3,
                "stability_priority": 5,
                "physical_activity": "moderate",
                "creativity_priority": 2,
            },
            constraints={
                "physical_conditions": [],
                "willing_to_relocate": False,
                "hours_available_per_week": 32,
                "shift_tolerance": "occasional",
                "commute_radius_km": 40,
            },
            preferences={
                "scoring_weights": {
                    "skills": 5,
                    "location": 4,
                    "experience": 4,
                    "education": 2,
                    "interests": 3,
                    "values": 3,
                }
            },
        ),
        ProfileSpec(
            key="returnship",
            name="Returnship",
            color="#f43f5e",
            basics={
                "birth_year": 1984,
                "education_level": "vocational",
                "career_stage": "returning",
                "country": "Sweden",
                "city": "Trollhättan",
                "timezone": "Europe/Stockholm",
                "full_name": "Sol Marchetti",
                "email": f"sol.marchetti{DEMO_EMAIL_DOMAIN}",
                "headline": "Returnship programmes in automation",
            },
            aspirations=(
                {
                    "label": "Structured returnship with retraining",
                    "tag_keys": ["technology-robots"],
                    "notes": "Safety certification refresh is planned.",
                },
            ),
            work_preferences={
                "teamwork": 4,
                "environment": 2,
                "structure": 5,
                "pace": 2,
                "leadership": 2,
                "remote_ok": False,
                "focus_areas": ["things", "people"],
                "salary_priority": 2,
                "stability_priority": 5,
                "physical_activity": "moderate",
                "creativity_priority": 2,
            },
        ),
    ),
    experiences=(
        ExperienceSpec(
            key="halcyon",
            kind="job",
            title="Robotics Maintenance Technician",
            org="Halcyon Robotics",
            start="2015-03-02",
            end="2022-11-30",
            description="Preventive and corrective maintenance on assembly cells.",
            skills=(
                SkillSpec("mechanical-repair", "primary", 8),
                SkillSpec("electronics", "primary", 7),
                SkillSpec("dexterity", "secondary", 7),
            ),
            achievements=(
                AchievementSpec(
                    "Reduced line downtime with a preventive checklist",
                    {"kind": "quality", "value": 35, "unit": "percent"},
                ),
                AchievementSpec(
                    "Mentored 4 apprentices",
                    {"kind": "scale", "value": 4, "unit": "people"},
                ),
            ),
        ),
        ExperienceSpec(
            key="vittoria",
            kind="job",
            title="Line Mechanic",
            org="Vittoria Packaging",
            start="2011-01-10",
            end="2015-02-20",
            description="Sealing-line changeovers and mechanical setup.",
            skills=(
                SkillSpec("mechanical-repair", "primary", 6),
                SkillSpec("attention-to-detail", "secondary", 6),
            ),
            achievements=(
                AchievementSpec(
                    "Kept the sealing line at high first-pass yield",
                    {"kind": "quality", "value": 98, "unit": "percent"},
                ),
            ),
        ),
        ExperienceSpec(
            key="repair-cafe",
            kind="volunteer",
            title="Repair Café Volunteer",
            org="Trollhättan Repair Café",
            start="2023-04-01",
            open_ended=True,
            description="Guiding visitors through safe small-appliance repairs.",
            skills=(
                SkillSpec("teaching", "secondary", 5),
                SkillSpec("empathy", "secondary", 5),
                SkillSpec("mechanical-repair", "primary", 7),
            ),
            achievements=(
                AchievementSpec(
                    "Guided 60 visitors through safe repairs",
                    {"kind": "scale", "value": 60, "unit": "repairs"},
                ),
            ),
        ),
    ),
    education=(
        EducationSpec(
            key="volta",
            institution="Istituto Volta",
            program="Industrial Maintenance",
            level="vocational",
            start="2008-09-01",
            end="2011-06-30",
            focus_subjects=("hands-machines", "hands-electricity"),
        ),
    ),
    certifications=(
        CertificationSpec(
            key="automation-tech",
            name="Certified Automation Technician",
            issuer="Global Automation Guild",
            issued="2019-05-01",
            expires="2027-05-01",
            credential_id="DEMO-CERT-0002",
        ),
    ),
    cvs=(CvSpec(key="resume", title="Sol Marchetti — CV"),),
    applications=(
        ApplicationSpec("dev-starter", "offer", 30, "Fictional offer — deciding."),
        ApplicationSpec("data-analyst", "applied", 2, ""),
    ),
)

DEMO_USERS: tuple[UserSpec, ...] = (WREN, PIPER, SOL)

# The one CV block layout every seeded draft uses — the same shape as the
# builder's FALLBACK_CONTENT (app/services/cv_builder_service.py): items
# resolve from the persona's experiences/education at render time.
# Block placement mirrors the demo template (teal-sidebar): the profile
# summary, skills, languages and interests fill the sidepanel; the header
# and dated lists stay in the main column. `area` falls back to "main"
# when a non-sidebar template is applied later (cv_renderer), so this
# stays valid across template switches.
_CV_BLOCKS: list[dict] = [
    {"kind": "header", "area": "main"},
    {"kind": "summary", "area": "sidebar", "props": {"title": "Profile", "max_chars": 500}},
    {"kind": "items", "area": "main", "props": {"title": "Work Experience", "source_key": "experience"}},
    {"kind": "items", "area": "main", "props": {"title": "Education", "source_key": "education"}},
    {"kind": "skills", "area": "sidebar", "props": {"title": "Skills", "show_levels": True, "max_items": 8}},
    {"kind": "languages", "area": "sidebar", "props": {"title": "Languages", "display": "list", "show_cefr": True}},
    {"kind": "interests", "area": "sidebar", "props": {"title": "Interests", "max_items": 6}},
]


# --------------------------------------------------------------------------
# Guard rails — refuse anything that is not a demo target/instance.
# --------------------------------------------------------------------------


@dataclass
class Target:
    url: str
    demo_dir: Path | None


def ensure_demo_target(url: str, demo_dir: Path | None) -> Target:
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend == "sqlite":
        if demo_dir is None:
            raise Refusal(
                "SQLite target without an explicit --demo-dir — refusing to seed "
                "anything but an isolated demo data dir (identity-auth §13)."
            )
        demo_root = demo_dir.resolve()
        database = Path(parsed.database or "")
        db_path = (database if database.is_absolute() else Path.cwd() / database).resolve()
        if demo_root != db_path and demo_root not in db_path.parents:
            raise Refusal(
                f"SQLite database {db_path} is not inside the demo data dir "
                f"{demo_root} — refusing (identity-auth §13)."
            )
        demo_root.mkdir(parents=True, exist_ok=True)
        return Target(url=url, demo_dir=demo_root)
    if backend == "postgresql":
        name = parsed.database or ""
        if not name.endswith("_demo"):
            raise Refusal(
                f"target database {name!r} is not a demo database — expected a "
                "name ending '_demo' (deployment.md: neuronection_career_demo); refusing "
                "(identity-auth §13)."
            )
        return Target(url=url, demo_dir=demo_dir)
    raise Refusal(f"unsupported database backend {backend!r} — refusing.")


def ensure_demo_instance(session: Session, *, init_demo: bool) -> str:
    row = session.get(InstanceSetting, "demo_mode")
    if row is not None and row.value == "true":
        return "demo_mode=true (instance_settings)"
    if not init_demo:
        raise Refusal(
            "instance_settings.demo_mode is not 'true' — refusing to seed a "
            "non-demo instance (identity-auth §13). Use --init-demo to "
            "initialize an EMPTY demo database."
        )
    if not _instance_is_empty(session):
        raise Refusal(
            "--init-demo requires an EMPTY demo database (found existing "
            "instance data) — refusing to re-flag an existing instance as demo "
            "(identity-auth §13)."
        )
    session.add(InstanceSetting(key="demo_mode", value="true"))
    session.commit()
    return "demo_mode=true (--init-demo)"


def _instance_is_empty(session: Session) -> bool:
    if session.get(InstanceSetting, "demo_mode") is not None:
        return False
    if session.get(InstanceSetting, "auth_mode") is not None:
        return False
    for model in (User, Profile):
        if session.scalars(select(model).limit(1)).first() is not None:
            return False
    return True


# --------------------------------------------------------------------------
# Reset — remove previously seeded demo rows (and the demo principal's),
# never anything else. Dependency-ordered; reference catalogs untouched.
# --------------------------------------------------------------------------


def _demo_user_ids(session: Session) -> list[str]:
    wanted = [demo_id("user", spec.key) for spec in DEMO_USERS] + [DEMO_PRINCIPAL_ID]
    return [
        str(row)
        for row in session.scalars(select(User.id).where(User.id.in_(wanted))).all()
    ]


def purge_seeded(session: Session) -> dict[str, int]:
    user_ids = _demo_user_ids(session)
    empty = {"users": 0}
    if not user_ids:
        return empty
    counts: dict[str, int] = {"users": len(user_ids)}

    def run(statement: Any) -> int:
        result = session.execute(statement)
        return int(result.rowcount or 0)

    profile_ids = list(
        session.scalars(select(Profile.id).where(Profile.user_id.in_(user_ids))).all()
    )
    experience_ids = list(
        session.scalars(
            select(ExperienceItem.id).where(ExperienceItem.user_id.in_(user_ids))
        ).all()
    )
    cv_ids = list(
        session.scalars(
            select(CvDocument.id).where(CvDocument.user_id.in_(user_ids))
        ).all()
    )
    posting_ids = list(
        session.scalars(
            select(JobPosting.id)
            .where(JobPosting.source_id == demo_id("source", DEMO_SOURCE_KEY))
        ).all()
    )

    run(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
    counts["applications"] = run(
        delete(PostingInteraction).where(PostingInteraction.user_id.in_(user_ids))
    )
    run(delete(PostingFit).where(PostingFit.user_id.in_(user_ids)))
    if posting_ids:
        run(delete(PostingSkill).where(PostingSkill.posting_id.in_(posting_ids)))
        run(
            delete(PostingInteraction).where(
                PostingInteraction.posting_id.in_(posting_ids)
            )
        )
    if cv_ids:
        from app.models.cv_model import CvVersion

        run(delete(CvVersion).where(CvVersion.cv_document_id.in_(cv_ids)))
        counts["cvs"] = run(delete(CvDocument).where(CvDocument.id.in_(cv_ids)))
    from app.models.experience_model import SkillEvidence

    run(delete(SkillEvidence).where(SkillEvidence.user_id.in_(user_ids)))
    if experience_ids:
        counts["achievements"] = run(
            delete(ExperienceAchievement).where(
                ExperienceAchievement.experience_id.in_(experience_ids)
            )
        )
        counts["skill_links"] = run(
            delete(ExperienceSkill).where(
                ExperienceSkill.experience_id.in_(experience_ids)
            )
        )
        counts["experiences"] = run(
            delete(ExperienceItem).where(ExperienceItem.id.in_(experience_ids))
        )
    counts["education"] = run(
        delete(EducationItem).where(EducationItem.user_id.in_(user_ids))
    )
    counts["certifications"] = run(
        delete(Certification).where(Certification.user_id.in_(user_ids))
    )
    counts["honors"] = run(
        delete(ProfileAchievement).where(ProfileAchievement.user_id.in_(user_ids))
    )
    if profile_ids:
        counts["profiles"] = run(delete(Profile).where(Profile.id.in_(profile_ids)))
    # The user row's DB-level ON DELETE CASCADE carries every remaining
    # user-scoped table (chats, notifications, documents, metrics…).
    run(delete(User).where(User.id.in_(user_ids)))
    if posting_ids:
        counts["postings"] = run(delete(JobPosting).where(JobPosting.id.in_(posting_ids)))
    run(delete(JobSource).where(JobSource.key == DEMO_SOURCE_KEY))
    session.commit()
    return counts


# --------------------------------------------------------------------------
# Seeding — get-or-create everything, so re-running changes no counts.
# --------------------------------------------------------------------------


@dataclass
class SeedCounts:
    totals: dict[str, int] = field(default_factory=dict)
    created: dict[str, int] = field(default_factory=dict)

    def add(self, entity: str, is_new: bool) -> None:
        self.totals[entity] = self.totals.get(entity, 0) + 1
        if is_new:
            self.created[entity] = self.created.get(entity, 0) + 1


def _demo_password_hash() -> str:
    from nx_auth.passwords import hash_password

    return hash_password(DEMO_PASSWORD)


def _sections(spec: ProfileSpec) -> dict[str, Any]:
    """Validated profile JSON sections (never hand-rolled shapes)."""
    from app.schemas.profile import (
        AcademicsSection,
        AspirationItem,
        BasicSection,
        ConstraintsSection,
        FavoriteSubject,
        HobbyItem,
        LanguageSkill,
        LikeDislikeItem,
        PreferencesSection,
        WorkPreferencesSection,
    )

    academics = dict(spec.academics)
    work = dict(spec.work_preferences)
    return {
        "basics": BasicSection(**spec.basics).model_dump(mode="json"),
        "academics": AcademicsSection(
            favorite_subjects=[
                FavoriteSubject(**item) for item in academics.get("favorite_subjects", [])
            ],
            languages=[LanguageSkill(**item) for item in academics.get("languages", [])],
        ).model_dump(mode="json"),
        "hobbies": [HobbyItem(**item).model_dump(mode="json") for item in spec.hobbies],
        "likes": [LikeDislikeItem(**item).model_dump(mode="json") for item in spec.likes],
        "dislikes": [
            LikeDislikeItem(**item).model_dump(mode="json") for item in spec.dislikes
        ],
        "aspirations": [
            AspirationItem(**item).model_dump(mode="json") for item in spec.aspirations
        ],
        "work_preferences": WorkPreferencesSection(**work).model_dump(mode="json"),
        "constraints": ConstraintsSection(**spec.constraints).model_dump(mode="json"),
        "preferences": PreferencesSection(**spec.preferences).model_dump(mode="json"),
    }


def _ensure_user(session: Session, spec: UserSpec, password_hash: str) -> tuple[User, bool]:
    """User rows are created here (not via the auth kit's store) so the
    whole workspace lands in one transaction — with the §6 Default
    profile provisioned in the same flush."""
    row = session.get(User, demo_id("user", spec.key))
    if row is not None:
        return row, False
    email = spec.email.lower().strip()
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        return existing, False
    row = User(
        id=demo_id("user", spec.key),
        email=email,
        password_hash=password_hash,
        full_name=spec.full_name,
        is_admin=spec.is_admin,
    )
    session.add(row)
    session.flush()
    return row, True


def _ensure_profile(session: Session, user: User, spec: ProfileSpec) -> tuple[Profile, bool]:
    profile_id = demo_id("profile", f"{user.id}:{spec.key}")
    row = session.get(Profile, profile_id)
    if row is not None:
        return row, False
    existing = session.scalar(
        select(Profile).where(Profile.user_id == user.id, Profile.name == spec.name)
    )
    if existing is not None:
        return existing, False
    sections = _sections(spec)
    row = Profile(
        id=profile_id,
        user_id=user.id,
        name=spec.name,
        is_default=spec.is_default,
        color=spec.color,
        basics=sections["basics"],
        academics=sections["academics"],
        hobbies=sections["hobbies"],
        likes=sections["likes"],
        dislikes=sections["dislikes"],
        aspirations=sections["aspirations"],
        work_preferences=sections["work_preferences"],
        constraints=sections["constraints"],
        preferences=sections["preferences"],
    )
    session.add(row)
    session.flush()
    return row, True


def _skill_id(session: Session, key: str) -> Any | None:
    row = session.scalar(select(Skill.id).where(Skill.key == key))
    return row if row is not None else None


def _ensure_experience(
    session: Session, user: User, spec: ExperienceSpec, counts: SeedCounts
) -> tuple[ExperienceItem, bool]:
    row = session.get(ExperienceItem, demo_id("exp", f"{user.id}:{spec.key}"))
    if row is not None:
        return row, False
    row = ExperienceItem(
        id=demo_id("exp", f"{user.id}:{spec.key}"),
        user_id=user.id,
        kind=spec.kind,
        title=spec.title,
        org_name=spec.org,
        start=date.fromisoformat(spec.start) if spec.start else None,
        end=date.fromisoformat(spec.end) if spec.end else None,
        open_ended=spec.open_ended,
        description=spec.description,
        source="self_report",
        status="active",
    )
    session.add(row)
    session.flush()
    for skill_spec in spec.skills:
        skill_id = _skill_id(session, skill_spec.key)
        if skill_id is None:
            continue  # reference catalog gap — never invent catalog rows
        session.add(
            ExperienceSkill(
                id=demo_id("skill_link", f"{row.id}:{skill_spec.key}"),
                experience_id=row.id,
                skill_id=skill_id,
                role_in_item=skill_spec.role,
                level_claim=skill_spec.level,
            )
        )
        counts.add("skill_links", True)
    for index, achievement in enumerate(spec.achievements):
        session.add(
            ExperienceAchievement(
                id=demo_id("achievement", f"{row.id}:{index}"),
                experience_id=row.id,
                text=achievement.text,
                metric=achievement.metric,
            )
        )
        counts.add("achievements", True)
    session.flush()
    return row, True


def _ensure_education(session: Session, user: User, spec: EducationSpec) -> tuple[EducationItem, bool]:
    row = session.get(EducationItem, demo_id("edu", f"{user.id}:{spec.key}"))
    if row is not None:
        return row, False
    row = EducationItem(
        id=demo_id("edu", f"{user.id}:{spec.key}"),
        user_id=user.id,
        institution=spec.institution,
        org_name=spec.institution,
        program=spec.program,
        level=spec.level,
        start=date.fromisoformat(spec.start) if spec.start else None,
        end=date.fromisoformat(spec.end) if spec.end else None,
        in_progress=spec.in_progress,
        focus_subjects=list(spec.focus_subjects),
        description=spec.description,
        source="self_report",
        status="active",
    )
    session.add(row)
    session.flush()
    return row, True


def _ensure_certification(
    session: Session, user: User, spec: CertificationSpec
) -> tuple[Certification, bool]:
    row = session.get(Certification, demo_id("cert", f"{user.id}:{spec.key}"))
    if row is not None:
        return row, False
    row = Certification(
        id=demo_id("cert", f"{user.id}:{spec.key}"),
        user_id=user.id,
        name=spec.name,
        issuer=spec.issuer,
        issued=date.fromisoformat(spec.issued) if spec.issued else None,
        expires=date.fromisoformat(spec.expires) if spec.expires else None,
        credential_id=spec.credential_id,
        link=f"https://demo.career.local/certs/{spec.credential_id}"
        if spec.credential_id
        else "",
        source="self_report",
        status="active",
    )
    session.add(row)
    session.flush()
    return row, True


def _ensure_honor(session: Session, user: User, spec: HonorSpec) -> tuple[ProfileAchievement, bool]:
    row = session.get(ProfileAchievement, demo_id("honor", f"{user.id}:{spec.key}"))
    if row is not None:
        return row, False
    row = ProfileAchievement(
        id=demo_id("honor", f"{user.id}:{spec.key}"),
        user_id=user.id,
        kind="honor",
        title=spec.title,
        issuer=spec.issuer,
        date=date.fromisoformat(spec.date) if spec.date else None,
        detail=spec.detail,
        source="self_report",
        status="active",
    )
    session.add(row)
    session.flush()
    return row, True


def _bank_template_id(session: Session, key: str) -> uuid.UUID | None:
    """Resolve a reference CV-template id by bank key (ids are generated by
    the reference seeder, so demo rows must look them up, not hardcode)."""
    from sqlalchemy import select

    return session.execute(
        select(CvTemplate.id).where(
            CvTemplate.key == key,
            CvTemplate.author_key == "bank",
        )
    ).scalar()


def _ensure_cv(session: Session, user: User, spec: CvSpec) -> tuple[CvDocument, bool]:
    row = session.get(CvDocument, demo_id("cv", f"{user.id}:{spec.key}"))
    if row is not None:
        return row, False
    row = CvDocument(
        id=demo_id("cv", f"{user.id}:{spec.key}"),
        user_id=user.id,
        title=spec.title,
        kind=spec.kind,
        language="en",
        page_size="a4",
        max_pages=1,
        status="draft",
        # Demo tours show a modern sidebar-styled CV (bank template resolved
        # by key; the reference catalogs are ensured before this runs).
        template_id=_bank_template_id(session, "teal-sidebar"),
        working_content={"blocks": [dict(block) for block in _CV_BLOCKS], "overrides": {}},
        context={},
    )
    session.add(row)
    session.flush()
    return row, True


def _posting_content_hash(spec: PostingSpec) -> str:
    payload = json.dumps(
        {
            "title": spec.title,
            "org": spec.org,
            "description": spec.description,
            "city": spec.city,
            "country": spec.country,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_postings(session: Session, counts: SeedCounts) -> None:
    """The fictional posting pool (and its fictional source)."""
    source_id = demo_id("source", DEMO_SOURCE_KEY)
    if session.get(JobSource, source_id) is None:
        session.add(
            JobSource(
                id=source_id,
                key=DEMO_SOURCE_KEY,
                connector_key="manual",
                config={"demo": True},
                enabled=True,
                sync_state={},
            )
        )
        session.flush()
    counts.totals["postings"] = 0
    for spec in DEMO_POSTINGS:
        row = session.get(JobPosting, demo_id("posting", spec.key))
        if row is not None:
            counts.add("postings", False)
            continue
        catalog_job_id = None
        if spec.catalog_job_code:
            catalog_job = session.scalar(
                select(Job.id).where(Job.code == spec.catalog_job_code)
            )
            catalog_job_id = catalog_job if catalog_job is not None else None
        now = datetime.now(timezone.utc)
        session.add(
            JobPosting(
                id=demo_id("posting", spec.key),
                source_id=source_id,
                external_id=spec.external_id,
                ref=spec.ref,
                title=spec.title,
                org=spec.org,
                location={
                    "city": spec.city,
                    "country": spec.country,
                    "remote": spec.remote,
                },
                url=f"https://demo.career.local/postings/{spec.ref}",
                seniority=spec.seniority,
                employment_type=spec.employment_type,
                onsite_policy=spec.onsite_policy,
                education_level=spec.education_level,
                salary_currency="SEK" if spec.salary_min is not None else None,
                salary_min=spec.salary_min,
                salary_max=spec.salary_max,
                salary_period="year" if spec.salary_min is not None else None,
                posted_at=now - timedelta(days=spec.posted_days_ago),
                expires_at=now + timedelta(days=spec.expires_in_days),
                content_hash=_posting_content_hash(spec),
                raw={"demo": True},
                posting_facts={},
                status="mapped" if catalog_job_id is not None else "new",
                catalog_job_id=catalog_job_id,
                mapping_method="manual" if catalog_job_id is not None else None,
                mapping_confidence=1.0 if catalog_job_id is not None else None,
                mapping_reason="demo seed (fictional vacancy)"
                if catalog_job_id is not None
                else "",
            )
        )
        counts.add("postings", True)
    session.flush()


def _ensure_application(
    session: Session, user: User, spec: ApplicationSpec, counts: SeedCounts
) -> None:
    posting_id = demo_id("posting", spec.posting_key)
    if session.get(JobPosting, posting_id) is None:
        return
    row = session.get(PostingInteraction, demo_id("app", f"{user.id}:{spec.posting_key}"))
    if row is not None:
        counts.add("applications", False)
        return
    applied_at = datetime.now(timezone.utc) - timedelta(days=spec.applied_days_ago)
    session.add(
        PostingInteraction(
            id=demo_id("app", f"{user.id}:{spec.posting_key}"),
            user_id=user.id,
            posting_id=posting_id,
            seen_at=applied_at - timedelta(days=1),
            saved_at=applied_at - timedelta(hours=6),
            applied_at=applied_at,
            applied_via_url=f"https://demo.career.local/postings/{spec.posting_key}/apply",
            stage=spec.stage,
            notes=spec.notes,
        )
    )
    counts.add("applications", True)
    session.flush()


def seed_workspace(session: Session) -> SeedCounts:
    counts = SeedCounts()
    _ensure_postings(session, counts)
    password_hash = _demo_password_hash()
    for user_spec in DEMO_USERS:
        user, user_new = _ensure_user(session, user_spec, password_hash)
        counts.add("users", user_new)
        for profile_spec in user_spec.profiles:
            _, profile_new = _ensure_profile(session, user, profile_spec)
            counts.add("profiles", profile_new)
        for experience_spec in user_spec.experiences:
            _, experience_new = _ensure_experience(session, user, experience_spec, counts)
            counts.add("experiences", experience_new)
        for education_spec in user_spec.education:
            _, education_new = _ensure_education(session, user, education_spec)
            counts.add("education", education_new)
        for certification_spec in user_spec.certifications:
            _, certification_new = _ensure_certification(
                session, user, certification_spec
            )
            counts.add("certifications", certification_new)
        for honor_spec in user_spec.honors:
            _, honor_new = _ensure_honor(session, user, honor_spec)
            counts.add("honors", honor_new)
        for cv_spec in user_spec.cvs:
            _, cv_new = _ensure_cv(session, user, cv_spec)
            counts.add("cvs", cv_new)
        for application_spec in user_spec.applications:
            _ensure_application(session, user, application_spec, counts)
    session.commit()
    return counts


_ENTITIES = (
    "users",
    "profiles",
    "experiences",
    "skill_links",
    "achievements",
    "education",
    "certifications",
    "honors",
    "cvs",
    "postings",
    "applications",
)


def scope_totals(session: Session) -> dict[str, int]:
    """Row counts for the seeded scope — stable across idempotent runs."""
    user_ids = _demo_user_ids(session)
    if not user_ids:
        return {entity: 0 for entity in _ENTITIES}
    profile_ids = list(
        session.scalars(select(Profile.id).where(Profile.user_id.in_(user_ids))).all()
    )
    experience_ids = list(
        session.scalars(
            select(ExperienceItem.id).where(ExperienceItem.user_id.in_(user_ids))
        ).all()
    )
    cv_ids = list(
        session.scalars(select(CvDocument.id).where(CvDocument.user_id.in_(user_ids))).all()
    )
    posting_ids = list(
        session.scalars(
            select(JobPosting.id)
            .where(JobPosting.source_id == demo_id("source", DEMO_SOURCE_KEY))
        ).all()
    )

    def count(statement: Any) -> int:
        return int(session.scalar(statement) or 0)

    return {
        "users": count(select(func.count()).select_from(User).where(User.id.in_(user_ids))),
        "profiles": count(
            select(func.count()).select_from(Profile).where(Profile.user_id.in_(user_ids))
        ),
        "experiences": count(
            select(func.count())
            .select_from(ExperienceItem)
            .where(ExperienceItem.id.in_(experience_ids))
        )
        if experience_ids
        else 0,
        "skill_links": count(
            select(func.count())
            .select_from(ExperienceSkill)
            .where(ExperienceSkill.experience_id.in_(experience_ids))
        )
        if experience_ids
        else 0,
        "achievements": count(
            select(func.count())
            .select_from(ExperienceAchievement)
            .where(ExperienceAchievement.experience_id.in_(experience_ids))
        )
        if experience_ids
        else 0,
        "education": count(
            select(func.count())
            .select_from(EducationItem)
            .where(EducationItem.user_id.in_(user_ids))
        ),
        "certifications": count(
            select(func.count())
            .select_from(Certification)
            .where(Certification.user_id.in_(user_ids))
        ),
        "honors": count(
            select(func.count())
            .select_from(ProfileAchievement)
            .where(ProfileAchievement.user_id.in_(user_ids))
        ),
        "cvs": count(
            select(func.count()).select_from(CvDocument).where(CvDocument.id.in_(cv_ids))
        )
        if cv_ids
        else 0,
        "postings": count(
            select(func.count())
            .select_from(JobPosting)
            .where(JobPosting.id.in_(posting_ids))
        )
        if posting_ids
        else 0,
        "applications": count(
            select(func.count())
            .select_from(PostingInteraction)
            .where(PostingInteraction.user_id.in_(user_ids))
        ),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="seed-demo.py",
        description=(
            "Seed synthetic demo data into a demo instance (identity-auth §13). "
            "Synthetic-only; refuses any non-demo target or instance."
        ),
    )
    parser.add_argument(
        "--database-url",
        help="target URL (else DATABASE_URL / Settings; explicit URL wins)",
    )
    parser.add_argument(
        "--demo-dir",
        type=Path,
        help="the isolated demo data dir (required for SQLite targets)",
    )
    parser.add_argument(
        "--init-demo",
        action="store_true",
        help="initialize demo_mode=true on an EMPTY demo database",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="remove previously seeded demo rows (and the demo principal's), then reseed",
    )
    return parser.parse_args(argv)


def resolve_target(args: argparse.Namespace) -> Target:
    # Explicit --database-url wins; else an explicit --demo-dir selects the
    # isolated SQLite target inside it (the ambient DATABASE_URL must never
    # hijack a declared demo workspace); else the ambient/Settings URL —
    # which the target guard then judges.
    explicit = args.database_url
    demo_dir: Path | None = args.demo_dir
    if explicit is None and demo_dir is not None:
        url = f"sqlite:///{demo_dir / 'career.sqlite3'}"
    elif explicit is not None:
        url = explicit
    else:
        url = os.environ.get("DATABASE_URL") or None
        if url is None:
            from app.core.config import Settings

            url = Settings().DATABASE_URL
    return ensure_demo_target(url, demo_dir)


def _async_url(url: str) -> str:
    """The target through the async driver alembic + app.seeds.run use."""
    driver = {"postgresql": "postgresql+asyncpg", "sqlite": "sqlite+aiosqlite"}
    parsed = make_url(url)
    return parsed.set(drivername=driver[parsed.get_backend_name()]).render_as_string(
        hide_password=False
    )


def _sync_url(url: str) -> str:
    """The target through the sync driver this script seeds with."""
    driver = {"postgresql": "postgresql+psycopg", "sqlite": "sqlite"}
    parsed = make_url(url)
    return parsed.set(drivername=driver[parsed.get_backend_name()]).render_as_string(
        hide_password=False
    )


def aim_app_at(url: str) -> str:
    """Point the app's own config at the target (env first — OS env wins)."""
    async_url = _async_url(url)
    os.environ["DATABASE_URL"] = async_url
    from app.core.config import settings

    settings.DATABASE_URL = async_url
    return async_url


def make_sync_engine(url: str):
    engine = create_engine(_sync_url(url))
    if make_url(url).get_backend_name() == "sqlite":
        def _fk_on(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        event.listen(engine, "connect", _fk_on)
    return engine


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")


def has_schema(engine: Any) -> bool:
    return "instance_settings" in inspect(engine).get_table_names()


def ensure_reference_catalog() -> None:
    """Ensure the REFERENCE starter catalogs exist (identity: reference
    data ≠ demo data — `backend/app/seeds/*` stays reference, this only
    runs its idempotent entry point so demo rows can link real skill ids)."""
    from app.seeds.run import run as run_reference_seed

    asyncio.run(run_reference_seed())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        target = resolve_target(args)
    except Refusal as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return EXIT_REFUSED
    engine = make_sync_engine(target.url)
    try:
        if not has_schema(engine) and not args.init_demo:
            print(
                "REFUSED: the target has no Career Assistant schema and --init-demo "
                "was not given — refusing to initialize anything but an explicitly "
                "declared empty demo database (identity-auth §13).",
                file=sys.stderr,
            )
            return EXIT_REFUSED
        aim_app_at(target.url)
        run_migrations()
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as session:
            try:
                mode = ensure_demo_instance(session, init_demo=args.init_demo)
            except Refusal as refusal:
                print(f"REFUSED: {refusal}", file=sys.stderr)
                return EXIT_REFUSED
            purged: dict[str, int] = {}
            if args.reset:
                purged = purge_seeded(session)
        # Reference catalogs only after every guard passed (reference data
        # ≠ demo data — ensured, never authored here). Own connection: the
        # async reference engine must not share SQLite write locks with an
        # open sync session.
        ensure_reference_catalog()
        with factory() as session:
            counts = seed_workspace(session)
            counts.totals.update(scope_totals(session))
    except Refusal as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return EXIT_REFUSED
    finally:
        engine.dispose()

    print("Demo seed complete — synthetic data only (identity-auth §13).")
    print(f"  instance: {mode}")
    print(f"  database: {target.url.split('@')[-1]}")
    if target.demo_dir is not None:
        print(f"  demo dir: {target.demo_dir}")
    if args.reset:
        removed = (
            ", ".join(f"{key}={value}" for key, value in sorted(purged.items()))
            or "nothing"
        )
        print(f"  reset: removed {removed}")
    for entity in _ENTITIES:
        total = counts.totals.get(entity, 0)
        created = counts.created.get(entity, 0)
        print(f"  {entity}: {total} ({created} created this run)")
    print(f"  demo users share the password: {DEMO_PASSWORD}")
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refusal as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        sys.exit(EXIT_REFUSED)
    except Exception as error:  # noqa: BLE001
        print(f"seed-demo.py failed: {error}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
