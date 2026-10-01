import contextlib
import secrets
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
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
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db, sqlite_pragmas
from app.main import app
from app.models.posting_model import JobPosting, JobSource, PostingSkill

TEST_DB_URL = settings.database_url
IS_SQLITE = TEST_DB_URL.startswith("sqlite")

_engine = create_async_engine(TEST_DB_URL, pool_pre_ping=True)
if IS_SQLITE:
    # Same pragmas as the app engine — the WAL switch must happen before a
    # second engine connects, or the first exclusive-lock attempt races.
    event.listens_for(_engine.sync_engine, "connect")(sqlite_pragmas)

    # SQLite profile only: test-side sessions run this engine in
    # AUTOCOMMIT (each statement is its own transaction). The identity
    # stores commit through a *separate* sync-engine connection, so a
    # session that holds one transaction across reads would pin the WAL
    # snapshot and miss those commits (stale assertions), and the
    # ``clean_db`` isolation below is by deletion, not rollback.
    _autocommit_engine = _engine.execution_options(isolation_level="AUTOCOMMIT")

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
    "auth_sessions",
    "audit_events",
    "instance_settings",
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
    "profile_proposals",
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

    with contextlib.suppress(Exception):
        await get_or_create_vapid_keys()
    yield


@pytest.fixture(scope="session", autouse=True)
async def warm_checkpointer():
    """Boot-equivalent checkpointer warm-up (lifespan does this in prod).

    The test HTTP client bypasses the app lifespan, so the first chat
    turn would otherwise run the saver's initial migration lazily
    mid-flight — LangGraph's `setup()` issues CREATE INDEX CONCURRENTLY,
    which waits on every open transaction snapshot, and the session-wide
    outer transaction IS one: on a fresh CI database the first chat test
    deadlocked past the 120 s timeout (local databases already carry the
    langgraph tables, masking it). Create them up front, on their own
    connection, outside any test transaction — same rule as prod boot.
    """
    from app.ai.checkpointer import aclose_checkpointer, get_checkpointer

    with contextlib.suppress(Exception):
        await get_checkpointer()
    yield
    await aclose_checkpointer()


@pytest.fixture(autouse=True)
def restore_kit_config() -> Iterator[None]:
    """Tests may temporarily replace the frozen AuthConfig (lockout,
    registration) — the shared app's kit config is restored after each."""
    kit = app.state.auth
    original = kit.config
    yield
    kit.config = original


@pytest.fixture(autouse=True)
def clean_identity() -> Iterator[None]:
    """Wipe the identity world around every test (plan 16 P3a).

    The kit's stores write through their own committed transactions (the
    sync bridge in `app/core.database`), so identity rows do NOT ride the
    `clean_db` rollback — they are truncated here instead: before the
    test (so `users.count()` keeps first-user-admin deterministic) and
    after `clean_db` rolled back (so nothing can reference them). Order:
    this fixture wraps `clean_db` (it is its dependency) — setup before
    the outer transaction begins, teardown after it ends.
    """
    _clear_identity_rows()
    yield
    _clear_identity_rows()


def _clear_identity_rows() -> None:
    from sqlalchemy import delete as sql_delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.database import AuthSessionLocal
    from app.models.identity_model import AuditEvent, AuthSession, InstanceSetting
    from app.models.user_model import User

    kit = app.state.auth
    kit.ip_limiter._hits.clear()
    kit.email_limiter._hits.clear()
    try:
        with AuthSessionLocal() as session:
            for model in (AuthSession, AuditEvent, InstanceSetting, User):
                session.execute(sql_delete(model))
            session.commit()
    except SQLAlchemyError:
        # Best-effort hygiene: migration tests legitimately leave the
        # schema mid-chain (tables absent) — the next full cleanup wipes
        # whatever the rolling schema missed.
        pass


async def _provision_vapid_keys() -> None:
    """Ensure the VAPID `app_settings` row exists for the next test.

    Deletion isolation wipes the row the session warm-up wrote; the
    in-process key cache must not outlive it (emit would silently skip
    persisting a fresh pair), so clear the cache and let the service
    provision again — its own session, short and committed.
    """
    from app.services import webpush_service

    webpush_service._keys_cache = None
    with contextlib.suppress(Exception):
        await webpush_service.get_or_create_vapid_keys()


async def _truncate_all(conn) -> None:
    """Delete every table's rows, children first (``TABLES`` is FK-ordered).

    The fast path is one transaction; migration tests legitimately leave
    the schema mid-chain (tables absent), so a failure falls back to
    best-effort per-table deletes.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        for table in TABLES:
            await conn.execute(text(f"DELETE FROM {table}"))
        await conn.commit()
    except SQLAlchemyError:
        await conn.rollback()
        for table in TABLES:
            try:
                await conn.execute(text(f"DELETE FROM {table}"))
                await conn.commit()
            except SQLAlchemyError:
                await conn.rollback()


@pytest.fixture(autouse=True)
async def clean_db(clean_identity) -> AsyncGenerator:
    """Isolate each test's database state.

    Postgres (and any non-SQLite profile): wrap the whole test in one
    transaction and roll it back. The `db` and `client` fixtures bind their
    sessions to this connection with
    ``join_transaction_mode="create_savepoint"`` — app-level commits become
    savepoint releases and the final rollback discards everything.

    SQLite (desktop profile): deletion-based isolation instead. The
    identity stores (``app/auth/stores.py``) commit real transactions
    through their own sync-engine connection, so a suite-long outer
    transaction is unusable here: it would hold SQLite's single write lock
    (bridge INSERTs die with "database is locked") and pin a WAL read
    snapshot (bridge commits invisible → stale assertions). Truncate
    before the test and run sessions in short (autocommit) transactions.
    """
    from app.core.ratelimit import limiter

    limiter.reset()
    if IS_SQLITE:
        async with _engine.connect() as conn:
            await _truncate_all(conn)
        await _provision_vapid_keys()
        # A short-transaction connection for the tests that bind their own
        # sessions to the fixture (desktop tray, browser-push channel).
        async with _autocommit_engine.connect() as ac:
            yield ac
        return
    async with _engine.connect() as conn:
        transaction = await conn.begin()
        yield conn
        if transaction.is_active:
            await transaction.rollback()


def _test_session(conn) -> AsyncSession:
    """A session on the test's outer transaction (commit = savepoint)."""
    return AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")


def _sqlite_session() -> AsyncSession:
    """A short-transaction (AUTOCOMMIT) session for the SQLite profile.

    Every statement is its own transaction, so a read always sees the
    latest committed state — including the identity bridge's commits on
    its own connection.
    """
    return AsyncSession(bind=_autocommit_engine, expire_on_commit=False)


@pytest.fixture
async def db(clean_db) -> AsyncGenerator[AsyncSession, None]:
    """A session bound to the test database (cleaned up with the test)."""
    if IS_SQLITE:
        async with _sqlite_session() as session:
            yield session
        return
    async with _test_session(clean_db) as session:
        yield session


class CleanJarClient(AsyncClient):
    """Client whose cookie jar is cleared after every response.

    Sessions travel as explicit `Cookie` headers (or response-set jars
    when a test asks for one) — never hidden jar state: a login response
    must not silently authenticate the next anonymous request, and a
    mid-test switch of users must be deterministic. This mirrors the
    family test-client rule (handoff §5.10)."""

    async def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        response = await super().send(request, **kwargs)
        self.cookies.clear()
        return response


@pytest.fixture
async def client(clean_db) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client wired to the FastAPI app with the test DB session."""

    if IS_SQLITE:
        # Deletion-based isolation: requests run real, short transactions
        # on the app engine (request atomicity intact); the middleware's
        # §15 binding falls back to `AsyncSessionLocal`, also committed.
        async def _override_get_db():
            async with AsyncSessionLocal() as session:
                yield session

    else:

        async def _override_get_db():
            async with _test_session(clean_db) as session:
                yield session

    app.dependency_overrides[get_db] = _override_get_db
    if not IS_SQLITE:
        # §15 binding must read through the test's transaction too, or
        # profile rows created by routes stay invisible to the middleware.
        app.state.profile_sessions = lambda: _test_session(clean_db)
    transport = ASGITransport(app=app)
    async with CleanJarClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    if hasattr(app.state, "profile_sessions"):
        delattr(app.state, "profile_sessions")


# ---------------------------------------------------------------------------
# Kit session layer (plan 16 P3a): cookie sessions minted through the real
# auth-kit keys/verification. `auth_headers` returns the browser transport
# shape (§10 cookie + CSRF echo) plus a `Bearer` session token (§9 user
# clients) — enforcement accepts either; tests parse the bearer for ids.
# ---------------------------------------------------------------------------


def auth_kit():
    """The installed auth-kit (`app.state.auth`) — stores, keys, config."""
    return app.state.auth


def _cookie_access_name() -> str:
    from nx_auth.cookies import cookie_names

    return cookie_names(auth_kit().config).access


def default_profile_id(user_id: str) -> str | None:
    """The user's Default profile id (identity-auth §6), read through the
    sync identity bridge — minted rows are committed there."""
    import uuid as _uuid

    from sqlalchemy import select

    from app.core.database import AuthSessionLocal
    from app.models.user_model import Profile

    with AuthSessionLocal() as session:
        row = session.execute(
            select(Profile.id)
            .where(Profile.user_id == _uuid.UUID(str(user_id)))
            .order_by(Profile.is_default.desc(), Profile.created_at, Profile.id)
            .limit(1)
        ).first()
        return str(row[0]) if row is not None else None


def mint_session_headers(
    *,
    email: str = "student@example.com",
    password: str | None = None,
    full_name: str = "Test Student",
    is_admin: bool = True,
) -> dict:
    """Auth headers for a (new or existing) user, without HTTP or bcrypt.

    The session token is a real kit `session` token — the middleware and
    `nx_auth.deps` verify it exactly like a cookie-carried one. The
    §15 `X-Profile-Id` header rides along (the user's Default profile):
    every domain call binds a profile like a real client would.
    """
    from nx_auth.tokens import AuthMode, TokenKind, mint_token

    kit = auth_kit()
    user = kit.users.get_by_email(email) or kit.users.create(
        email=email,
        password_hash=_fixture_password_hash() if password is None else _fixture_hash(password),
        full_name=full_name,
        is_admin=is_admin,
    )
    token = mint_token(
        kit.ring,
        kit.config,
        kind=TokenKind.SESSION,
        sub=user.id,
        ver=user.token_version,
        auth_mode=AuthMode.PASSWORD,
    )
    csrf = secrets.token_urlsafe(32)
    headers = {
        "Cookie": f"{_cookie_access_name()}={token}; nx_csrf={csrf}",
        "X-CSRF-Token": csrf,
        "Authorization": f"Bearer {token}",
    }
    profile_id = default_profile_id(user.id)
    if profile_id is not None:
        headers["X-Profile-Id"] = profile_id
    return headers


_HASH_CACHE: dict[str, str] = {}


def _fixture_hash(password: str) -> str:
    """One bcrypt per distinct test password, not one per call."""
    if password not in _HASH_CACHE:
        from nx_auth.passwords import hash_password

        _HASH_CACHE[password] = hash_password(password)
    return _HASH_CACHE[password]


def _fixture_password_hash() -> str:
    return _fixture_hash("fixture-password-career")


def session_headers(response) -> dict:
    """Auth headers built from a login/register response's Set-Cookie
    (identity-auth §10) — the real issued session of that user, refresh
    cookie included (the `/auth/refresh` endpoint rotates from it)."""
    access = refresh = csrf = None
    for line in response.headers.get_list("set-cookie"):
        name, _, rest = line.partition("=")
        value = rest.split(";", 1)[0]
        if name.strip() == _cookie_access_name():
            access = value
        elif name.strip() == "nx_refresh":
            refresh = value
        elif name.strip() == "nx_csrf":
            csrf = value
    assert access, f"no session cookie in response: {response.headers.get_list('set-cookie')}"
    cookie = f"{_cookie_access_name()}={access}"
    if refresh:
        cookie += f"; nx_refresh={refresh}"
    cookie += f"; nx_csrf={csrf}"
    headers = {
        "Cookie": cookie,
        "X-CSRF-Token": csrf or "",
        "Authorization": f"Bearer {access}",
    }
    # §15: bind the fresh account's Default profile like a real client.
    profile_id = default_profile_id(str(decode_session_token(access)[0]))
    if profile_id is not None:
        headers["X-Profile-Id"] = profile_id
    return headers


async def register_user(
    client: AsyncClient,
    email: str,
    password: str = "supersecret1",
    full_name: str = "T",
) -> dict:
    """Register through the real API; returns auth headers for the new user."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return session_headers(response)


def user_id_from_headers(headers: dict) -> str:
    """The user id behind `auth_headers`-style headers (the bearer token's
    `sub`) — replaces the retired `core.security.decode_access_token`."""
    return str(decode_session_token(headers["Authorization"].split(" ", 1)[1])[0])


def decode_session_token(token: str) -> tuple[UUID, int]:
    """(user_id, token_version) from a kit-issued session token — the
    test-side parser (tokens are minted by the kit; verification is the
    middleware's job)."""
    import jwt as pyjwt

    claims = pyjwt.decode(token, options={"verify_signature": False})
    return UUID(str(claims["sub"])), int(claims.get("ver", 0))


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict:
    """Auth headers for the fixture user (admin, like the old default user).

    Minted through the kit stores (committed identity world — see
    `clean_identity`); every request carrying them is a session request.
    """
    return mint_session_headers()


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
    from app.seeds.metrics import seed_metric_dimensions
    from app.seeds.run import seed_taxonomy

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
        "hobbies": [{"key": "gaming", "label": "Playing and modding games", "weight": 4}],
        "likes": [{"tag_key": "technology-data", "label": "Solving puzzles", "weight": 4}],
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
    return user_id_from_headers(auth_headers)


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
            posted_at=datetime.now(UTC) - timedelta(days=2),
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
    defaults = {
        "external_id": "ex-1",
        "title": "Data Analyst",
        "org": "ExtractCo",
        "url": "https://ex.example/1",
        # Relative, never a fixed date: a pinned posted_at ages out of
        # posted_within windows and time-bombs the freshness tests.
        "posted_at": datetime.now(UTC) - timedelta(days=2),
        "skills_raw": ["programming", "problem-solving"],
        "raw": {
            "description": (
                "We need programming and problem-solving. Salary: 40000-60000 EUR per year."
            )
        },
    }
    defaults.update(kw)
    return RawPosting(**defaults)


async def _make_posting(db, source, **kw) -> JobPosting:
    """Sync one raw posting through the real fast pass."""
    from app.services.postings_service import upsert_posting

    posting = await upsert_posting(db, source, _raw_posting(**kw))
    await db.commit()
    await db.refresh(posting)
    return posting


async def _add_posting_skill(db, posting: JobPosting, skill_key: str, level, priority) -> None:
    """Upsert — the deep pass updates fast-pass rows in place."""
    from app.models.taxonomy_model import Skill

    skill = (await db.execute(select(Skill).where(Skill.key == skill_key))).scalars().first()
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
async def client_admin_headers(client) -> dict:
    """An admin user's session (promoted through the kit store — the
    first-user rule may already be taken by `auth_headers`)."""
    headers = await register_user(client, "admin@example.com", "supersecret1")
    kit = auth_kit()
    user = kit.users.get_by_email("admin@example.com")
    assert user is not None
    if not user.is_admin:
        kit.users.set_admin(user.id, True)
    return headers


def _chat_agent_script(user_text: str, tool_names: list[str]) -> dict:
    """The chat agent-round stand-in — delegates to the REAL mock (plan
    107: the local copy had drifted from app/ai/mock_chat.py; one source
    of truth, the fixture only guarantees registration + cleanup)."""
    from app.ai.mock_chat import mock_chat_agent_round

    return mock_chat_agent_round(user_text, tool_names)


@pytest.fixture(autouse=True)
def _chat_agent_mock():
    """Script the chat agent-round mock + register the structured reply
    mock for every test (the chatbot import side effect is gone — plan 98
    moved the builders to app/ai/mock_chat.py)."""
    from app.ai import gateway as gateway_module
    from app.models.enums import AITaskType

    gateway_module.register_agent_mock(AITaskType.CHAT.value, _chat_agent_script)
    yield
    gateway_module.AGENT_MOCK_SCRIPTS.pop(AITaskType.CHAT.value, None)
