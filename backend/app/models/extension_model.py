"""Extension sources & installs (plan 32 Phase 3 / ADR-0040 D13+D22).

The import layer's persistence: git sources (https production descriptors
+ the dev/test ``local`` variant) and the extensions installed from them —
digest-pinned, consent-tracked, never auto-enabled. Imported content is
data on disk (``data_dir/extensions/<id>/<digest>/``), never code in the
process (D2's gate point); the runnable surface is the existing ``mcp``
connector (T3 managed spawn from the cloned content).

Status rides the family status vocabulary (``ok | degraded | failing |
stale`` with ``last_success_at`` / ``consecutive_failures``, D21). Consent
records ride the install row (``instance.consentRecord``, D19) and survive
tombstoning (lifecycle law: digest + origin + consent retained).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)

SOURCE_STATUSES = ("ok", "degraded", "failing", "stale")
INSTALL_STATES = ("installed", "disabled", "self-disabled", "removed")
INSTALL_TIERS = ("T0", "T2", "T3")
# Sandbox run outcomes (plan 32 Phase 5): one row per spawned sandbox.
# ``interrupted`` is written by boot reconciliation for runs orphaned by a
# host restart (host death is NOT extension failure — the extension
# survives, the next run re-spawns); ``crashed``/``watchdog`` self-disable
# the extension (ADR-0030: sandbox death is extension failure).
SANDBOX_OUTCOMES = (
    "running",
    "completed",
    "disposed",
    "crashed",
    "watchdog",
    "protocol-violation",
    "interrupted",
)


class ExtensionSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One git source added by an admin (manual) or provisioned by GitOps.

    ``origin`` is the https URL (kind ``git``) or the absolute local path
    (kind ``local`` — dev/test only, gated off in production boots).
    ``descriptor`` is the validated source descriptor verbatim; ``secrets``
    holds atrest-sealed private-repo credential slots (secret-slot
    references resolve here — an inline token is structurally invalid at
    the schema seam, D22). ``candidates`` is the last discovery result:
    what the source currently offers, digests and compat reasons.
    """

    __tablename__ = "extension_sources"
    __table_args__ = (
        UniqueConstraint("origin", name="uq_extension_sources_origin"),
        CheckConstraint("kind IN ('git', 'local')", name="source_kind_allowed"),
        CheckConstraint(
            "status IN ('ok', 'degraded', 'failing', 'stale')",
            name="source_status_allowed",
        ),
        CheckConstraint("consecutive_failures >= 0", name="source_failures_nonneg"),
    )

    origin: Mapped[str] = mapped_column(String(600), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="git")
    descriptor: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    candidates: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    secrets: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ok")
    last_success_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ExtensionInstall(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One imported extension installed from a source — the pinned artifact.

    Digest + origin pinned at install (D7); every consent event appends to
    ``consents`` (who/when/what-digest — verifiable against the digest);
    ``pin_history`` records ref/digest moves. ``enabled`` mirrors the minted
    job source's enable flag and is ONLY ever flipped by an explicit admin
    act — installs, updates and reconcile never auto-enable (D22).
    ``state`` rides the lifecycle vocabulary; ``parked`` marks the GitOps
    parking state (removed from the desired list ⇒ disabled, data intact,
    tombstone-able). Tombstoned rows keep everything — consent records
    included — so a re-import never silently re-enables.
    """

    __tablename__ = "extension_installs"
    __table_args__ = (
        UniqueConstraint("extension_id", name="uq_extension_installs_extension"),
        CheckConstraint(
            "state IN ('installed', 'disabled', 'self-disabled', 'removed')",
            name="install_state_allowed",
        ),
        CheckConstraint("managed_by IN ('manual', 'gitops')", name="install_managed_by_allowed"),
        CheckConstraint("tier IN ('T0', 'T2', 'T3')", name="install_tier_allowed"),
        Index("ix_extension_installs_source", "source_id"),
    )

    extension_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extension_sources.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    manifest: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    pin_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    content_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    tier: Mapped[str] = mapped_column(String(4), nullable=False, default="T3")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="installed")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The T2 state.* seam home (plan 32 Phase 5 / charter `state`
    # capability): extension-owned persistent key/values, host-quota'd by
    # the charter ``limits.stateMaxBytes`` per instance and evictable —
    # distinct from sync cursors (``job_sources.sync_state``), which never
    # cross the sandbox seam (capability-rpc.md §4).
    extension_state: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    managed_by: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    source_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    consents: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    pin_history: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    update: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    parked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    installed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tombstoned_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class ExtensionSandboxRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One spawned T2 sandbox process (plan 32 Phase 5).

    The operational record behind the sandbox lifecycle law: a run row is
    inserted when the child spawns (outcome ``running``) and closed with
    its outcome + capped reason. ``crashed``/``watchdog``/``protocol-
    violation`` mean sandbox death — the host self-disables the extension
    with the surfaced reason (ADR-0030 clause 1). Boot reconciliation
    closes still-open rows as ``interrupted`` — a host restart orphaned
    them, which is never an extension failure (ADR-0030's AppService boot
    pattern, ported)."""

    __tablename__ = "extension_sandbox_runs"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('running', 'completed', 'disposed', 'crashed', 'watchdog', "
            "'protocol-violation', 'interrupted')",
            name="sandbox_run_outcome_allowed",
        ),
        Index("ix_extension_sandbox_runs_install", "install_id"),
    )

    install_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extension_installs.id", ondelete="CASCADE"), nullable=False
    )
    extension_id: Mapped[str] = mapped_column(String(64), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    pid: Mapped[int | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=lambda: datetime.now(UTC)
    )
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
