from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.connectors.base import (
    ConnectorCapabilities,
    ConnectorResult,
    PostingConnector,
    RawPosting,
)
from app.connectors.registry import register_connector, reset_registry
from app.models.posting_model import JobPosting, JobSource, PostingSkill

from app.core.config import settings
from app.core.database import get_db, sqlite_pragmas
from app.main import app

TEST_DB_URL = settings.DATABASE_URL
IS_SQLITE = TEST_DB_URL.startswith("sqlite")

_engine = create_async_engine(TEST_DB_URL, pool_pre_ping=True)
if IS_SQLITE:
    # Same pragmas as the app engine — the WAL switch must happen before a
    # second engine connects, or the first exclusive-lock attempt races.
    event.listens_for(_engine.sync_engine, "connect")(sqlite_pragmas)

    def _sqlite_driver_autocommit_off(dbapi_connection, _record=None):
        """Disable aiosqlite's implicit BEGIN/COMMIT handling.

        The driver's legacy mode commits the whole transaction when the
        outermost savepoint is released, so the ``clean_db`` rollback
        would silently leak every app-level commit. With
        ``isolation_level=None`` the driver never begins or ends
        transactions itself and SQLAlchemy emits the BEGIN explicitly.
        """

        dbapi_connection.isolation_level = None

    def _sqlite_emit_begin(connection):
        connection.exec_driver_sql("BEGIN")

    event.listens_for(_engine.sync_engine, "connect")(_sqlite_driver_autocommit_off)
    event.listens_for(_engine.sync_engine, "begin")(_sqlite_emit_begin)

TABLES = [
    "cv_versions",
    "cv_documents",
    "cv_templates",
    "skill_evidence",
    "experience_skills",
    "experience_achievements",
    "experience_items",
    "education_items",
    "certifications",
    "profile_achievements",
    "autopilot_findings",
    "autopilot_runs",
    "autopilot_goals",
    "notification_deliveries",
    "notification_kind_prefs",
    "notification_recipients",
    "notification_subscriptions",
    "ai_budgets",
    "app_settings",
    "schedules",
    "learning_resources",
    "growth_plan_steps",
    "growth_plans",
    "posting_interactions",
    "posting_skills",
    "posting_fits",
    "interview_sessions",
    "cv_synth_items",
    "job_postings",
    "organizations",
    "job_sources",
    "notifications",
    "notification_rules",
    "notification_preferences",
    "notification_kinds",
    "search_history",
    "assessment_answers",
    "assessment_questions",
    "assessment_runs",
    "assessment_templates",
    "background_jobs",
    "ai_task_assignments",
    "ai_models",
    "ai_providers",
    "chat_messages",
    "chat_sessions",
    "ai_skill_packs",
    "ai_embeddings",
    "ai_mcp_servers",
    "ai_generations",
    "market_snapshots",
    "match_insights",
    "job_department_links",
    "department_admissions",
    "cv_parse_drafts",
    "cv_intake_applied",
    "departments",
    "universities",
    "career_path_steps",
    "career_paths",
    "user_skills",
    "user_interests",
    "user_metric_profile",
    "skill_transferability",
    "metric_dimensions",
    "job_skills",
    "job_tags",
    "job_relations",
    "jobs",
    "job_families",
    "interest_tags",
    "skills",
    "profiles",
    "documents",
    "users",
]


@pytest.fixture(scope="session", autouse=True)
async def warm_vapid_keys():
    """Boot-equivalent VAPID cache warm-up (lifespan does this in prod).

    Dispatch must never generate keys mid-transaction — the own-session
    write deadlocks SQLite behind the caller's write lock — so tests
    populate the cache once up front, like the app lifespan does.
    """
    from app.services.webpush_service import get_or_create_vapid_keys

    try:
        await get_or_create_vapid_keys()
    except Exception:  # noqa: BLE001 — browser push stays fail-soft
        pass
    yield


@pytest.fixture(autouse=True)
async def clean_db() -> AsyncGenerator:
    """Wrap the whole test in one transaction and roll it back.

    Truncating ~60 tables cost ~1.5s per test (≈13 min per suite run); a
    rollback costs milliseconds. The `db` and `client` fixtures bind their
    sessions to this connection with
    ``join_transaction_mode="create_savepoint"`` — app-level commits become
    savepoint releases and the final rollback discards everything, so the
    isolation guarantee is unchanged.
    """
    async with _engine.connect() as conn:
        from app.core.ratelimit import limiter

        limiter.reset()
        transaction = await conn.begin()
        yield conn
        if transaction.is_active:
            await transaction.rollback()


def _test_session(conn) -> AsyncSession:
    """A session on the test's outer transaction (commit = savepoint)."""
    return AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
async def db(clean_db) -> AsyncGenerator[AsyncSession, None]:
    """A session bound to the test database (rolled back with the test)."""
    async with _test_session(clean_db) as session:
        yield session


@pytest.fixture
async def client(clean_db) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client wired to the FastAPI app with the test DB session."""

    async def _override_get_db():
        async with _test_session(clean_db) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def auth_headers(client: AsyncClient, db) -> dict:
    """Bearer auth headers for API calls.

    Single-user mode: warm the default user via /auth/me, then mint a token
    for it (tests decode the user id from the token). Multi-user mode:
    register student@example.com through the regular register endpoint.
    """
    from sqlalchemy import select

    from app.core.config import settings
    from app.core.security import create_access_token
    from app.models.user_model import User

    if settings.SINGLE_USER_MODE:
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 200, response.text
        user = (
            (
                await db.execute(
                    select(User).where(User.email == settings.DEFAULT_USER_EMAIL)
                )
            )
            .scalars()
            .first()
        )
        assert user is not None
        token = create_access_token(user.id, user.token_version)
        return {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.com",
            "password": "supersecret1",
            "full_name": "Test Student",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def seeded_catalog(db) -> dict:
    """Seed taxonomy + catalog + curated paths; returns counts."""
    from app.seeds.run import seed_catalog, seed_paths, seed_taxonomy

    i, s = await seed_taxonomy(db)
    j, r = await seed_catalog(db)
    p = await seed_paths(db)
    from app.seeds.assessment import seed_assessment_bank

    q = await seed_assessment_bank(db)
    return {
        "interests": i,
        "skills": s,
        "jobs": j,
        "relations": r,
        "paths": p,
        "questions": q,
    }


@pytest.fixture
async def profile_ready(client: AsyncClient, auth_headers: dict, db) -> dict:
    """A user with a filled profile; returns the profile payload."""
    from app.seeds.run import seed_taxonomy
    from app.seeds.metrics import seed_metric_dimensions

    await seed_taxonomy(db)
    await seed_metric_dimensions(db)
    payload = {
        "basics": {
            "birth_year": 2008,
            "education_level": "high_school",
            "grade": "10",
            "country": "Greece",
            "city": "Athens",
        },
        "academics": {
            "favorite_subjects": [
                {"key": "mathematics", "weight": 5},
                {"key": "physics", "weight": 4},
            ],
            "languages": [{"code": "en", "level": "advanced"}],
        },
        "interests": [
            {"tag_key": "technology-software", "weight": 5, "source": "self"},
            {"tag_key": "technology-ai", "weight": 4, "source": "self"},
            {"tag_key": "technology-games", "weight": 3, "source": "self"},
        ],
        "hobbies": [
            {"key": "gaming", "label": "Playing and modding games", "weight": 4}
        ],
        "likes": [
            {"tag_key": "technology-data", "label": "Solving puzzles", "weight": 4}
        ],
        "dislikes": [{"label": "Public speaking", "weight": 2}],
        "aspirations": [
            {
                "label": "Build my own app",
                "tag_keys": ["technology-software"],
                "notes": "",
            }
        ],
        "work_preferences": {
            "teamwork": 3,
            "environment": 1,
            "structure": 2,
            "pace": 3,
            "leadership": 2,
            "remote_ok": True,
            "focus_areas": ["ideas", "data"],
            "salary_priority": 4,
            "stability_priority": 3,
            "physical_activity": "sedentary",
            "creativity_priority": 4,
        },
        "constraints": {
            "physical_conditions": [],
            "max_education_years": 6,
            "willing_to_relocate": True,
            "hours_available_per_week": 20,
        },
    }
    response = await client.put("/api/v1/profile", json=payload, headers=auth_headers)
    assert response.status_code == 200, response.text
    return payload


# ------------------------------------------------- shared postings fixtures
# (Phases 26/31/32 — one definition, imported by name in every postings
# test module; module-level re-definitions keep shadowing these fine.)


def _uid(auth_headers) -> str:
    from app.core.security import decode_access_token

    return str(decode_access_token(auth_headers["Authorization"].split(" ", 1)[1])[0])


class SyntheticConnector(PostingConnector):
    """Deterministic one-posting connector with etag-based increments."""

    key = "synthetic"
    title = "Synthetic test connector"
    docs_url = "https://docs.example/synthetic"
    capabilities = ConnectorCapabilities(supports_incremental=True)
    counter = 0

    def config_model(self):
        from app.connectors.base import EmptyConfig

        return EmptyConfig

    async def fetch(self, config, state, *, transport=None, **_kw):
        if state and state.get("etag"):
            return ConnectorResult(next_state=state)
        SyntheticConnector.counter += 1
        posting = RawPosting(
            external_id="syn-1",
            title="QA Automation Engineer",
            org="SynthCo",
            url="https://syn.example/1",
            posted_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            skills_raw=["programming", "problem-solving"],
            raw={"description": "We need programming and problem-solving."},
        )
        return ConnectorResult(postings=[posting], next_state={"etag": '"syn-etag"'})


@pytest.fixture
def synthetic_connector():
    register_connector(SyntheticConnector())
    yield SyntheticConnector
    reset_registry()


@pytest.fixture
async def source(db, synthetic_connector):
    src = JobSource(key="synth", connector_key="synthetic", config={}, enabled=True)
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


@pytest.fixture
async def kinds(db):
    from app.seeds.run import seed_notification_kinds

    return await seed_notification_kinds(db)


def _raw_posting(**kw) -> RawPosting:
    defaults = dict(
        external_id="ex-1",
        title="Data Analyst",
        org="ExtractCo",
        url="https://ex.example/1",
        posted_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        skills_raw=["programming", "problem-solving"],
        raw={
            "description": (
                "We need programming and problem-solving. "
                "Salary: 40000-60000 EUR per year."
            )
        },
    )
    defaults.update(kw)
    return RawPosting(**defaults)


async def _make_posting(db, source, **kw) -> JobPosting:
    """Sync one raw posting through the real fast pass."""
    from app.services.postings_service import upsert_posting

    posting = await upsert_posting(db, source, _raw_posting(**kw))
    await db.commit()
    await db.refresh(posting)
    return posting


async def _add_posting_skill(
    db, posting: JobPosting, skill_key: str, level, priority
) -> None:
    """Upsert — the deep pass updates fast-pass rows in place."""
    from app.models.taxonomy_model import Skill

    skill = (
        (await db.execute(select(Skill).where(Skill.key == skill_key)))
        .scalars()
        .first()
    )
    assert skill is not None, f"seeded skill missing: {skill_key}"
    row = (
        (
            await db.execute(
                select(PostingSkill).where(
                    PostingSkill.posting_id == posting.id,
                    PostingSkill.skill_id == skill.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        row = PostingSkill(posting_id=posting.id, skill_id=skill.id)
        db.add(row)
    row.required_level = level
    row.priority = priority
    await db.commit()


@pytest.fixture
async def search_fixtures(db, client, auth_headers, seeded_catalog, source, kinds):
    a = await _make_posting(db, source, external_id="ex-a", title="Analyst A")
    b = await _make_posting(db, source, external_id="ex-b", title="Analyst B")
    c = await _make_posting(db, source, external_id="ex-c", title="Analyst C")
    await _add_posting_skill(db, a, "programming", 5, "must_have")
    await _add_posting_skill(db, a, "problem-solving", 3, "nice_to_have")
    await _add_posting_skill(db, b, "programming", 2, "bonus")
    await _add_posting_skill(db, b, "problem-solving", 1, "nice_to_have")
    await _add_posting_skill(db, c, "programming", None, None)  # not extracted
    return a, b, c


@pytest.fixture
async def client_admin_headers(client, db):
    """An admin user (is_admin forced — the first-user rule may already be taken)."""
    from sqlalchemy import select

    from app.models.user_model import User

    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    row = (
        (await db.execute(select(User).where(User.email == "admin@example.com")))
        .scalars()
        .first()
    )
    row.is_admin = True
    await db.commit()
    return {"Authorization": f"Bearer {first.json()['access_token']}"}


@pytest.fixture
def multi_user_mode(monkeypatch):
    """Disable single-user mode: strict JWT auth like the future family auth."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SINGLE_USER_MODE", False)
