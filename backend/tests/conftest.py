import contextlib
import fnmatch
import json
import os
import secrets
from collections.abc import AsyncGenerator, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from _pytest.mark.expression import Expression
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.core.database import (
    AsyncSessionLocal,
    get_db,
    json_serializer,
    sqlite_pragmas,
)
from app.extensions.registry import register_connector, reset_registry
from app.extensions.sdk import (
    ConnectorCapabilities,
    ConnectorResult,
    PostingConnector,
    RawPosting,
)
from app.main import app
from app.models.posting_model import JobPosting, JobSource, PostingSkill
from tests.xdist_routing import routed_worker_root

TEST_DB_URL = settings.database_url
IS_SQLITE = TEST_DB_URL.startswith("sqlite")


def _assert_worker_state_isolation() -> None:
    """Fail when a routed worker's data/upload roots escaped its worker directory.

    ``tests/xdist_routing.py`` routes a worker's database *and* its
    ``CAREER_DATA_DIR``/``CAREER_UPLOAD_DIR``; a test that hard-codes the
    shared ``tests/_data``/``tests/_uploads`` trees would silently reintroduce
    cross-worker sharing. Routing is a no-op for serial runs, the xdist
    controller, a missing ``CAREER_DATABASE_URL`` and in-memory databases, so
    this only applies to processes that were actually routed.
    """
    worker_root = routed_worker_root()
    if worker_root is None:
        return
    root = worker_root.expanduser().resolve()
    scopes = (("data_dir", settings.data_dir), ("upload_root", settings.upload_root))
    for label, path in scopes:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_relative_to(root):
            raise RuntimeError(
                f"xdist worker state escaped its worker directory: {label}={resolved} "
                f"is outside {root}. Tests must not hard-code tests/_data or "
                "tests/_uploads — route the path through tests/xdist_routing.py."
            )


_assert_worker_state_isolation()

_engine = create_async_engine(TEST_DB_URL, pool_pre_ping=True, json_serializer=json_serializer)
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
    "backup_runs",
    "migration_archive",
    "source_prefs",
    "provider_subscriptions",
    "job_source_presets",
    "provider_endpoints",
    "seed_item_provenance",
    "seed_deferred_refs",
    "seed_import_run_items",
    "seed_sync_runs",
    "seed_import_runs",
    "retrieval_query_rollups",
    "retrieval_coverage_snapshots",
    "vector_records",
    "vector_documents",
    "vector_spaces",
    "claim_events",
    "scenario_points",
    "econ_observations",
    "econ_series",
    "econ_watchlist",
    "econ_packs",
    "claims",
    "scenarios",
    "exposure_scores",
    "code_crosswalks",
    "geo_region_aliases",
    "geo_regions",
    "contact_interactions",
    "application_events",
    "applications",
    "contacts",
    "user_path_flags",
    "label_overrides",
    "mcp_tokens",
    "user_feed_tokens",
    "followup_rules",
    "user_channel_configs",
    "webhook_endpoints",
    "extension_sandbox_runs",
    "extension_installs",
    "extension_sources",
    "cv_versions",
    "cv_documents",
    "cv_templates",
    "skill_evidence",
    "experience_skills",
    "experience_achievements",
    "interview_stories",
    "experience_items",
    "education_items",
    "certifications",
    "profile_achievements",
    "saved_answers",
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
    "posting_filter_presets",
    "posting_interactions",
    "posting_changes",
    "posting_skills",
    "mapping_reviews",
    "mapping_coverage_snapshots",
    "posting_fits",
    "interview_sessions",
    "cv_synth_items",
    "job_postings",
    "source_runs",
    "company_profiles",
    "job_radars",
    "organization_aliases",
    "organization_match_exclusions",
    "organization_match_pairs",
    "organization_merge_suggestions",
    "organizations",
    "job_sources",
    "seed_source_versions",
    "seed_sources",
    "notifications",
    "notification_rules",
    "notification_preferences",
    "notification_kinds",
    "smart_query_cache",
    "search_history",
    "assessment_answers",
    "assessment_questions",
    "assessment_runs",
    "assessment_templates",
    "background_jobs",
    "embedding_model_profiles",
    "ai_task_assignments",
    "ai_models",
    "ai_price_overrides",
    "ai_providers",
    "profile_proposals",
    "user_tool_grants",
    "chat_messages",
    "chat_sessions",
    "ai_skill_packs",
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
    "metric_category_anchors",
    "job_skills",
    "job_tags",
    "job_relations",
    "jobs",
    "job_families",
    "interest_tags",
    "skill_changes",
    "skill_relations",
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


@pytest_asyncio.fixture
async def _stop_pdf_engine():
    """Stop the cached Playwright driver on the test's own loop.

    The test HTTP client bypasses the app lifespan, so shutdown_engine() never
    ran under pytest, and pytest-asyncio closes the loop after each test. The
    driver's node subprocess was then left to the garbage collector; when GC
    landed on a later test it raised ``RuntimeError: Event loop is closed``
    inside ``BaseSubprocessTransport.__del__`` — a
    PytestUnraisableExceptionWarning attributed to whichever test triggered GC,
    not the one that started the driver.
    """
    yield
    from app.services.cv.cv_pdf_service import shutdown_engine

    with contextlib.suppress(Exception):
        await shutdown_engine()


@pytest.fixture(autouse=True)
def restore_kit_config() -> Iterator[None]:
    """Tests may temporarily replace the frozen AuthConfig (lockout,
    registration) — the shared app's kit config is restored after each."""
    kit = app.state.auth
    original = kit.config
    yield
    kit.config = original


@pytest.fixture(autouse=True)
def reset_embed_cache() -> Iterator[None]:
    """Plan 201 S6: the query-embedding cache is process-wide; a hit from a
    previous test would fake a provider call (and its absence)."""
    from app.services.embed_cache import clear

    clear()
    yield
    clear()


@pytest.fixture(autouse=True)
def reset_embedding_model_cache() -> Iterator[None]:
    """Plan 201 S2: the embedding client cache is process-wide.

    A cached ``OpenAIEmbeddings`` carries an httpx/AsyncOpenAI client; leaking
    one into the next test (or across the auth/provider permutations) would
    mask a broken cache key and can hold a closed loop's client. Clear before
    and after every test.
    """
    from app.ai.model_cache import clear_embedding_models

    clear_embedding_models()
    yield
    clear_embedding_models()


@pytest.fixture(autouse=True)
def reset_metric_registry() -> Iterator[None]:
    """Plan 225 S3: the metric registry is a process-wide cache.

    A snapshot loaded in a previous test would hide a just-applied pack (or
    leak a rolled-back one), so every test starts and ends with a cold cache.
    """
    from app.services.catalog.metric_registry import reset_metric_registry

    reset_metric_registry()
    yield
    reset_metric_registry()


@pytest.fixture(autouse=True)
def clean_vector_store() -> Iterator[None]:
    """Drop vector-store state left behind by a previous test's sync writes.

    The Postgres lane rolls the app session back, but the vector store is
    written through its own sync engine (provisioning/jobs), so a test that
    fails before its cleanup would otherwise leave an ``active`` space whose
    name collides with the next test's fixture — and a per-space ``vec_*``
    table, which the migration tests assume cannot exist. SQLite's deletion
    isolation covers the rows but not the extension-owned tables.
    """
    from sqlalchemy import delete as sql_delete
    from sqlalchemy import inspect, text

    from app.core.database import sync_engine
    from app.models.vector_model import (
        RetrievalCoverageSnapshot,
        RetrievalQueryRollup,
        VectorDocument,
        VectorRecord,
    )
    from app.models.vector_model import VectorSpace as VectorSpaceRow
    from app.storage.vector_backends import reset_backend_cache

    reset_backend_cache()

    def _clear_residue() -> None:
        with sync_engine.begin() as connection:
            tables = set(inspect(connection).get_table_names())
            suffix = " CASCADE" if connection.dialect.name == "postgresql" else ""
            for table in sorted(
                name for name in tables if name.startswith("vec_") and len(name) >= 12
            ):
                connection.execute(text(f"DROP TABLE IF EXISTS {table}{suffix}"))
            if "vector_entry_ids" in tables:
                connection.execute(text("DELETE FROM vector_entry_ids"))
            if "vector_spaces" in tables:
                for model in (
                    RetrievalQueryRollup,
                    RetrievalCoverageSnapshot,
                    VectorRecord,
                    VectorDocument,
                    VectorSpaceRow,
                ):
                    connection.execute(sql_delete(model))

    with contextlib.suppress(Exception):
        # a mid-chain migration test legitimately has no schema
        _clear_residue()
    yield


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


async def _provision_quality_denylist() -> None:
    """Re-seed the baseline's junk-label exclusions for the next test.

    The denylist is DATA (admin-editable `organization_match_exclusions`
    rows, seeded by the 0001 baseline). SQLite's deletion isolation wipes
    them with everything else, while the Postgres lanes keep them outside
    the per-test rollback — without this the quality gate admits
    "Confidential" on the desktop lane only. The list stays owned by the
    baseline module (loaded by path: revision modules are not importable by
    name), so the seed and this provision can never drift apart.
    """
    import importlib.util
    from pathlib import Path

    from sqlalchemy import text

    revision_path = (
        Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0001_baseline_schema.py"
    )
    spec = importlib.util.spec_from_file_location("_plan135_revision", revision_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    seen_keys: set[str] = set()
    async with _autocommit_engine.connect() as conn:
        for label in module._QUALITY_DENYLIST:  # type: ignore[attr-defined]
            label_key = module._alias_key(label)  # type: ignore[attr-defined]
            if label_key in seen_keys:
                continue
            seen_keys.add(label_key)
            await conn.execute(
                text(
                    "INSERT INTO organization_match_exclusions "
                    "(id, label, label_key, org_id, reason, source, created_by) "
                    "VALUES (:id, :label, :lkey, NULL, 'quality', 'seed', 'system')"
                ),
                {"id": str(uuid4()), "label": label, "lkey": label_key},
            )


async def _truncate_all(conn) -> None:
    """Delete every table's rows, children first (``TABLES`` is FK-ordered).

    The fast path is one transaction; migration tests legitimately leave
    the schema mid-chain (tables absent), so a failure falls back to
    best-effort per-table deletes.

    Self-referencing FKs need their links cleared first: ``skills.parent_id``
    is RESTRICT and RESTRICT is checked immediately, so one DELETE cannot
    remove a parent row while its child row still exists (a test that seeds
    a skill hierarchy would otherwise leak its rows into the next test).
    """
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    clearers = {
        "skills": "UPDATE skills SET parent_id = NULL",
    }

    async def delete_table(table: str) -> None:
        clearer = clearers.get(table)
        if clearer is not None:
            await conn.execute(text(clearer))
        await conn.execute(text(f"DELETE FROM {table}"))

    try:
        for table in TABLES:
            await delete_table(table)
        await conn.commit()
    except SQLAlchemyError:
        await conn.rollback()
        for table in TABLES:
            try:
                await delete_table(table)
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
    from app.middleware import RATE_LIMIT_POLICY

    # Plan 21: the kit counter is the app-wide limiter state.
    RATE_LIMIT_POLICY.counter.clear()
    if IS_SQLITE:
        async with _engine.connect() as conn:
            await _truncate_all(conn)
        await _provision_quality_denylist()
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


def _cookie_refresh_name() -> str:
    from nx_auth.cookies import cookie_names

    return cookie_names(auth_kit().config).refresh


def _cookie_csrf_name() -> str:
    from nx_auth.cookies import cookie_names

    return cookie_names(auth_kit().config).csrf


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
        "Cookie": f"{_cookie_access_name()}={token}; {_cookie_csrf_name()}={csrf}",
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
        elif name.strip() == _cookie_refresh_name():
            refresh = value
        elif name.strip() == _cookie_csrf_name():
            csrf = value
    assert access, f"no session cookie in response: {response.headers.get_list('set-cookie')}"
    cookie = f"{_cookie_access_name()}={access}"
    if refresh:
        cookie += f"; {_cookie_refresh_name()}={refresh}"
    cookie += f"; {_cookie_csrf_name()}={csrf}"
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
async def fixture_catalog(db, tmp_path):
    """Apply the published job-catalog fixture pack (plan 224 S4)."""
    from tests.seed_pack_fixture import apply_catalog_pack

    return await apply_catalog_pack(db, tmp_path)


@pytest.fixture
async def fixture_taxonomy(db, tmp_path):
    """Apply just the pack's skills and interest tags (profile fixtures)."""
    from tests.seed_pack_fixture import apply_taxonomy_pack

    return await apply_taxonomy_pack(db, tmp_path)


@pytest.fixture
async def seeded_catalog(db, fixture_catalog) -> dict:
    """The fixture job catalog plus the assessment bank."""
    from app.seeds.assessment import seed_assessment_bank

    questions = await seed_assessment_bank(db)
    return {"questions": questions}


@pytest.fixture
async def profile_ready(client: AsyncClient, auth_headers: dict, db, fixture_taxonomy) -> dict:
    """A user with a filled profile; returns the profile payload."""
    from app.seeds.metrics import seed_metric_dimensions

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
    manifest_file = Path(__file__).resolve().parent / "fixtures" / "synthetic-connector.json"
    docs_url = "https://docs.example/synthetic"
    capabilities = ConnectorCapabilities(supports_incremental=True)
    counter = 0

    def config_model(self):
        from app.extensions.sdk import EmptyConfig

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
        return ConnectorResult(items=[posting], next_state={"etag": '"syn-etag"'})


@pytest.fixture
def synthetic_connector():
    register_connector(SyntheticConnector())
    yield SyntheticConnector
    reset_registry()


class DynamicSynthetic(SyntheticConnector):
    key = "dynamic-synthetic"
    capabilities = ConnectorCapabilities(supports_incremental=True, dynamic_queries=True)
    last_config: ClassVar[dict] = {}
    calls = 0

    async def fetch(self, config, state, *, transport=None, **_kw):
        DynamicSynthetic.last_config = dict(config)
        DynamicSynthetic.calls += 1
        return ConnectorResult(
            items=[
                RawPosting(
                    external_id=f"dyn-{DynamicSynthetic.calls}",
                    title="Engineer",
                    url=f"https://example.test/{DynamicSynthetic.calls}",
                    posted_at=datetime.now(UTC),
                )
            ],
            next_state={"etag": str(DynamicSynthetic.calls)},
        )


@pytest.fixture
def dynamic_connector():
    register_connector(DynamicSynthetic())
    DynamicSynthetic.last_config = {}
    DynamicSynthetic.calls = 0
    yield DynamicSynthetic
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
    from app.services.postings.postings_service import upsert_posting

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


async def grant_tool(db, user, key: str) -> None:
    """D20 test helper: the catalog grant a state-changing tool needs
    before the registry funnel lets its write run. Accepts a User row or
    a bare user id."""
    from uuid import UUID

    from app.ai.tools.grants import grant

    user_id = user if isinstance(user, UUID) else user.id
    await grant(db, user_id, key)


_SKIP_ALLOWLIST_PATH = Path(__file__).with_name("skip_allowlist.json")
_SKIP_OBSERVATIONS_PATH = Path(__file__).with_name("_xdist") / "skip_observations.json"
_PARALLEL_LANE = "not serial"
_SERIAL_LANE = "serial"
_observed_skips: dict[str, str] = {}


def _skip_allowlist() -> list[dict[str, str]]:
    data = json.loads(_SKIP_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return data.get("sqlite" if IS_SQLITE else "postgres", [])


def _selects_whole_tree(config: pytest.Config) -> bool:
    """Whether this session selects every test in the tree (no ``-k``, no path narrowing)."""
    if getattr(config.option, "keyword", ""):
        return False
    targets = [str(arg).rstrip("/") for arg in config.args] or ["tests"]
    return targets == ["tests"]


def _targets_full_suite(config: pytest.Config) -> bool:
    if getattr(config.option, "markexpr", ""):
        return False
    return _selects_whole_tree(config)


def _load_skip_observations() -> dict[str, dict[str, str]]:
    """The per-lane skip observations merged by earlier non-worker sessions."""
    try:
        data = json.loads(_SKIP_OBSERVATIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _merge_skip_observations(markexpr: str, observed: dict[str, str]) -> dict[str, dict[str, str]]:
    """Record this session's skips under its exact ``-m`` expression, replacing an earlier run."""
    merged = _load_skip_observations()
    merged[markexpr] = dict(observed)
    _SKIP_OBSERVATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SKIP_OBSERVATIONS_PATH.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return merged


def _matching_allowlist_entry(
    nodeid: str, reason: str, allowlist: list[dict[str, str]]
) -> int | None:
    for index, entry in enumerate(allowlist):
        if not fnmatch.fnmatch(nodeid, entry["id"]):
            continue
        if entry["reason_contains"] in reason:
            return index
    return None


def _unlisted_skip_problems(observed: dict[str, str], allowlist: list[dict[str, str]]) -> list[str]:
    return [
        f"unlisted skip: {nodeid} ({reason})"
        for nodeid, reason in observed.items()
        if _matching_allowlist_entry(nodeid, reason, allowlist) is None
    ]


def _missing_allowlisted_skip_problems(
    observed: dict[str, str], allowlist: list[dict[str, str]]
) -> list[str]:
    matched = {
        index
        for nodeid, reason in observed.items()
        if (index := _matching_allowlist_entry(nodeid, reason, allowlist)) is not None
    }
    return [
        f"allowlisted skip did not fire: {entry['id']} ({entry['reason_contains']})"
        for index, entry in enumerate(allowlist)
        if entry.get("when", "always") == "always" and index not in matched
    ]


def _completeness_scope(
    config: pytest.Config, markexpr: str, merged: dict[str, dict[str, str]]
) -> tuple[dict[str, str] | None, str]:
    """What the completeness half judges: ``(observations, failure message)``.

    A full run judges this session's own observations (today's whole-suite
    behaviour), not a union of every lane an earlier run recorded. A
    ``--collect-only`` session runs no tests, so it has no observations to
    judge and never evaluates completeness. The ``serial`` pass finishes the
    partition, so it needs the ``not serial`` lane's observations and fails
    closed without them. Any other selector — and a narrowed path — never
    evaluates completeness.
    """
    if getattr(config.option, "collectonly", False):
        return None, ""
    if markexpr == _SERIAL_LANE:
        if not _selects_whole_tree(config):
            return None, ""
        if _PARALLEL_LANE not in merged:
            return None, (
                "final lane without the parallel lane's observations — run "
                "./scripts/run-tests.sh (or --no-skip-wall)"
            )
        union = dict(merged[_PARALLEL_LANE])
        union.update(_observed_skips)
        return union, ""
    if _targets_full_suite(config):
        return dict(_observed_skips), ""
    return None, ""


def pytest_runtest_logreport(report) -> None:
    """Record every skip so the wall can compare it against the allowlist."""
    if not report.skipped or report.nodeid in _observed_skips:
        return
    reason = ""
    if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        reason = str(report.longrepr[2]).removeprefix("Skipped: ")
    _observed_skips[report.nodeid] = reason


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the run when the skip list grows beyond the reviewed allowlist.

    Skips are intentional coverage gaps: a dialect-only case, a missing
    optional engine, or a documented environment limitation. A new skip
    must be reviewed and added to ``tests/skip_allowlist.json`` (with a
    reason) instead of silently shrinking the suite.

    Every non-worker session records its skips in
    ``tests/_xdist/skip_observations.json`` under its exact ``-m`` expression,
    replacing an earlier run's entry for that lane. The completeness half
    (every ``when: always`` entry actually fired) then holds for a full run
    over this session's observations, and the ``-m serial`` pass is the
    partition's final lane: it fails closed when the ``not serial`` pass never
    ran, so a forgotten flag cannot switch the gate off.
    ``--no-skip-wall`` is the only opt-out, and it disables completeness only.
    """
    if hasattr(session.config, "workerinput"):
        return
    markexpr = getattr(session.config.option, "markexpr", "") or ""
    merged = _merge_skip_observations(markexpr, _observed_skips)
    allowlist = _skip_allowlist()
    problems = _unlisted_skip_problems(_observed_skips, allowlist)
    if not session.config.getoption("--no-skip-wall", default=False):
        scope, failure = _completeness_scope(session.config, markexpr, merged)
        if failure:
            problems.append(failure)
        elif scope is not None:
            problems.extend(_missing_allowlisted_skip_problems(scope, allowlist))
    if not problems:
        return
    session.exitstatus = 1
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        reporter.write_line("")
        reporter.write_line("skip wall FAILED — expected skip list drifted:", red=True)
        for problem in problems:
            reporter.write_line(f"  {problem}", red=True)
        reporter.write_line(f"  update {_SKIP_ALLOWLIST_PATH} (documented skips only)")


SERIAL_MARKER = "serial"
_SERIAL_ALLOWLIST_PATH = Path(__file__).with_name("serial_allowlist.json")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERIAL_CRITERIA = frozenset({"H2", "H3"})


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the explicit, visible opt-out from the skip wall's completeness half."""
    parser.addoption(
        "--no-skip-wall",
        action="store_true",
        default=False,
        help=(
            "skip only the skip-wall completeness half (every allowlisted skip must "
            "fire); unlisted skips still fail the run"
        ),
    )


def _serial_allowlist() -> list[dict[str, str]]:
    data = json.loads(_SERIAL_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return data.get("entries", [])


def _serial_entry_matches(entry_id: str, nodeid: str) -> bool:
    """A registry id is an exact node id or a ``tests/<file>.py`` prefix form."""
    if entry_id.endswith(".py"):
        return nodeid.startswith(f"{entry_id}::")
    return nodeid == entry_id


def _resource_problem(resource: str) -> str:
    path_part, _, line_part = resource.rpartition(":")
    if not path_part or not line_part.isdigit():
        return f"resource must be a path:line reference, got {resource!r}"
    path = _REPO_ROOT / path_part
    if not path.is_file():
        return f"resource file does not exist: {resource}"
    if len(path.read_text(encoding="utf-8").splitlines()) < int(line_part):
        return f"resource line is past the end of {path_part}: {resource}"
    return ""


def _serial_registry_problems(marked_ids: Iterable[str], *, full_run: bool) -> list[str]:
    """Registry drift for the collected ``serial`` items, as human-readable problems."""
    entries = _serial_allowlist()
    problems: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        entry_id = str(entry.get("id", "")).strip()
        if not entry_id:
            problems.append(f"serial registry entry without an id: {entry}")
            continue
        if entry_id in seen:
            problems.append(f"duplicate serial registry id: {entry_id}")
        seen.add(entry_id)
        if entry.get("criterion") not in _SERIAL_CRITERIA:
            problems.append(f"serial registry entry {entry_id}: criterion must be H2 or H3")
        if not str(entry.get("why", "")).strip():
            problems.append(f"serial registry entry {entry_id}: why must be non-empty")
        problem = _resource_problem(str(entry.get("resource", "")).strip())
        if problem:
            problems.append(f"serial registry entry {entry_id}: {problem}")
    marked = sorted(set(marked_ids))
    for nodeid in marked:
        if not any(_serial_entry_matches(str(entry.get("id", "")), nodeid) for entry in entries):
            problems.append(
                f"serial test not in the registry: {nodeid} — add it to "
                "tests/serial_allowlist.json with its criterion and the resource that justifies it"
            )
    if full_run:
        for entry in entries:
            entry_id = str(entry.get("id", "")).strip()
            if entry_id and not any(_serial_entry_matches(entry_id, nodeid) for nodeid in marked):
                problems.append(f"serial registry entry matches nothing on a full run: {entry_id}")
    return problems


def _resolved_worker_count(config: pytest.Config) -> int:
    """The effective xdist worker count, normalised across ``-n`` spellings.

    pytest-xdist clears ``numprocesses`` inside a worker process, so there the
    count comes from the ``PYTEST_XDIST_WORKER_COUNT`` it exports instead.
    """
    raw = config.getoption("numprocesses", default=None)
    if isinstance(raw, str) and raw in {"auto", "logical"}:
        return os.cpu_count() or 1
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    count = os.environ.get("PYTEST_XDIST_WORKER_COUNT", "")
    return int(count) if count.isdigit() else 0


def _serial_guard_violation(config: pytest.Config, marked_ids: list[str]) -> str:
    """The refusal message when ``serial`` items would run in a parallel SQLite session."""
    if not IS_SQLITE or not marked_ids:
        return ""
    workers = _resolved_worker_count(config)
    if workers <= 1:
        return ""
    return (
        f"{len(marked_ids)} serial-marked test(s) collected with {workers} xdist workers on "
        "the SQLite desktop profile — they are not parallel-safe there. Run "
        'pytest -m "not serial" -n <workers> and then pytest -m serial separately, '
        "or use ./scripts/run-tests.sh (which runs both passes)."
    )


def _serial_registry_covers_the_tree(config: pytest.Config) -> bool:
    """Whether this session sees the registry's whole subject (full run or the serial lane)."""
    if _targets_full_suite(config):
        return True
    markexpr = getattr(config.option, "markexpr", "") or ""
    return markexpr == _SERIAL_LANE and _selects_whole_tree(config)


def _serial_marker_selected(config: pytest.Config) -> bool:
    """Whether the active ``-m`` expression keeps a bare ``serial`` marker in.

    The expression is compiled with pytest's own engine and evaluated against a
    matcher that is true only for the bare ``serial`` marker, so every spelling
    that excludes the serial lane (``not serial``, ``contract or not serial``,
    ``not (serial or benchmark)``) is recognised, while no selector, ``serial``
    and ``not benchmark`` keep the guard armed. A malformed expression fails
    closed (the guard applies); pytest reports the parse error itself.
    """
    markexpr = getattr(config.option, "markexpr", "") or ""
    if not markexpr:
        return True
    try:
        expression = Expression.compile(markexpr)
    except SyntaxError:
        return True
    return expression.evaluate(lambda name, **kwargs: name == SERIAL_MARKER and not kwargs)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Attach the driver cleanup, then enforce the serial partition at collection.

    The per-test Playwright cleanup is attached to async tests here because it
    needs their loop. The registry and the controller-layer guard are skipped in
    xdist workers: pytest-xdist turns an exception raised in a worker's
    collection hooks into an internal error, so the harness would lose the
    message. The serial lane and every single-process run do both checks here;
    the guard in :func:`pytest_runtest_setup` covers the rest. The
    controller-layer guard is skipped when the active ``-m`` expression excludes
    ``serial``: pytest deselects those items after this hook, so a legitimate
    ``-m "not serial" -n N --collect-only`` must not be refused.
    """
    import inspect

    for item in items:
        obj = getattr(item, "obj", None)
        if obj is not None and inspect.iscoroutinefunction(obj):
            item.add_marker(pytest.mark.usefixtures("_stop_pdf_engine"))
    if hasattr(config, "workerinput"):
        return
    marked = [item.nodeid for item in items if item.get_closest_marker(SERIAL_MARKER)]
    problems = _serial_registry_problems(marked, full_run=_serial_registry_covers_the_tree(config))
    if problems:
        raise pytest.UsageError("serial partition FAILED:\n  " + "\n  ".join(problems))
    violation = _serial_guard_violation(config, marked)
    if violation and _serial_marker_selected(config):
        raise pytest.UsageError(violation)


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Refuse to run a ``serial`` test inside a parallel SQLite session."""
    if item.get_closest_marker(SERIAL_MARKER) is None:
        return
    violation = _serial_guard_violation(item.config, [item.nodeid])
    if violation:
        pytest.fail(violation, pytrace=False)


@pytest.fixture(scope="session", autouse=True)
async def _shutdown_pdf_engine_after_the_session():
    """Stop the persistent Playwright driver inside the test loop.

    Tests that exercise the real PDF engine start a Node subprocess bound to
    the session loop. Without an explicit stop, the transport is garbage
    collected after the loop closes — an unraisable warning that pytest can
    turn into a session error. The app lifespan does this on shutdown; the
    suite must do the same.
    """
    yield
    from app.services.cv.cv_pdf_service import shutdown_engine

    with contextlib.suppress(Exception):
        await shutdown_engine()
