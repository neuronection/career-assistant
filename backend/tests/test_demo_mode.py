"""Demo mode (plan 16 P3e, identity-auth §13) through the real career surface.

The seeder (`scripts/seed-demo.py`) must refuse anything that is not a
demo target *and* a demo instance — loudly, non-zero — seed idempotent
synthetic-only content, and land rows nowhere but the demo instance.
Reference banks (`backend/app/seeds/*`) stay reference data; the job
catalog comes from the released seed pack (plan 224). The
public `GET /api/v1/instance/config` endpoint (product-owned) feeds the
SPA's "Demo — synthetic data" badge before login, and the kit's demo
rules hold through career's real app: the `demo` principal only on demo
instances, `demo` tokens rejected elsewhere (§18.11).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest
from httpx import ASGITransport

from app.core.config import settings
from tests.conftest import CleanJarClient, auth_kit, session_headers

# Every test here implements identity-auth §18.11 (demo principal/seeder
# refusal, §13) through career's real surface — the family drift gate.
pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
SEEDER = REPO_ROOT / "scripts" / "seed-demo.py"
DEMO_PRINCIPAL_ID = "00000000-0000-4000-8000-00000000d0e0"
SEED_DOMAIN = "@demo.career.local"

DEMO_COUNTS = {
    "users": 3,
    "profiles": 6,
    "experiences": 9,
    "skill_links": 23,
    "achievements": 14,
    "education": 5,
    "certifications": 2,
    "honors": 1,
    "cvs": 3,
    "postings": 14,
    "posting_skills": 54,
    "applications": 6,
    "demo_mode": 1,
}

# The captured/hero roles must each carry at least one mapped posting.
SEEDED_ROLE_CODES = {
    "accountant",
    "teacher",
    "nurse",
    "graphic-designer",
    "financial-analyst",
    "data-scientist",
    "software-developer",
    "marketing-specialist",
    "electrician",
    "chef",
}

SKILL_PRIORITIES = {"must_have", "nice_to_have", "bonus"}


def load_seeder() -> ModuleType:
    """Import the seeder for its static spec (no DB touched at import)."""
    spec = importlib.util.spec_from_file_location("career_seed_demo", SEEDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve their module by name while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SEED = load_seeder()
CATALOG_PACK = (
    BACKEND_DIR / "tests" / "fixtures" / "seed_packs" / "packs" / "neuronection" / "job-catalog"
)


def _pack_items(relative: str) -> list[dict]:
    envelope = json.loads((CATALOG_PACK / "items" / relative).read_text(encoding="utf-8"))
    return list(envelope["items"])


SKILL_KEYS = {item["key"] for item in _pack_items("skills/skills.json")}
CATALOG_JOB_CODES = {item["code"] for item in _pack_items("job_types/jobs.json")}


def run_seeder(*args: str) -> subprocess.CompletedProcess[str]:
    upload_dir = Path(tempfile.mkdtemp(prefix="career-demo-uploads-"))
    return subprocess.run(
        [sys.executable, str(SEEDER), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
        env={**os.environ, "CAREER_UPLOAD_DIR": str(upload_dir)},
    )


def demo_db(demo_dir: Path) -> Path:
    return demo_dir / "career.sqlite3"


def db_counts(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(database)
    try:
        counts: dict[str, int] = {}
        for table in (
            "users",
            "profiles",
            "experience_items",
            "experience_skills",
            "experience_achievements",
            "education_items",
            "certifications",
            "profile_achievements",
            "cv_documents",
            "job_postings",
            "posting_skills",
            "posting_interactions",
            "applications",
            "skills",
        ):
            counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        demo_flag = connection.execute(
            "SELECT value FROM instance_settings WHERE key = 'demo_mode'"
        ).fetchone()
        counts["demo_mode"] = 1 if demo_flag is not None and demo_flag[0] == "true" else 0
        return counts
    finally:
        connection.close()


def named_counts(counts: dict[str, int]) -> dict[str, int]:
    """The seeder's entity names → raw table counts."""
    return {
        "users": counts["users"],
        "profiles": counts["profiles"],
        "experiences": counts["experience_items"],
        "skill_links": counts["experience_skills"],
        "achievements": counts["experience_achievements"],
        "education": counts["education_items"],
        "certifications": counts["certifications"],
        "honors": counts["profile_achievements"],
        "cvs": counts["cv_documents"],
        "postings": counts["job_postings"],
        "posting_skills": counts["posting_skills"],
        "applications": counts["applications"],
        "demo_mode": counts["demo_mode"],
    }


# ---------------------------------------------------------------------------
# Guard rails — the seeder refuses anything that is not a demo instance.
# ---------------------------------------------------------------------------


def test_seeder_refuses_non_demo_targets(tmp_path: Path) -> None:
    postgres = run_seeder(
        "--database-url", "postgresql+psycopg://u:p@localhost:5432/neuronection_career"
    )
    assert postgres.returncode != 0
    assert postgres.returncode == 2
    assert "REFUSED" in postgres.stderr
    assert "_demo" in postgres.stderr

    sqlite_plain = run_seeder("--database-url", f"sqlite:///{tmp_path}/plain.sqlite3")
    assert sqlite_plain.returncode == 2
    assert "REFUSED" in sqlite_plain.stderr
    assert "--demo-dir" in sqlite_plain.stderr

    outside = run_seeder(
        "--database-url",
        f"sqlite:///{tmp_path}/outside.sqlite3",
        "--demo-dir",
        str(tmp_path / "demo-data"),
    )
    assert outside.returncode == 2
    assert "REFUSED" in outside.stderr

    unannounced = run_seeder("--demo-dir", str(tmp_path / "fresh-demo"))
    assert unannounced.returncode == 2
    assert "REFUSED" in unannounced.stderr
    assert "--init-demo" in unannounced.stderr

    # Nothing landed anywhere the guards refused.
    connection = sqlite3.connect(tmp_path / "outside.sqlite3")
    try:
        tables = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
        assert tables == 0
    finally:
        connection.close()


def test_seeder_refuses_non_demo_instance(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo-workspace"
    seeded = run_seeder("--demo-dir", str(demo_dir), "--init-demo")
    assert seeded.returncode == 0, seeded.stderr

    database = demo_db(demo_dir)
    connection = sqlite3.connect(database)
    try:
        connection.execute("UPDATE instance_settings SET value = 'false' WHERE key = 'demo_mode'")
        connection.commit()
    finally:
        connection.close()

    refused = run_seeder("--demo-dir", str(demo_dir))
    assert refused.returncode == 2
    assert "REFUSED" in refused.stderr
    assert "demo_mode" in refused.stderr

    # The refused run changed nothing.
    after = named_counts(db_counts(database))
    assert after["users"] == DEMO_COUNTS["users"]
    assert after["demo_mode"] == 0


def test_seeder_refuses_init_demo_on_non_empty_db(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo-workspace"
    seeded = run_seeder("--demo-dir", str(demo_dir), "--init-demo")
    assert seeded.returncode == 0, seeded.stderr

    database = demo_db(demo_dir)
    connection = sqlite3.connect(database)
    try:
        # An existing instance whose demo flag is gone is NOT empty —
        # --init-demo must never re-flag it (identity-auth §13).
        connection.execute("DELETE FROM instance_settings")
        connection.commit()
    finally:
        connection.close()

    refused = run_seeder("--demo-dir", str(demo_dir), "--init-demo")
    assert refused.returncode == 2
    assert "REFUSED" in refused.stderr
    assert "EMPTY" in refused.stderr


# ---------------------------------------------------------------------------
# Idempotent, synthetic-only seeding — into the demo instance and nowhere else.
# ---------------------------------------------------------------------------


def test_seeder_seeds_demo_workspace_idempotently_only_in_the_demo_instance(
    tmp_path: Path,
) -> None:
    demo_dir = tmp_path / "demo-workspace"
    first = run_seeder("--demo-dir", str(demo_dir), "--init-demo")
    assert first.returncode == 0, first.stderr
    assert "synthetic" in first.stdout.lower()

    database = demo_db(demo_dir)
    seeded = db_counts(database)
    assert named_counts(seeded) == DEMO_COUNTS

    second = run_seeder("--demo-dir", str(demo_dir))
    assert second.returncode == 0, second.stderr
    assert "(0 created this run)" in second.stdout
    assert db_counts(database) == seeded

    third = run_seeder("--demo-dir", str(demo_dir), "--reset")
    assert third.returncode == 0, third.stderr
    assert "reset: removed" in third.stdout
    after_reset = db_counts(database)
    assert named_counts(after_reset) == DEMO_COUNTS
    # Reference catalogs are not demo data — reset never touches them.
    assert after_reset["skills"] == seeded["skills"]
    assert after_reset["skills"] > 0

    connection = sqlite3.connect(database)
    try:
        emails = {row[0] for row in connection.execute("SELECT email FROM users")}
        assert emails == {
            f"wren.ashgrove{SEED_DOMAIN}",
            f"piper.moss{SEED_DOMAIN}",
            f"sol.marchetti{SEED_DOMAIN}",
        }
        sources = {row[0] for row in connection.execute("SELECT key FROM job_sources")}
        assert sources == {"demo-postings"}
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# The synthetic posting pool: no empty job cards, real skill edges.
# ---------------------------------------------------------------------------


def test_demo_posting_specs_reference_real_catalog_and_skills() -> None:
    """Static contract: every spec links a real catalog job and reference skills."""
    assert len(SEED.DEMO_POSTINGS) == 14
    codes = {spec.catalog_job_code for spec in SEED.DEMO_POSTINGS}
    assert codes >= SEEDED_ROLE_CODES, SEEDED_ROLE_CODES - codes
    unknown_jobs = codes - CATALOG_JOB_CODES
    assert unknown_jobs == set(), f"unknown catalog job codes {unknown_jobs}"
    for spec in SEED.DEMO_POSTINGS:
        assert 2 <= len(spec.skills) <= 5, spec.key
        skill_keys = [skill.skill_key for skill in spec.skills]
        assert len(skill_keys) == len(set(skill_keys)), spec.key
        # A typo fails loudly here instead of silently seeding one edge less.
        unknown = [key for key in skill_keys if key not in SKILL_KEYS]
        assert unknown == [], f"{spec.key}: unknown skill keys {unknown}"
        for skill in spec.skills:
            assert 1 <= skill.required_level <= 10, spec.key
            assert skill.priority in SKILL_PRIORITIES, spec.key
        # The expiry sweep treats 45-day-old postings as stale.
        assert spec.posted_days_ago <= 44, spec.key


def test_demo_postings_and_skills_land_mapped_and_idempotently(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo-workspace"
    seeded = run_seeder("--demo-dir", str(demo_dir), "--init-demo")
    assert seeded.returncode == 0, seeded.stderr

    database = demo_db(demo_dir)
    connection = sqlite3.connect(database)
    try:
        postings = {
            row[0]: row[1]
            for row in connection.execute("SELECT id, status FROM job_postings").fetchall()
        }
        assert len(postings) == len(SEED.DEMO_POSTINGS)
        assert set(postings.values()) == {"mapped"}

        rows = connection.execute(
            "SELECT posting_id, skill_id, required_level, priority FROM posting_skills"
        ).fetchall()
        pairs = [(row[0], row[1]) for row in rows]
        assert len(pairs) == len(set(pairs))
        assert all(1 <= level <= 10 for *_, level, priority in rows)
        assert {priority for *_, level, priority in rows} <= SKILL_PRIORITIES

        per_posting = Counter(posting_id for posting_id, *_ in rows)
        assert set(per_posting) == set(postings), "every posting carries skill context"
        assert all(2 <= count <= 5 for count in per_posting.values())

        posting_skill_keys = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT s.key FROM posting_skills ps JOIN skills s ON s.id = ps.skill_id"
            ).fetchall()
        }
        assert posting_skill_keys
        assert posting_skill_keys <= SKILL_KEYS

        # Accountant proof: one mapped posting with a real requirement set.
        accountant = connection.execute(
            "SELECT p.id FROM job_postings p JOIN jobs j ON j.id = p.catalog_job_id "
            "WHERE j.code = 'accountant' AND p.status = 'mapped'"
        ).fetchall()
        assert len(accountant) == 1
        accountant_skills = connection.execute(
            "SELECT s.key FROM posting_skills ps JOIN skills s ON s.id = ps.skill_id "
            "WHERE ps.posting_id = ?",
            (accountant[0][0],),
        ).fetchall()
        assert {row[0] for row in accountant_skills} <= SKILL_KEYS
        assert len(accountant_skills) >= 2

        for code in SEEDED_ROLE_CODES:
            mapped = connection.execute(
                "SELECT COUNT(*) FROM job_postings p JOIN jobs j ON j.id = p.catalog_job_id "
                "WHERE j.code = ? AND p.status = 'mapped'",
                (code,),
            ).fetchone()[0]
            assert mapped >= 1, code

        # Reference catalogs stay reference data (unchanged by the demo seed).
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 45
        assert connection.execute("SELECT COUNT(*) FROM job_relations").fetchone()[0] == 40
    finally:
        connection.close()

    # A second run adds no posting and no posting-skill edge.
    second = run_seeder("--demo-dir", str(demo_dir))
    assert second.returncode == 0, second.stderr
    assert "(0 created this run)" in second.stdout
    assert "  postings: 14 (0 created this run)" in second.stdout
    assert "  posting_skills: 54 (0 created this run)" in second.stdout
    assert db_counts(database)["posting_skills"] == len(rows)


# ---------------------------------------------------------------------------
# Public instance config (the badge must render before login).
# ---------------------------------------------------------------------------


async def test_instance_config_is_public_and_profile_exempt(client) -> None:
    # No session, no X-Profile-Id — the boot gate reads it before login.
    response = await client.get("/api/v1/instance/config")
    assert response.status_code == 200
    assert response.json() == {
        "demo_mode": False,
        "auth_mode": "authenticated",
        "registration_enabled": auth_kit().config.registration_enabled,
        # §4 entrypoint mode is public fact — the §4.5 control blocks
        # "Remove login" on server instances (S14).
        "identity_mode": "server",
        # The datastore-break marker is desktop-only; a server never
        # exposes a local path (family datastore-breaks contract).
        "datastore_quarantine": None,
    }


async def test_instance_config_reports_demo_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setattr(settings, "demo_mode", True)
    application = create_app()
    async with CleanJarClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as anonymous:
        response = await anonymous.get("/api/v1/instance/config")
    assert response.status_code == 200
    assert response.json()["demo_mode"] is True


async def test_instance_config_reports_registration_flag(client) -> None:
    kit = auth_kit()
    kit.config = dataclasses.replace(kit.config, registration_enabled=False)
    response = await client.get("/api/v1/instance/config")
    assert response.status_code == 200
    assert response.json()["registration_enabled"] is False


# ---------------------------------------------------------------------------
# The kit's demo rules through career's real app (§18.11).
# ---------------------------------------------------------------------------


async def test_demo_principal_only_on_demo_instances(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await client.post("/api/v1/auth/demo")).status_code == 404

    from app.main import create_app

    monkeypatch.setattr(settings, "demo_mode", True)
    application = create_app()
    async with CleanJarClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as anonymous:
        login = await anonymous.post("/api/v1/auth/demo")
        assert login.status_code == 200, login.text
        me = await anonymous.get("/api/v1/auth/me", headers=session_headers(login))
    assert me.status_code == 200
    assert me.json()["id"] == DEMO_PRINCIPAL_ID


async def test_demo_token_rejected_on_non_demo_instance(client) -> None:
    from nx_auth.cookies import cookie_names
    from nx_auth.tokens import AuthMode, TokenKind, mint_token

    kit = auth_kit()
    user = kit.users.create(email="demo-token@demo.career.local", password_hash=None)
    token = mint_token(
        kit.ring,
        kit.config,
        kind=TokenKind.SESSION,
        sub=user.id,
        ver=user.token_version,
        auth_mode=AuthMode.DEMO,
    )
    access_name = cookie_names(kit.config).access
    response = await client.get("/api/v1/auth/me", headers={"Cookie": f"{access_name}={token}"})
    assert response.status_code == 401
