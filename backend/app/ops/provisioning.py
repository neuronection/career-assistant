"""The one provisioning seam (ADR-0064 §3 / plan 64 §1.2-§1.3).

Runs ONLY inside the one-shot ``migrate`` mode (``python -m careerassistant
migrate``), as the **owner** role. Serving processes never import this
module: under the split credential model their app role is DML-only and
runtime code must never issue DDL (the typed refusals live in
``app.storage.vector_provisioning`` / ``app.ai.checkpointer``).

Order (ADR-0064 §3, adjusted for career's app-table-dependent vector
spaces — ``vec_*`` tables hold a FK into ``vector_records``, so they can
only be provisioned after the Alembic chain created the app schema):

1. create/verify the app role (split mode only);
2. create extensions (``vector``) — owner on self-host, provider admin on
   managed DBs; a failure is a loud warning, never a brick (spaces that
   need it refuse at runtime with guidance);
3. Alembic to head (owner);
4. the LangGraph checkpoint schema (owner) — serving processes open it
   without ``setup()``;
5. provision every known vector space (owner);
6. re-grant and verify: DML grants on everything that now exists, ``ALTER
   DEFAULT PRIVILEGES`` for future objects, then ``has_table_privilege``/
   ``has_schema_privilege`` verification (split mode only).

Legacy single-role installs (no ``CAREER_DB_SPLIT=1``) skip 1/6 entirely —
their serving role is still the owner — while 2-5 still run, so an upgrade
lands with the checkpoint schema and spaces already provisioned.
"""

from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine

from app.core.config import settings

logger = logging.getLogger(__name__)

_SIMPLE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFAULT_APP_USER = "neuronection_career_app"


class ProvisioningError(RuntimeError):
    """The provisioning seam could not complete (migrate exits non-zero)."""


def _sync_engine(url: str) -> Engine:
    """A psycopg engine for the one-shot process (asyncpg URLs rewritten)."""
    if url.startswith("sqlite"):
        raise ProvisioningError(
            "server provisioning is the PostgreSQL path — desktop migrates "
            "locally at boot (python -m careerassistant app/web/seed)"
        )
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    elif not url.startswith("postgresql"):
        raise ProvisioningError(
            f"unsupported datastore URL for provisioning: {url.rsplit('@', 1)[-1]}"
        )
    return create_engine(url)


def _owner_user(engine: Engine) -> str:
    """The role name of the owner connection (for default privileges)."""
    raw = engine.url.username
    if not raw:
        raise ProvisioningError("the migrations URL carries no role name")
    return str(raw)


def _quote_identifier(name: str) -> str:
    if not _SIMPLE_IDENTIFIER.fullmatch(name):
        raise ProvisioningError(f"refusing non-simple role/schema identifier {name!r}")
    return f'"{name}"'


def _password_literal(password: str) -> str:
    """A safely quoted SQL string literal for role DDL.

    ``CREATE ROLE``/``ALTER ROLE`` are utility statements — PostgreSQL
    accepts no bind parameters in them, so the secret must be inlined.
    Standard-conforming string escaping ('' doubling) makes that safe.
    """
    return "'" + password.replace("'", "''") + "'"


def provision_app_role(engine: Engine, app_user: str, app_password: str) -> None:
    """Create/verify the DML-only app role (split mode, step 1)."""
    quoted = _quote_identifier(app_user)
    password_sql = _password_literal(app_password)
    with engine.begin() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": app_user}
        ).scalar()
        if exists is None:
            # Identifier validated above; the password is escaped (see
            # `_password_literal`) and never logged.
            connection.execute(text(f"CREATE ROLE {quoted} LOGIN PASSWORD {password_sql}"))
            logger.info("provision: created app role %s", app_user)
        else:
            # Keep the password in sync with the deployment secret (rotation
            # path: rotate the secret, re-run migrate).
            connection.execute(text(f"ALTER ROLE {quoted} LOGIN PASSWORD {password_sql}"))
            logger.info("provision: app role %s verified", app_user)
        connection.execute(
            text(
                "GRANT CONNECT ON DATABASE "
                f"{_quote_identifier(engine.url.database or '')} TO {quoted}"
            )
        )


def ensure_extensions(engine: Engine) -> list[str]:
    """Create extensions the schema expects (step 2). Owner on self-host.

    Non-fatal by design: on a managed provider the *provider admin*
    (azure_pg_admin / rds_superuser) creates extensions and the product
    owner must not attempt it; on a plain-postgres self-host the image
    simply lacks pgvector. Either way the message names the fix, and
    vector spaces that need the extension refuse at runtime with the same
    guidance.
    """
    created: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        try:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            created.append("vector")
        except Exception as exc:
            logger.warning(
                "provision: the `vector` extension is unavailable (%s) — semantic search "
                "stays degraded. Self-host: run the pgvector/pgvector:pg16 image. Managed: "
                "have the provider admin (azure_pg_admin / rds_superuser) create it.",
                type(exc).__name__,
            )
    return created


def provision_vector_spaces(engine: Engine) -> int:
    """Provision every known vector space as the owner (step 5).

    Idempotent per space (``to_regclass``/dimension checks); a space that
    cannot provision (missing extension, dim ceiling) is a loud warning and
    the migrate job still succeeds — the app refuses writes for it with
    typed guidance instead of attempting DDL.
    """
    from sqlalchemy.orm import sessionmaker

    from app.models.vector_model import VectorSpace as VectorSpaceRow
    from app.storage.vector_provisioning import provision_space

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        rows = list(
            session.scalars(select(VectorSpaceRow).order_by(VectorSpaceRow.created_at)).all()
        )
    provisioned = 0
    for row in rows:
        with factory() as session:
            target = session.get(VectorSpaceRow, row.id)
            if target is None:  # pragma: no cover - listed a moment ago
                continue
            try:
                provision = provision_space(session, target, allow_split=True)
            except Exception as exc:
                logger.warning(
                    "provision: vector space %r could not be provisioned (%s)",
                    row.name,
                    exc,
                )
                continue
            provisioned += 1
            logger.info("provision: vector space %r → %s", row.name, provision.detail)
    return provisioned


def grant_app_role(engine: Engine, app_user: str) -> list[str]:
    """Re-grant DML + default privileges, then verify (step 6).

    The refusal side is part of the contract: the app role must NOT hold
    schema-level CREATE — a grant refactor that hands it DDL rights fails
    the migrate job here instead of silently reviving runtime DDL.
    """
    quoted = _quote_identifier(app_user)
    owner = _quote_identifier(_owner_user(engine))
    statements = [
        f"GRANT USAGE ON SCHEMA public TO {quoted}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {quoted}",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        # Hard checks: DML where the app needs it, DDL nowhere.
        for table in ("users", "checkpoints", "vector_spaces", "alembic_version"):
            ok = connection.execute(
                text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                {"role": app_user, "table": table},
            ).scalar()
            if not ok:
                raise ProvisioningError(
                    f"verification failed: app role {app_user!r} cannot SELECT {table!r} "
                    "(was the table created after the grants?)"
                )
        ddl = connection.execute(
            text("SELECT has_schema_privilege(:role, 'public', 'CREATE')"),
            {"role": app_user},
        ).scalar()
        if ddl:
            raise ProvisioningError(
                f"verification failed: app role {app_user!r} holds CREATE on schema public "
                "— the split contract requires a DML-only app role (ADR-0064)"
            )
    logger.info("provision: app role %s granted (DML-only) and verified", app_user)
    return statements


def run_server_provisioning() -> None:
    """The one-shot migrate entry: the full seam, in order.

    Sync by design: Alembic's env.py drives the async engine with its own
    ``asyncio.run()``, so this must not already sit inside an event loop.
    """
    from app.ai.checkpointer import provision_postgres_checkpoints
    from app.local import run_migrations

    # The broken half-configured split refuses loudly (ADR-0064 §4).
    split = settings.db_credential_mode == "split"  # may raise SplitCredentialConfigError
    owner_url = settings.migrations_database_url or settings.database_url
    # Alembic's env.py and the checkpoint saver read `settings.database_url`:
    # rebind the ONE-SHOT process to the owner DSN so a migrate service that
    # carries only the migrations URL still migrates as owner. Never done on
    # a serve path (this process exits after provisioning).
    settings.database_url = owner_url

    engine = _sync_engine(owner_url)
    try:
        app_user = settings.db_app_user or _DEFAULT_APP_USER
        app_password = settings.db_password
        if split and not app_password:
            raise ProvisioningError(
                "split mode needs the app-role password (CAREER_DB_PASSWORD) to "
                "provision the DML-only app role"
            )

        # 1. role (split only) — before grants exist to anchor.
        if split and app_password:
            provision_app_role(engine, app_user, app_password)

        # 2. extensions → 3. Alembic → 4. checkpoint schema → 5. spaces.
        ensure_extensions(engine)
        run_migrations()
        asyncio.run(provision_postgres_checkpoints(owner_url))
        provisioned = provision_vector_spaces(engine)
        logger.info("provision: %d vector space(s) provisioned", provisioned)

        # 6. re-grant + verify (split only).
        if split:
            grant_app_role(engine, app_user)
    finally:
        engine.dispose()
    logger.info("provision: complete (mode=%s)", settings.db_credential_mode)
