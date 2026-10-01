"""Career's adapters for the family auth-kit protocols (plan 16 P3a).

Career owns its identity models (`app/models/user_model.py`,
`app/models/identity_model.py`) so its single metadata/registry stays
self-contained — never import the kit's ORM classes (gotcha §5.11).

Adapter design: the `nx_auth` protocols are synchronous (auth-kit README
"Scope" — "async consumers hand in their own adapter implementing the
same protocol"), so these adapters run over a dedicated **sync**
sessionmaker on the same database (`app.core.database.AuthSessionLocal`)
— study's `app/auth/stores.py` pattern. FastAPI runs the kit's sync
handlers in the threadpool and the enforcement middleware reads through
them once per request; auth writes are short single-row transactions.

Profile provisioning (identity-auth §6) is wired: user creation creates
the Default profile in the same transaction (career's profile rows keep
their product JSON sections; `profiles` is family 1:N since P3b).
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from datetime import UTC, datetime

from nx_auth.audit import AuditEvent, AuditSink
from nx_auth.lockout import ensure_aware
from nx_auth.protocols import EmailAlreadyExists, SessionRecord, UserRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.identity_model import AuditEvent as AuditEventRow
from app.models.identity_model import AuthSession as AuthSessionRow
from app.models.identity_model import InstanceSetting as InstanceSettingRow
from app.models.matching_model import MatchInsight
from app.models.user_model import Profile as ProfileRow
from app.models.user_model import User as UserRow

_EPOCH: datetime = datetime(1970, 1, 1, tzinfo=UTC)


def _record(row: UserRow) -> UserRecord:
    return UserRecord(
        id=str(row.id),
        email=str(row.email),
        password_hash=row.password_hash,
        full_name=row.full_name,
        is_active=bool(row.is_active),
        is_admin=bool(row.is_admin),
        failed_login_attempts=int(row.failed_login_attempts),
        locked_until=ensure_aware(row.locked_until),
        token_version=int(row.token_version),
        created_at=ensure_aware(row.created_at),
    )


def _session(row: AuthSessionRow) -> SessionRecord:
    return SessionRecord(
        id=str(row.id),
        user_id=str(row.user_id),
        refresh_jti_hash=str(row.refresh_jti_hash),
        expires_at=ensure_aware(row.expires_at) or _EPOCH,
        absolute_expires_at=ensure_aware(row.absolute_expires_at) or _EPOCH,
        revoked_at=ensure_aware(row.revoked_at),
        client_label=row.client_label,
        created_at=ensure_aware(row.created_at),
    )


class CareerUserStore:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self._create_lock = threading.Lock()

    def get(self, user_id: str) -> UserRecord | None:
        with self._factory() as session:
            row = session.get(UserRow, user_id)
            return _record(row) if row is not None else None

    def get_by_email(self, email: str) -> UserRecord | None:
        with self._factory() as session:
            row = session.scalar(select(UserRow).where(UserRow.email == email.lower()))
            return _record(row) if row is not None else None

    def count(self) -> int:
        with self._factory() as session:
            return int(session.scalar(select(func.count()).select_from(UserRow)) or 0)

    def create(
        self,
        *,
        email: str,
        password_hash: str | None,
        full_name: str = "",
        is_admin: bool = False,
        user_id: str | None = None,
    ) -> UserRecord:
        from app.schemas.profile import (
            DEFAULT_ACADEMICS,
            DEFAULT_BASICS,
            DEFAULT_CONSTRAINTS,
            DEFAULT_WORK_PREFERENCES,
        )

        normalized = email.lower().strip()
        # First-user-admin race guard (health's bootstrap pattern, in-process
        # edition): serialize creation so two concurrent registers cannot both
        # observe zero users.
        with self._create_lock, self._factory() as session:
            if session.scalar(select(UserRow.id).where(UserRow.email == normalized)):
                raise EmailAlreadyExists(normalized)
            first = session.scalar(select(func.count()).select_from(UserRow)) or 0
            row = UserRow(
                id=user_id if user_id is not None else uuid.uuid4(),
                email=normalized,
                password_hash=password_hash,
                full_name=full_name,
                is_admin=is_admin or int(first) == 0,
            )
            session.add(row)
            session.flush()  # the profile FK needs the user row visible
            # identity-auth §6: Default profile in the same transaction —
            # a user is never without a profile. Career's product JSON
            # sections get their defaults here (the shape registration
            # always produced).
            session.add(
                ProfileRow(
                    user_id=row.id,
                    name="Default",
                    is_default=True,
                    basics=dict(DEFAULT_BASICS),
                    academics=dict(DEFAULT_ACADEMICS),
                    work_preferences=dict(DEFAULT_WORK_PREFERENCES),
                    constraints=dict(DEFAULT_CONSTRAINTS),
                )
            )
            session.commit()
            session.refresh(row)
            return _record(row)

    def set_login_failures(self, user_id: str, failed: int, locked_until: datetime | None) -> None:
        with self._factory() as session:
            row = session.get(UserRow, user_id)
            if row is not None:
                row.failed_login_attempts = failed
                row.locked_until = locked_until
                row.updated_at = datetime.now(UTC)
                session.commit()

    def reset_login_failures(self, user_id: str) -> None:
        self.set_login_failures(user_id, 0, None)

    def bump_token_version(self, user_id: str) -> int:
        with self._factory() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                return 0
            updated = int(row.token_version) + 1
            row.token_version = updated
            row.updated_at = datetime.now(UTC)
            session.commit()
            return updated

    def set_password(self, user_id: str, password_hash: str) -> None:
        with self._factory() as session:
            row = session.get(UserRow, user_id)
            if row is not None:
                row.password_hash = password_hash
                row.updated_at = datetime.now(UTC)
                session.commit()

    def list(self) -> list[UserRecord]:
        with self._factory() as session:
            rows = session.scalars(
                select(UserRow).order_by(UserRow.created_at.asc(), UserRow.id.asc())
            ).all()
            return [_record(row) for row in rows]

    def set_active(self, user_id: str, is_active: bool) -> None:
        with self._factory() as session:
            row = session.get(UserRow, user_id)
            if row is not None:
                row.is_active = is_active
                row.updated_at = datetime.now(UTC)
                session.commit()

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        with self._factory() as session:
            row = session.get(UserRow, user_id)
            if row is not None:
                row.is_admin = is_admin
                row.updated_at = datetime.now(UTC)
                session.commit()

    def count_admins(self) -> int:
        with self._factory() as session:
            return int(
                session.scalar(
                    select(func.count()).select_from(UserRow).where(UserRow.is_admin.is_(True))
                )
                or 0
            )

    def delete(self, user_id: str) -> None:
        """Cascade delete (identity-auth §12): profile, insights, chats,
        documents, user-scoped AI config and background jobs follow the
        user row through the DB-level ON DELETE CASCADE (the same chain
        the old in-tree `account_service.delete_account` relied on).
        Uploaded files are removed first — rows alone leave them behind."""
        with self._factory() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                return
            self._delete_uploaded_files(session, uuid.UUID(str(row.id)))
            session.delete(row)
            session.commit()

    @staticmethod
    def _delete_uploaded_files(session: Session, user_id: uuid.UUID) -> None:
        from app.models.document_model import Document
        from app.services.document_service import DocumentService

        documents = session.scalars(select(Document).where(Document.user_id == user_id)).all()
        for document in documents:
            file_path = DocumentService.upload_file_path(document)
            if file_path is not None and file_path.is_file():
                with contextlib.suppress(OSError):
                    file_path.unlink()

    def activity_counts(self) -> dict[str, int]:
        """Product-defined activity per user (identity-auth §12): match
        insights — the number the admin listing always showed."""
        counts: dict[str, int] = {}
        with self._factory() as session:
            rows = session.execute(
                select(MatchInsight.user_id, func.count())
                .select_from(MatchInsight)
                .group_by(MatchInsight.user_id)
            ).all()
            for user_id, count in rows:
                counts[str(user_id)] = int(count)
        return counts


class CareerProfileStore:
    """`nx_auth.protocols.ProfileStore` adapter (kit-side provisioning).

    P3b (`profiles` 1:N): `name`/`is_default` are honoured (identity-auth
    §5) and career's product JSON sections get their defaults on every
    provisioned row.
    """

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def create(
        self,
        *,
        user_id: str,
        name: str,
        is_default: bool,
        preferences: dict[str, object] | None = None,
    ) -> str:
        from app.schemas.profile import (
            DEFAULT_ACADEMICS,
            DEFAULT_BASICS,
            DEFAULT_CONSTRAINTS,
            DEFAULT_WORK_PREFERENCES,
        )

        with self._factory() as session:
            row = ProfileRow(
                user_id=uuid.UUID(str(user_id)),
                name=name.strip() or "Default",
                is_default=is_default,
                basics=dict(DEFAULT_BASICS),
                academics=dict(DEFAULT_ACADEMICS),
                work_preferences=dict(DEFAULT_WORK_PREFERENCES),
                constraints=dict(DEFAULT_CONSTRAINTS),
            )
            if preferences:
                row.preferences = dict(preferences)
            session.add(row)
            session.commit()
            session.refresh(row)
            return str(row.id)

    def count_for(self, user_id: str) -> int:
        with self._factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(ProfileRow)
                    .where(ProfileRow.user_id == uuid.UUID(str(user_id)))
                )
                or 0
            )


class CareerSessionStore:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def create(
        self,
        *,
        user_id: str,
        refresh_jti_hash: str,
        expires_at: datetime,
        absolute_expires_at: datetime,
        client_label: str = "",
    ) -> str:
        row = AuthSessionRow(
            id=uuid.uuid4(),
            user_id=uuid.UUID(str(user_id)),
            refresh_jti_hash=refresh_jti_hash,
            expires_at=expires_at,
            absolute_expires_at=absolute_expires_at,
            client_label=client_label,
        )
        with self._factory() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return str(row.id)

    def get(self, family_id: str) -> SessionRecord | None:
        with self._factory() as session:
            row = session.get(AuthSessionRow, family_id)
            return _session(row) if row is not None else None

    def rotate(self, family_id: str, refresh_jti_hash: str, expires_at: datetime) -> None:
        with self._factory() as session:
            row = session.get(AuthSessionRow, family_id)
            if row is not None and row.revoked_at is None:
                row.refresh_jti_hash = refresh_jti_hash
                row.expires_at = expires_at
                session.commit()

    def revoke(self, family_id: str) -> None:
        with self._factory() as session:
            row = session.get(AuthSessionRow, family_id)
            if row is not None and row.revoked_at is None:
                row.revoked_at = datetime.now(UTC)
                session.commit()

    def revoke_all_for_user(self, user_id: str) -> int:
        with self._factory() as session:
            rows = session.scalars(
                select(AuthSessionRow).where(
                    AuthSessionRow.user_id == uuid.UUID(str(user_id)),
                    AuthSessionRow.revoked_at.is_(None),
                )
            ).all()
            for row in rows:
                row.revoked_at = datetime.now(UTC)
            session.commit()
            return len(rows)

    def list_for_user(self, user_id: str) -> list[SessionRecord]:
        with self._factory() as session:
            rows = session.scalars(
                select(AuthSessionRow)
                .where(AuthSessionRow.user_id == uuid.UUID(str(user_id)))
                .order_by(AuthSessionRow.created_at.desc(), AuthSessionRow.id.desc())
            ).all()
            return [_session(row) for row in rows]


class CareerInstanceStore:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def get(self, key: str) -> str | None:
        with self._factory() as session:
            row = session.get(InstanceSettingRow, key)
            return str(row.value) if row is not None else None

    def set(self, key: str, value: str) -> None:
        with self._factory() as session:
            row = session.get(InstanceSettingRow, key)
            if row is None:
                session.add(InstanceSettingRow(key=key, value=value))
            else:
                row.value = value
                row.updated_at = datetime.now(UTC)
            session.commit()


class CareerAuditSink(AuditSink):
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def record(self, event: AuditEvent) -> None:
        row = AuditEventRow(
            actor=str(event.actor),
            action=event.action,
            resource=event.resource,
            tenant_id=event.tenant_id,
            outcome=event.outcome,
            created_at=event.timestamp(),
        )
        with self._factory() as session:
            session.add(row)
            session.commit()
