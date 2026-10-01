"""Demo mode (plan 16 P3e, identity-auth §13) through the real career surface.

The seeder (`scripts/seed-demo.py`) must refuse anything that is not a
demo target *and* a demo instance — loudly, non-zero — seed idempotent
synthetic-only content, and land rows nowhere but the demo instance.
Reference catalogs (`backend/app/seeds/*`) stay reference data. The
public `GET /api/v1/instance/config` endpoint (product-owned) feeds the
SPA's "Demo — synthetic data" badge before login, and the kit's demo
rules hold through career's real app: the `demo` principal only on demo
instances, `demo` tokens rejected elsewhere (§18.11).
"""

from __future__ import annotations

import dataclasses
import sqlite3
import subprocess
import sys
from pathlib import Path

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
    "postings": 4,
    "applications": 6,
    "demo_mode": 1,
}


def run_seeder(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SEEDER), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
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
            "posting_interactions",
            "skills",
        ):
            counts[table] = connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        demo_flag = connection.execute(
            "SELECT value FROM instance_settings WHERE key = 'demo_mode'"
        ).fetchone()
        counts["demo_mode"] = (
            1 if demo_flag is not None and demo_flag[0] == "true" else 0
        )
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
        "applications": counts["posting_interactions"],
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
        connection.execute(
            "UPDATE instance_settings SET value = 'false' WHERE key = 'demo_mode'"
        )
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
    response = await client.get(
        "/api/v1/auth/me", headers={"Cookie": f"{access_name}={token}"}
    )
    assert response.status_code == 401
