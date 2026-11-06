# ruff: noqa: E501 -- long immutable template/message strings; reflow when touched
"""Postings service (Phase 26): sync, skill-ID mapping, fit deltas,
listings, interactions, alerts, expiry.

Mapping is literal-ID only: keyword/alias extraction resolves taxonomy
skills, an audited AI pass covers the rest, and catalog matching is an
intersection over `job_skills`/`posting_skills` FK ids — labels never
match."""

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.extensions import registry
from app.models.application_model import Application
from app.models.enums import (
    MappingMethod,
    NotificationRuleKind,
    PostingEvidence,
    PostingSkillPriority,
    SourceQueryMode,
)
from app.models.experience_model import Organization
from app.models.job_model import Job, JobSkill
from app.models.posting_model import (
    JobPosting,
    JobSource,
    PostingInteraction,
    PostingSkill,
)

if TYPE_CHECKING:
    from app.services.catalog.organization_service import OrganizationService
    from app.services.postings.mapping_policy import MappingPolicy
from app.models.taxonomy_model import Skill
from app.schemas.posting import PostingSkillRefOut
from app.services.postings.salary import annualized

logger = logging.getLogger(__name__)

AUTO_MAP_THRESHOLD = 0.34
#: Plan 164 mapping provenance version. Rows below this value are not
#: re-mapped by this slice; the POSTING_REMAP seam re-decides the semantic
#: subset on a space cutover (plan 50 §7.2, plan 164 S3).
MAPPING_VERSION = 2
FRESH_DECAY_PER_WEEK = 0.5
FRESH_DECAY_CAP = 2.0
POSTING_MAX_AGE_DAYS = 45

SKILL_ALIASES_EXTRA = {
    "js": "javascript",
    "nodejs": "node",
    "golang": "go",
    "py": "python",
    "postgres": "postgresql",
    "k8s": "kubernetes",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _norm(token: str) -> str:
    return SKILL_ALIASES_EXTRA.get(token.strip().lower(), token.strip().lower())


# ------------------------------------------------------------------- sync


def resolve_source_secrets(source: JobSource) -> dict[str, str]:
    """Decrypt the source's sealed secret slots (D19/INV-4) — values exist
    only here, host-side, for the duration of one fetch."""
    from app.core.encryption import decrypt_secret

    resolved: dict[str, str] = {}
    for slot, sealed in (source.secrets or {}).items():
        value = decrypt_secret(sealed) if isinstance(sealed, str) else None
        if value:
            resolved[str(slot)] = value
    return resolved


def _record_health(source: JobSource, errors: list[dict]) -> None:
    """Source health badge: failed / degraded (partial errors) / ok."""
    from app.models.enums import HealthStatus

    if errors:
        source.last_status = HealthStatus.DEGRADED.value
    else:
        source.last_status = HealthStatus.OK.value


async def _query_overlay(db: AsyncSession, source: JobSource, connector) -> tuple[dict | None, str]:
    """Plan 130 radar mode: the next rotated role group arrives as a
    call-time ``config["query"]`` overlay — never stored, never fanned
    out (one focused query per sync). ``None`` config = polite skip.

    A source left in radar mode over a connector that cannot rotate
    queries (no ``dynamic_queries``) normalizes to ``static`` — the label
    then matches the behavior instead of silently doing nothing."""
    call_config = dict(source.config or {})
    if not getattr(connector.capabilities, "dynamic_queries", False):
        if source.query_mode == SourceQueryMode.RADAR.value:
            source.query_mode = SourceQueryMode.STATIC.value
            await db.commit()
        return call_config, ""
    if source.query_mode != SourceQueryMode.RADAR.value:
        return call_config, ""
    from sqlalchemy.orm.attributes import flag_modified

    from app.services.postings import query_curator

    cache = await query_curator.ensure_query_cache(db, source)
    query = query_curator.take_rotation(cache, source.query_batch_size)
    if not query.get("groups"):
        return None, "radar has no keywords yet — nothing to search"
    query_curator.advance_rotation(cache, source.query_batch_size)
    source.query_cache = cache
    flag_modified(source, "query_cache")
    await db.commit()
    call_config["query"] = {
        "groups": query["groups"],
        "location": query["groups"][0].get("location", ""),
    }
    searched = " | ".join(group["keywords"] for group in query["groups"])
    note = f"searching radar group(s) {query['rotation']}: {searched}"
    if query["groups"][0].get("location"):
        note += f" @ {query['groups'][0]['location']}"
    return call_config, note


async def sync_source(
    db: AsyncSession, source: JobSource, *, transport=None, trigger: str = "scheduled"
) -> dict:
    """Fetch via the connector through the polite runtime, upsert postings,
    map, alert — recording one row of the plan-134 run ledger per attempt.

    A failing connector errors its own source row — never the queue or
    other sources. T1 built-ins get the injected polite transport; T2
    imports resolve through the registry onto the sandbox runner (their
    net rides the seam, not this transport)."""
    started = _utcnow()
    run_row = await _begin_run(db, source, trigger=trigger, started=started, stage="fetching")
    try:
        report = await _sync_source_inner(
            db, source, transport=transport, run_id=run_row.id if run_row else None, trigger=trigger
        )
    except Exception as exc:
        report = {"synced": 0, "error": f"{type(exc).__name__}: {exc}"[:2000]}
    try:
        from app.services.postings.detail_service import enqueue_details

        queued = await enqueue_details(db, source)
        if queued:
            report["detail_queued"] = queued
    except Exception:
        logger.warning("detail enrichment enqueue failed for %s", source.key, exc_info=True)
    try:
        from app.services.catalog.company_triage_service import enqueue_company_triage

        if await enqueue_company_triage(db):
            report["company_triage_queued"] = 1
    except Exception:
        logger.warning("company triage enqueue failed for %s", source.key, exc_info=True)
    if run_row is not None:
        await _finish_run(db, run_row.id, started=started, report=report)
    await _pause_on_operator_action(db, source, report)
    return report


PAUSE_ON_CODES = frozenset({"provider", "auth", "needs-secret", "unsupported"})


def _pause_reason(errors: list[dict]) -> str:
    """The first typed error that needs a human (a provider block, a
    sign-in wall, missing credentials, an unsupported host) — retrying
    those on the schedule only deepens the problem, so the source pauses
    instead (plan 174 follow-up: hourly retries against a Cloudflare block
    refresh the bot score and extend it)."""
    for error in errors:
        if error.get("code") in PAUSE_ON_CODES and error.get("retryable") != "yes":
            return f"{error.get('code')}: {error.get('detail')}"
    return ""


async def _pause_on_operator_action(db: AsyncSession, source: JobSource, report: dict) -> None:
    """Auto-pause on a non-retryable operator-action error + alert admins.

    The run itself keeps its honest status; the pause stops the scheduler
    (and the sources list's paused filter) from retrying an external block
    every hour. Resuming stays an explicit user act."""
    if source.paused_at is not None:
        return
    reason = _pause_reason(report.get("errors") or [])
    if not reason:
        return
    source.paused_at = _utcnow()
    source.error = f"{reason} — source paused until you resume it"[:2000]
    await db.commit()
    await _notify_source_paused(db, source, reason)


async def _notify_source_paused(db: AsyncSession, source: JobSource, reason: str) -> None:
    from app.models.user_model import User
    from app.services.notification_service import NotificationService

    admins = (await db.execute(select(User.id).where(User.is_admin.is_(True)))).scalars().all()
    name = getattr(source, "title", None) or source.key
    for user_id in list(admins)[:20]:
        await NotificationService(db).emit(
            "background_failed",
            [user_id],
            title=f"Job source paused: {name}",
            body=(
                f"{reason[:300]} — the source was paused so the scheduler stops "
                "retrying; resume it when the provider is reachable again."
            ),
            payload={"source_id": str(source.id), "link": f"/sources/{source.id}"},
            source_ref={"source_id": str(source.id)},
            dedup_key=f"source-paused:{source.id}:{user_id}",
            dedup_ttl_days=1,
            max_per_day=10,
        )


def _run_status(report: dict) -> str:
    if report.get("error"):
        return "failed"
    if report.get("errors"):
        return "degraded"
    if report.get("note") and not report.get("synced"):
        return "skipped"
    return "ok"


STALE_RUN_MINUTES = 30
RUN_ERRORS_WITH_SUMMARY = 10


async def _begin_run(
    db: AsyncSession, source: JobSource, *, trigger: str, started: datetime, stage: str
):
    """Open the ledger row at run START (live status + stage on the
    management page) — best-effort, never fails the run it records.
    Self-healing: stale running rows (a crash left them behind) close as
    interrupted so a ghost never lingers."""
    from app.models.posting_model import SourceRun

    try:
        cutoff = started - timedelta(minutes=STALE_RUN_MINUTES)
        stale = (
            (
                await db.execute(
                    select(SourceRun).where(
                        SourceRun.source_id == source.id,
                        SourceRun.status == "running",
                        SourceRun.started_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in stale:
            row.status = "failed"
            row.error = "interrupted — the run never finished"
            row.finished_at = started
        row = SourceRun(
            source_id=source.id,
            trigger=trigger if trigger in ("manual", "scheduled") else "scheduled",
            status="running",
            started_at=started,
            report={"stage": stage},
        )
        db.add(row)
        await db.commit()
        return row
    except Exception:
        logger.warning("run ledger begin failed for source %s", source.key, exc_info=True)
        return None


async def _update_run_progress(db: AsyncSession, run_id, *, stage: str, **extra) -> None:
    """Live progress into the open row's report — best-effort."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.models.posting_model import SourceRun

    try:
        row = await db.get(SourceRun, run_id)
        if row is None or row.status != "running":
            return
        row.report = {**(row.report or {}), "stage": stage, **extra}
        flag_modified(row, "report")
        await db.commit()
    except Exception:
        logger.warning("run ledger progress write failed", exc_info=True)


async def _finish_run(db: AsyncSession, run_id, *, started: datetime, report: dict) -> None:
    """Settle the open row with its final status — best-effort, never
    fails the run it records."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.models.posting_model import SourceRun

    try:
        row = await db.get(SourceRun, run_id)
        if row is None:
            return
        finished = _utcnow()
        errors = report.get("errors") or []
        error_text = str(report.get("error") or "")
        if not error_text and errors:
            error_text = "; ".join(
                f"{entry.get('code')}: {entry.get('detail')}" for entry in errors[:5]
            )
        bounded = dict(report)
        if bounded.get("run_summary") is not None:
            # A run summary present: bound the errors COUNT so the pair
            # fits the report cap — the summary survives, errors truncate
            # (plan 003 amendment 5) instead of waiting for the whole-report
            # pop below.
            errors_list = bounded.get("errors") or []
            if len(errors_list) > RUN_ERRORS_WITH_SUMMARY:
                bounded["errors"] = errors_list[:RUN_ERRORS_WITH_SUMMARY]
                bounded["errors_truncated"] = True
        if len(json.dumps(bounded, default=str)) > 8_192:
            bounded.pop("errors", None)
            bounded["errors_truncated"] = True
        row.status = _run_status(report)
        row.finished_at = finished
        row.duration_ms = int((finished - started).total_seconds() * 1000)
        row.items_synced = int(report.get("synced") or 0)
        row.error = error_text[:2000]
        row.report = bounded
        flag_modified(row, "report")
        await db.commit()
    except Exception:
        logger.warning("run ledger write failed", exc_info=True)


async def _sync_source_inner(
    db: AsyncSession, source: JobSource, *, transport=None, run_id=None, trigger: str = "scheduled"
) -> dict:
    from app.extensions.polite_http import PoliteHttpError
    from app.extensions.runtime.http import build_transport
    from app.extensions.runtime.sandbox.connector import SandboxConnector
    from app.extensions.sdk import ConnectorError

    try:
        connector = await registry.resolve_connector(db, source.connector_key)
    except ValidationError as exc:
        source.error = str(exc)
        source.last_status = "failed"
        await db.commit()
        return {"synced": 0, "error": str(exc)}
    secrets = resolve_source_secrets(source)
    missing = [
        slot
        for slot in connector.secret_slots()
        if connector.capabilities.requires_credentials and not secrets.get(slot)
    ]
    if missing:
        error = ConnectorError.needs_secret(f"missing secret slot(s): {', '.join(sorted(missing))}")
        source.error = f"{error.code}: {error.detail}"
        source.last_status = "failed"
        await db.commit()
        return {"synced": 0, "error": source.error, "errors": [error.model_dump(mode="json")]}
    runtime_transport = transport or build_transport(
        domains=frozenset(connector.capabilities.network_scopes or []),
        requests_per_minute=connector.capabilities.max_requests_per_minute,
    )
    audit = None
    if isinstance(connector, SandboxConnector):
        from app.extensions.runtime.sandbox import sandbox_capability_auditor

        audit = sandbox_capability_auditor(db, source.key)
    elif getattr(connector, "audits_effects", False):
        from app.extensions.runtime.mcp import mcp_effect_auditor

        audit = mcp_effect_auditor(db, source.key)
    try:
        call_config, query_note = await _query_overlay(db, source, connector)
    except Exception:
        logger.warning("query overlay failed for source %s", source.key, exc_info=True)
        if source.query_mode == SourceQueryMode.RADAR.value:
            source.last_status = "ok"
            source.error = ""
            source.last_run_at = _utcnow()
            await db.commit()
            return {"synced": 0, "note": "radar query unavailable this run — skipped"}
        call_config, query_note = dict(source.config or {}), ""
    if call_config is None:
        source.last_status = "ok"
        source.error = ""
        source.last_run_at = _utcnow()
        await db.commit()
        return {"synced": 0, "note": query_note}
    try:
        result = await connector.fetch(
            call_config,
            source.sync_state or {},
            transport=runtime_transport,
            secrets=secrets,
            audit=audit,
        )
    except PoliteHttpError as exc:
        error = ConnectorError.from_polite(exc)
        source.error = f"{error.code}: {error.detail}"
        source.last_status = "failed"
        source.last_run_at = _utcnow()
        await db.commit()
        return {"synced": 0, "error": source.error, "errors": [error.model_dump(mode="json")]}
    except Exception:
        logger.warning(
            "connector %s failed while fetching source %s",
            source.connector_key,
            source.key,
            exc_info=True,
        )
        error = ConnectorError(
            code="io",
            detail=(
                f"the {source.connector_key} connector failed — check its configuration "
                "and the server log"
            ),
            retryable="after-config-change",
        )
        source.error = f"{error.code}: {error.detail}"[:2000]
        source.last_status = "failed"
        source.last_run_at = _utcnow()
        await db.commit()
        return {"synced": 0, "error": source.error, "errors": [error.model_dump(mode="json")]}

    if run_id is not None:
        await _update_run_progress(db, run_id, stage="ingesting")
    synced = 0
    errors = [error.model_dump(mode="json") for error in result.partial_errors]
    fresh: list[tuple[JobPosting, bool]] = []
    from app.services.catalog.organization_service import OrganizationService

    org_service = OrganizationService(db)
    for raw in result.items:
        try:
            posting = await upsert_posting(
                db, source, raw, org_service=org_service, run_id=run_id, trigger=trigger
            )
            if posting is not None:
                synced += 1
                demand = False
                if posting.status == "mapped":
                    recipients = await check_new_posting_alerts(db, posting)
                    demand = bool(recipients)
                fresh.append((posting, demand))
        except ValidationError as exc:
            errors.append(
                ConnectorError(
                    code="invalid",
                    detail=f"{raw.external_id}: {exc}"[:500],
                    retryable="no",
                ).model_dump(mode="json")
            )
    source.sync_state = result.next_state or {}
    source.last_run_at = _utcnow()
    source.error = "; ".join(f"{error['code']}: {error['detail']}" for error in errors)[:2000]
    _record_health(source, errors)
    await db.commit()
    # Deep extraction is queued, never blocking the sync path;
    # demand-matched postings enqueue first (oldest-first claim order).
    from app.services.postings.detail_service import detail_mode
    from app.services.postings.extract_service import plan_extractions

    if detail_mode(source) in ("smart", "all"):
        # Deferred: the deep pass would run on description-less list cards.
        # The detail enrichment re-queues it once descriptions land.
        extract_queued = 0
        backlog_remaining = 0
    else:
        plan = await plan_extractions(db, fresh, backlog=True)
        extract_queued = plan.queued
        backlog_remaining = plan.backlog_remaining
    report: dict = {
        "synced": synced,
        "extract_queued": extract_queued,
        "backlog_remaining": backlog_remaining,
        "errors": errors,
    }
    if query_note:
        report["note"] = query_note
    if result.run_summary is not None:
        report["run_summary"] = result.run_summary
    return report


async def upsert_posting(
    db: AsyncSession,
    source: JobSource,
    raw,
    org_service: "OrganizationService | None" = None,
    *,
    run_id=None,
    trigger: str = "scheduled",
) -> JobPosting | None:
    """Dedup by (source_id, external_id) + content_hash — unchanged content
    is a no-op; changed content re-maps unless a human mapped it.

    `org_service` threads one matcher (one candidate load) through a sync
    batch — the per-posting N+1 the plan 135 ingest step removes. The
    change journals as `sync_run` (same transaction; `map_posting` and
    `attach_to_posting` journal their own slices).
    """
    from time import perf_counter

    from app.services.postings.change_journal import (
        SYNC_FIELDS,
        PostingChangeJournal,
        raw_summary,
        snapshot,
    )

    started = perf_counter()
    rows = await db.execute(
        select(JobPosting).where(
            JobPosting.source_id == source.id, JobPosting.external_id == raw.external_id
        )
    )
    posting = rows.scalars().first()
    content = raw.model_dump(mode="json")
    content_hash = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    if posting is not None and posting.content_hash == content_hash:
        return None
    before = None
    if posting is not None:
        before = {**snapshot(posting, SYNC_FIELDS), "raw_summary": raw_summary(posting)}
    content_changed = posting is not None
    if posting is None:
        posting = JobPosting(
            source_id=source.id, external_id=raw.external_id, content_hash=content_hash
        )
        db.add(posting)
    else:
        posting.content_hash = content_hash
    posting.title = raw.title[:300]
    posting.org = raw.org[:200]
    if (posting.org or "").strip():
        if org_service is None:
            from app.services.catalog.organization_service import OrganizationService

            org_service = OrganizationService(db)
        # The PK is assigned at INSERT — the org-match journal below takes
        # posting.id, and a decision that doesn't flush (a link to an
        # existing org) would hand it None (plan 176 follow-up).
        await db.flush()
        await org_service.attach_to_posting(posting, run_id=run_id)
    posting.location = raw.location.model_dump(mode="json")
    posting.url = raw.url[:1000]
    posting.seniority = raw.seniority
    posting.employment_type = raw.employment_type
    posting.contract_type = raw.contract_type
    posting.onsite_policy = raw.onsite_policy
    posting.work_hours = raw.work_hours
    posting.hours_per_week_min = raw.hours_per_week_min
    posting.hours_per_week_max = raw.hours_per_week_max
    posting.travel_class = raw.travel_class
    posting.education_level = raw.education_level
    posting.salary_currency = raw.salary.currency if raw.salary else None
    posting.salary_min = raw.salary.min if raw.salary else None
    posting.salary_max = raw.salary.max if raw.salary else None
    posting.salary_period = raw.salary.period if raw.salary else None
    posting.salary_basis = raw.salary.basis if raw.salary else None
    norm_low, norm_high = annualized(
        raw.salary.min if raw.salary else None,
        raw.salary.max if raw.salary else None,
        raw.salary.period if raw.salary else None,
    )
    posting.salary_normalized_min = norm_low
    posting.salary_normalized_max = norm_high
    posting.posted_at = raw.posted_at or posting.posted_at or _utcnow()
    posting.expires_at = raw.expires_at
    posting.raw = raw.raw or {}
    if posting.status == "expired":
        posting.status = "new"
    posting.raw = {**(raw.raw or {}), "_skills_raw": list(raw.skills_raw)[:60]}
    if posting.mapping_method != MappingMethod.MANUAL.value:
        await map_posting(db, posting, tokens=raw.skills_raw, run_id=run_id)
    if content_changed:
        # Content changed ⇒ any previous deep extract is stale —
        # reset so the queued pass re-runs.
        posting.extract = {}
        posting.extract_version = None
        posting.needs_review = False
    await db.flush()
    actor_ref: dict = {"trigger": trigger}
    if run_id is not None:
        actor_ref["run_id"] = str(run_id)
    PostingChangeJournal.record(
        db,
        posting.id,
        "sync_run",
        actor_ref=actor_ref,
        operation={"source": source.key, "connector": source.connector_key},
        duration_ms=int((perf_counter() - started) * 1000),
        before=before,
        after={**snapshot(posting, SYNC_FIELDS), "raw_summary": raw_summary(posting)},
    )
    return posting


# ----------------------------------------------------------------- mapping


def _taxonomy_index_rows(rows: list[Skill]) -> dict[str, UUID]:
    """lower(alias/label/key) + extra aliases → skill_id over loaded rows.

    Active rows claim their tokens first; a deprecated row fills only
    tokens no active row claimed (exact key/label — a merged-away row's
    aliases live on the surviving skill). A merged-away label row can
    never shadow the surviving skill whose alias carries the label
    (decision 6), while a deprecated row still answers its own unmatched
    key/label so a posting tagged to it survives every re-map — the same
    fallback order `SkillService.resolve` answers with.
    """
    index: dict[str, UUID] = {}
    for skill in rows:
        if skill.status == "deprecated":
            continue
        index[_norm(skill.key)] = skill.id
        index[_norm(skill.label)] = skill.id
        for alias in skill.aliases or []:
            index[_norm(str(alias))] = skill.id
    for skill in rows:
        if skill.status != "deprecated":
            continue
        index.setdefault(_norm(skill.key), skill.id)
        index.setdefault(_norm(skill.label), skill.id)
    return index


async def _taxonomy_index(db: AsyncSession) -> dict[str, UUID]:
    """The matchable skill index over every skill row (see
    `_taxonomy_index_rows` for the precedence law)."""
    rows = (await db.execute(select(Skill))).scalars().all()
    return _taxonomy_index_rows(list(rows))


def _match_keywords(text: str, index: dict[str, UUID]) -> dict[str, UUID]:
    """Whole-token scan over the alias index (explicit hits). Punctuation is
    neutralized so 'Python, SQL' still matches both."""
    normalized = text.lower()
    for char in ",;|/()[]":
        normalized = normalized.replace(char, " ")
    haystack = f" {normalized} "
    found: dict[str, UUID] = {}
    for token in sorted(index, key=len, reverse=True):
        if token and f" {token} " in haystack:
            found.setdefault(token, index[token])
    return found


async def map_posting(
    db: AsyncSession, posting: JobPosting, tokens: list[str] | None = None, *, run_id=None
) -> None:
    """Extract taxonomy skills (alias index first, audited AI second) and
    map onto the catalog by skill-ID intersection; below threshold stays
    unmapped for moderation. Journals the re-tag (`retag`): the skills
    set-diff (pre-state loaded before the delete) plus the mapping
    fields, in this same transaction."""
    from app.services.postings.change_journal import (
        RETAG_FIELDS,
        PostingChangeJournal,
        skills_state,
        snapshot,
    )

    before = {**snapshot(posting, RETAG_FIELDS), "skills": await skills_state(db, posting.id)}
    index = await _taxonomy_index(db)
    tokens = tokens if tokens is not None else _posting_skill_tokens(posting)
    description = str((posting.raw or {}).get("description") or "")
    haystack = " ".join([posting.title, *tokens, description])
    explicit = _match_keywords(haystack, index)

    inferred: dict[str, UUID] = {}
    confidence_ai = 0.6
    if len(explicit) < 2 and description:
        try:
            inferred = await _ai_extract_skills(db, posting, index)
        except Exception:
            inferred = {}

    skills: dict[UUID, tuple[str, float]] = {}
    for skill_id in explicit.values():
        skills.setdefault(skill_id, (PostingEvidence.EXPLICIT.value, 1.0))
    for skill_id in inferred.values():
        skills.setdefault(skill_id, (PostingEvidence.INFERRED.value, confidence_ai))

    await db.execute(
        PostingSkill.__table__.delete().where(  # type: ignore[attr-defined]
            PostingSkill.posting_id == posting.id
        )
    )
    for skill_id, (evidence, confidence) in skills.items():
        db.add(
            PostingSkill(
                posting_id=posting.id,
                skill_id=skill_id,
                evidence=evidence,
                confidence=confidence,
            )
        )
    await db.flush()
    # The skill rewrite journals ITS mutation (plan-142 gate: every writer
    # calls the seam); the mapping decision journals separately below.
    PostingChangeJournal.record(
        db,
        posting.id,
        "retag",
        actor_ref={"run_id": str(run_id)} if run_id is not None else None,
        operation={"auto_map_threshold": AUTO_MAP_THRESHOLD},
        before=before,
        after={**snapshot(posting, RETAG_FIELDS), "skills": await skills_state(db, posting.id)},
    )

    await decide_catalog(db, posting, set(skills), run_id=run_id, defer_semantic=True)


async def decide_catalog(
    db: AsyncSession,
    posting: JobPosting,
    skill_ids: set[UUID],
    *,
    run_id=None,
    defer_semantic: bool = False,
    policy: "MappingPolicy | None" = None,
    skip_semantic_indexing: bool = False,
) -> MappingMethod | None:
    """The catalog decision seam (plan 185 + plan 50 P2b/P2c.3).

    The deterministic weighted skill overlap stays the gate and the primary
    decision. Two semantic stages are bounded by it:

    * a **rerank** of the stage-2 candidates when the deterministic outcome
      is ambiguous (best below ``τ_job`` or a runner-up margin under
      ``δ``), using plan 164 S4.4's ``0.75/0.25`` blend — it may only
      reorder the deterministic candidate set; gated by its own
      ``catalog.semantic_rerank`` switch (default OFF);
    * the plan-185 **rescue**, only where the overlap missed, gated by the
      same shared resolved skill and the published status, behind its own
      ``catalog.semantic_rescue`` switch.

    The two switches are independent: turning rescue off never disables the
    rerank and vice versa. With the rerank switch off the decision is
    bit-identical to the pre-rerank path (no rerank call, no rerank
    candidates beyond the deterministic trace).

    ``defer_semantic=True`` is the request-path form (plan 50 P2c.3): the
    deterministic decision is computed exactly as if both switches were off,
    BUT a needed semantic stage is recorded as
    ``posting_facts["mapping_signals"]["semantic_pending"]`` and one
    single-posting ``POSTING_REMAP`` job is queued **in the caller's
    transaction** to finish the decision off the request path. No
    embed/index/match call happens here. The worker re-runs this seam with
    ``defer_semantic=False`` and overwrites ``mapping_signals`` with the
    final trace; because that call cannot defer again, the loop terminates
    after one pass.

    Semantic never introduces a candidate into the rerank and never
    resurrects a gated-out row. Writes the mapping fields + status, the
    versioned ``mapping_features`` provenance payload and ``mapping_version``,
    journals one ``retag`` row (unchanged shape) and merges both raw scores,
    the candidate trace, the rerank trace and the space key into
    ``posting_facts["mapping_signals"]`` (in place — ``apply_extract`` owns
    other keys in the same dict).

    NEVER touches ``PostingSkill`` rows: only ``map_posting``'s skill
    writing path rewrites them, so the post-extract re-decision (S3)
    leaves levels/priority intact.

    A ``manual`` mapping is a human decision: the seam returns without
    touching any field, so no automatic path (rerank, rescue, remap) can
    overwrite it even when a caller forgets the guard. Terminal postings
    (``expired``/``hidden``) are frozen the same way — never re-decided,
    never queued.
    """
    if posting.mapping_method == MappingMethod.MANUAL.value:
        return None

    from sqlalchemy.orm.attributes import flag_modified

    from app.services.postings.catalog_settings import (
        semantic_rerank_enabled,
        semantic_rescue_enabled,
    )
    from app.services.postings.change_journal import (
        RETAG_FIELDS,
        PostingChangeJournal,
        skills_state,
        snapshot,
    )
    from app.services.postings.mapping_candidates import catalog_candidates
    from app.services.postings.mapping_features import build_mapping_features
    from app.services.postings.mapping_outcome import (
        MappingOutcomeReason,
        MappingOutcomeState,
        write_mapping_outcome,
    )
    from app.services.postings.mapping_policy import load_mapping_policy
    from app.services.postings.mapping_remap import (
        TERMINAL_POSTING_STATUSES,
        enqueue_semantic_redecision,
    )
    from app.services.postings.semantic_rerank import (
        RERANK_BLEND_DETERMINISTIC,
        RERANK_BLEND_SEMANTIC,
        RERANK_CANDIDATE_K,
        not_run_rerank,
        semantic_rerank_signal,
    )
    from app.services.postings.semantic_rescue import (
        not_run_signal,
        semantic_catalog_signal,
    )

    if posting.status in TERMINAL_POSTING_STATUSES:
        return None

    before = {
        **snapshot(posting, RETAG_FIELDS),
        "skills": await skills_state(db, posting.id),
    }

    policy = policy or await load_mapping_policy(db)
    tau_job = policy.tau_job
    delta_margin = policy.delta
    semantic_threshold = policy.semantic_threshold
    semantic_min_shared = policy.semantic_min_shared_skills

    candidates = await catalog_candidates(db, skill_ids, k=RERANK_CANDIDATE_K) if skill_ids else []
    overlap_job = candidates[0].job if candidates else None
    overlap_score = candidates[0].score if candidates else None
    runner_up = candidates[1].score if len(candidates) > 1 else None
    overlap_cleared = (
        overlap_score is not None and overlap_job is not None and overlap_score >= tau_job
    )
    ambiguous = (
        bool(candidates)
        and overlap_score is not None
        and (overlap_score < tau_job or (overlap_score - (runner_up or 0.0)) < delta_margin)
    )

    rescue_enabled = await semantic_rescue_enabled(db)
    rerank_enabled = await semantic_rerank_enabled(db)
    pending_stages: list[str] = []
    if rerank_enabled and ambiguous:
        pending_stages.append("rerank")
    if rescue_enabled and not overlap_cleared:
        pending_stages.append("rescue")
    deferred = bool(skill_ids) and bool(pending_stages) and defer_semantic

    rerank = not_run_rerank(threshold=tau_job)
    semantic = not_run_signal()
    if not defer_semantic:
        if skill_ids and ambiguous and rerank_enabled:
            rerank = await semantic_rerank_signal(
                db,
                posting,
                candidates,
                threshold=tau_job,
                margin=delta_margin,
                skip_indexing=skip_semantic_indexing,
            )
        if skill_ids and not overlap_cleared and rescue_enabled and not rerank.accepted:
            semantic = await semantic_catalog_signal(
                db,
                posting,
                skill_ids,
                threshold=semantic_threshold,
                skip_indexing=skip_semantic_indexing,
            )

    if not skill_ids:
        mapped: MappingMethod | None = None
        posting.catalog_job_id = None
        posting.mapping_method = None
        posting.mapping_confidence = None
        posting.mapping_reason = "no taxonomy skills recognised"
        posting.status = "new" if posting.status == "mapped" else posting.status
        outcome_reason = MappingOutcomeReason.NO_SKILLS
    elif overlap_cleared and overlap_job is not None and overlap_score is not None:
        if (
            rerank.accepted
            and rerank.top_candidate is not None
            and rerank.top_candidate.job_id != str(overlap_job.id)
        ):
            top = rerank.top_candidate
            mapped = MappingMethod.SEMANTIC_RERANK
            posting.catalog_job_id = UUID(top.job_id)
            posting.mapping_method = MappingMethod.SEMANTIC_RERANK.value
            posting.mapping_confidence = round(top.blend, 3)
            posting.mapping_reason = (
                f"semantic rerank {top.blend:.2f} above {tau_job} "
                f"(deterministic {top.deterministic:.2f}, semantic {top.semantic:.2f}; "
                f"margin {rerank.margin_value:.2f})"
            )
            posting.status = "mapped"
            outcome_reason = MappingOutcomeReason.SEMANTIC_RERANK
        else:
            mapped = MappingMethod.SKILL_OVERLAP
            posting.catalog_job_id = overlap_job.id
            posting.mapping_method = MappingMethod.SKILL_OVERLAP.value
            posting.mapping_confidence = round(overlap_score, 3)
            posting.mapping_reason = (
                f"{len(skill_ids)} skills intersect; overlap {overlap_score:.2f} "
                f"(runner-up {runner_up or 0.0:.2f})"
            )
            posting.status = "mapped"
            outcome_reason = MappingOutcomeReason.SKILL_OVERLAP
    elif rerank.accepted and rerank.top_candidate is not None:
        top = rerank.top_candidate
        mapped = MappingMethod.SEMANTIC_RERANK
        posting.catalog_job_id = UUID(top.job_id)
        posting.mapping_method = MappingMethod.SEMANTIC_RERANK.value
        posting.mapping_confidence = round(top.blend, 3)
        posting.mapping_reason = (
            f"semantic rerank {top.blend:.2f} above {tau_job} "
            f"(deterministic {top.deterministic:.2f}, semantic {top.semantic:.2f}; "
            f"margin {rerank.margin_value:.2f})"
        )
        posting.status = "mapped"
        outcome_reason = MappingOutcomeReason.SEMANTIC_RERANK
    elif (
        semantic.cleared
        and semantic.top_candidate is not None
        and semantic.top_candidate.shared_skills >= semantic_min_shared
    ):
        rescue = semantic.top_candidate
        mapped = MappingMethod.SEMANTIC
        posting.catalog_job_id = UUID(rescue.job_id)
        posting.mapping_method = MappingMethod.SEMANTIC.value
        posting.mapping_confidence = round(rescue.score, 3)
        posting.mapping_reason = (
            f"semantic match {rescue.score:.2f} above {semantic_threshold} "
            f"(overlap {overlap_score if overlap_score is not None else 0:.2f} below "
            f"{tau_job}; {rescue.shared_skills} shared skill(s))"
        )
        posting.status = "mapped"
        outcome_reason = MappingOutcomeReason.SEMANTIC
    else:
        mapped = None
        posting.catalog_job_id = None
        posting.mapping_method = None
        posting.mapping_confidence = round(overlap_score, 3) if overlap_score is not None else None
        if semantic.top is not None:
            posting.mapping_reason = (
                f"best overlap {overlap_score if overlap_score is not None else 0:.2f} "
                f"below {tau_job}; semantic top {semantic.top:.2f} below "
                f"{semantic_threshold} — moderation"
            )
        else:
            posting.mapping_reason = (
                f"best overlap {overlap_score if overlap_score is not None else 0:.2f} "
                f"below {tau_job} — moderation"
            )
        posting.status = "new" if posting.status == "mapped" else posting.status
        if deferred:
            outcome_reason = MappingOutcomeReason.SEMANTIC_PENDING
        elif not candidates:
            outcome_reason = MappingOutcomeReason.NO_CANDIDATE
        elif semantic.degraded:
            outcome_reason = MappingOutcomeReason.SEMANTIC_UNAVAILABLE
        else:
            outcome_reason = MappingOutcomeReason.BELOW_THRESHOLD

    semantic_payload = semantic.as_dict()
    rerank_payload = rerank.as_dict()
    signals_payload: dict[str, Any] = {
        "overlap": {
            "score": round(overlap_score, 4) if overlap_score is not None else None,
            "runner_up": round(runner_up, 4) if runner_up is not None else None,
        },
        "semantic": semantic_payload,
        "rerank": rerank_payload,
    }
    if deferred:
        reasons = []
        if "rerank" in pending_stages:
            reasons.append("ambiguous deterministic outcome")
        if "rescue" in pending_stages:
            reasons.append("overlap below threshold")
        signals_payload["semantic_pending"] = True
        signals_payload["semantic_pending_reason"] = "; ".join(reasons)
    facts = {**(posting.posting_facts or {})}
    facts["mapping_signals"] = signals_payload
    posting.posting_facts = facts
    flag_modified(posting, "posting_facts")

    space_key = rerank.space_key or semantic.space_key
    degraded = rerank.degraded or semantic.degraded
    features = await build_mapping_features(
        db,
        candidates=candidates,
        rerank=rerank if rerank.ran else None,
        mapping_version=MAPPING_VERSION,
        tau_job=tau_job,
        delta=delta_margin,
        k=RERANK_CANDIDATE_K,
        blend_deterministic=RERANK_BLEND_DETERMINISTIC,
        blend_semantic=RERANK_BLEND_SEMANTIC,
        semantic_threshold=semantic_threshold,
        semantic_min_shared_skills=semantic_min_shared,
        space_key=space_key,
        degraded=degraded,
    )
    posting.mapping_features = features
    posting.mapping_version = MAPPING_VERSION
    write_mapping_outcome(
        posting,
        state=MappingOutcomeState.MAPPED if mapped is not None else MappingOutcomeState.UNMAPPED,
        reason=outcome_reason,
        confidence=posting.mapping_confidence,
        policy_hash=policy.hash,
    )

    actor_ref = {"run_id": str(run_id)} if run_id is not None else None
    PostingChangeJournal.record(
        db,
        posting.id,
        "retag",
        actor_ref=actor_ref,
        operation={
            "auto_map_threshold": tau_job,
            "mapping_version": MAPPING_VERSION,
            "policy_hash": policy.hash,
            "method": mapped.value if mapped is not None else None,
            "overlap_score": signals_payload["overlap"]["score"],
            "semantic_top": semantic_payload["top"],
            "rerank": rerank_payload,
            "space_key": space_key,
            "mapping_signals": signals_payload,
            "mapping_features": features,
        },
        before=before,
        after={**snapshot(posting, RETAG_FIELDS), "skills": await skills_state(db, posting.id)},
    )
    if deferred:
        # Same transaction as the decision: the caller's commit makes the
        # job durable, a rollback drops it with the posting write.
        await enqueue_semantic_redecision(db, posting.id, commit=False)
    return mapped


def _posting_skill_tokens(posting: JobPosting) -> list[str]:
    return [str(s) for s in (posting.raw or {}).get("_skills_raw", [])]


async def resolve_posting(db: AsyncSession, ref_or_id: str) -> JobPosting | None:
    """: everywhere accepts a short `ref` (Crockford base32) or the
    internal UUID; unknown values resolve to None (caller 404s)."""
    token = str(ref_or_id).strip()
    try:
        posting_id = UUID(token)
    except ValueError:
        rows = await db.execute(select(JobPosting).where(JobPosting.ref == token.upper()))
        return rows.scalars().first()
    rows = await db.execute(select(JobPosting).where(JobPosting.id == posting_id))
    return rows.scalars().first()


async def _ai_extract_skills(
    db: AsyncSession, posting: JobPosting, index: dict[str, UUID]
) -> dict[str, UUID]:
    from app.ai.agents.posting_mapper import extract_skill_keys

    known_keys = await _active_skill_keys(db)
    result = await extract_skill_keys(
        db,
        None,
        posting.title,
        str((posting.raw or {}).get("description") or ""),
        known_keys,
    )
    resolved: dict[str, UUID] = {}
    for key in result:
        skill_id = index.get(_norm(key))
        if skill_id is not None:
            resolved[key] = skill_id
    return resolved


async def _active_skill_keys(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(Skill.key).where(Skill.status == "active"))
    return list(rows.scalars().all())


async def _best_catalog_job(
    db: AsyncSession, posting_skill_ids: set[UUID]
) -> tuple[Job | None, float, float]:
    """Skill-ID intersection weighted by job_skills importance/level."""
    from app.services.postings.mapping_candidates import score_catalog_candidates

    candidates = await score_catalog_candidates(db, posting_skill_ids)
    if not candidates:
        return None, 0.0, 0.0
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    return candidates[0].job, candidates[0].score, runner_up


# --------------------------------------------------------------- user fit


async def posting_fit(db: AsyncSession, user_id: UUID, posting: JobPosting) -> float:
    """Mapped catalog fit + deterministic deltas — no per-posting AI."""
    from app.services.deps import get_profile_for_user

    if posting.catalog_job_id is None:
        return 0.0
    from app.services.catalog.job_service import JOB_LOAD_OPTIONS

    rows = await db.execute(
        select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == posting.catalog_job_id)
    )
    catalog_job = rows.scalars().unique().first()
    if catalog_job is None:
        return 0.0
    profile = await get_profile_for_user(db, user_id)
    from app.services.postings.fit.service import FitService

    fit_service = FitService(db)
    result = await fit_service.fit_for(profile, catalog_job)
    score = result.score

    now = _utcnow()
    posted = posting.posted_at or posting.created_at
    if posted:
        age_weeks = max(0.0, (now - posted).total_seconds() / (7 * 86400))
        score -= min(FRESH_DECAY_CAP, FRESH_DECAY_PER_WEEK * age_weeks)

    basics = profile.basics or {}
    prefs = profile.work_preferences or {}
    location = posting.location or {}
    if location.get("remote"):
        score += 0.5 if prefs.get("remote_ok", True) else -1.0
    elif (
        basics.get("city")
        and location.get("city")
        and basics["city"].strip().lower() != location["city"].strip().lower()
    ):
        score -= 0.5

    stage, _source = await _stage_for(db, user_id)
    seniority_ranks = {
        "intern": 0,
        "junior": 1,
        "mid": 2,
        "senior": 3,
        "lead": 4,
        "principal": 5,
    }
    posting_rank = seniority_ranks.get(posting.seniority or "")
    if posting_rank is not None:
        if stage.value == "student" and posting_rank >= 3:
            score -= 1.0
        if stage.value == "experienced" and posting_rank <= 1:
            score -= 0.5

    return round(max(0.0, min(10.0, score)), 2)


async def _stage_for(db: AsyncSession, user_id: UUID):
    from app.services.profile.stages_service import stage_for_user

    return await stage_for_user(db, user_id)


# ---------------------------------------------------------------- listings


async def list_postings(
    db: AsyncSession,
    user_id: UUID,
    *,
    source_id: UUID | None = None,
    remote: bool | None = None,
    seniority: str | None = None,
    catalog_job_id: UUID | None = None,
    saved: bool = False,
    sort: str = "fit",
    include_hidden: bool = False,
    company: str | None = None,
    no_company: str | None = None,
) -> dict:
    """Live tab: mapped-first listings with fit sort (unseen-first honored)."""
    from sqlalchemy.orm import selectinload

    from app.models.job_model import JobTag

    query = (
        select(JobPosting, PostingInteraction, Application)
        .options(
            selectinload(JobPosting.catalog_job).selectinload(Job.family),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.tag_links)
            .selectinload(JobTag.tag),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.skill_links)
            .selectinload(JobSkill.skill),
        )
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .outerjoin(
            Application,
            (Application.posting_id == JobPosting.id) & (Application.user_id == user_id),
        )
    )
    # Saved keeps postings that closed after they were saved (plan 140);
    # the open feed only lists live rows.
    if saved:
        query = query.where(JobPosting.status != "hidden")
    else:
        query = query.where(JobPosting.status.in_(["mapped", "new"]))
    if not include_hidden:
        query = query.where(
            or_(
                PostingInteraction.id.is_(None),
                PostingInteraction.hidden_at.is_(None),
            )
        )
    if source_id is not None:
        query = query.where(JobPosting.source_id == source_id)
    if remote is not None:
        query = query.where(JobPosting.location["remote"].as_boolean() == remote)
    if seniority:
        query = query.where(JobPosting.seniority == seniority)
    if catalog_job_id is not None:
        query = query.where(JobPosting.catalog_job_id == catalog_job_id)
    if company is not None:
        org_id = (
            await db.execute(select(Organization.id).where(Organization.key == company))
        ).scalar_one_or_none()
        if org_id is None:
            return {"items": [], "unseen": 0, "total": 0}
        query = query.where(JobPosting.org_id == org_id)
    if no_company is not None:
        query = query.where(JobPosting.org_id.is_(None), JobPosting.org_match_state == no_company)
    rows = (await db.execute(query.order_by(JobPosting.posted_at.desc()))).all()

    items: list[dict[str, Any]] = []
    unseen = 0
    for posting, interaction, application in rows:
        seen = interaction is not None and interaction.seen_at is not None
        if saved and (interaction is None or interaction.saved_at is None):
            continue
        if not seen:
            unseen += 1
        items.append(
            {
                "posting": posting,
                "interaction": interaction,
                "application": application,
                "seen": seen,
            }
        )

    if sort == "fresh":
        items.sort(key=lambda i: i["posting"].posted_at or _utcnow(), reverse=True)
    else:
        from app.services.postings.posting_fit_service import (
            FEED_FIT_WRITE_BUDGET,
            get_posting_fits_batch,
        )

        fits = await get_posting_fits_batch(
            db,
            user_id,
            [item["posting"] for item in items],
            write_budget=FEED_FIT_WRITE_BUDGET,
        )
        scores = {posting_id: entry["score"] for posting_id, entry in fits.items()}
        items.sort(
            key=lambda i: (
                0 if not i["seen"] else 1,
                -scores[i["posting"].id],
                i["posting"].title,
            )
        )
        for item in items:
            item["fit"] = scores[item["posting"].id]
    return {"items": items, "unseen": unseen, "total": len(items)}


# ------------------------------------------------------- skill-level search


async def postings_for_skill(
    db: AsyncSession,
    user_id: UUID,
    skill_id: UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """The skill page's positions list (plan 148): postings with a
    `posting_skills` row for this skill, excluding hidden — the saved
    view's visibility rule (expired/closed postings stay listable with
    their closed chip), newest first, bounded.

    Item dicts carry the same (posting, interaction, application) triples
    the feed/search projections consume, so the caller renders the exact
    `PostingOut` shape the cards already render.
    """
    from sqlalchemy.orm import selectinload

    from app.models.job_model import JobTag

    scope = (
        select(JobPosting.id)
        .join(PostingSkill, PostingSkill.posting_id == JobPosting.id)
        .where(PostingSkill.skill_id == skill_id, JobPosting.status != "hidden")
    )
    total = (await db.execute(select(func.count()).select_from(scope.subquery()))).scalar_one()
    query = (
        select(JobPosting, PostingInteraction, Application)
        .join(PostingSkill, PostingSkill.posting_id == JobPosting.id)
        .options(
            selectinload(JobPosting.catalog_job).selectinload(Job.family),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.tag_links)
            .selectinload(JobTag.tag),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.skill_links)
            .selectinload(JobSkill.skill),
        )
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .outerjoin(
            Application,
            (Application.posting_id == JobPosting.id) & (Application.user_id == user_id),
        )
        .where(PostingSkill.skill_id == skill_id, JobPosting.status != "hidden")
        .order_by(JobPosting.posted_at.desc(), JobPosting.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        {"posting": posting, "interaction": interaction, "application": application}
        for posting, interaction, application in (await db.execute(query)).all()
    ]
    return {"items": items, "total": total}


PRIORITY_WEIGHT = {"must_have": 3.0, "nice_to_have": 2.0, "bonus": 1.0}


def parse_skill_entries(raw: str) -> list[tuple[str, int | None]]:
    """`skills=sql:4,python:3` → [(key, level|None)]; validated at API."""
    entries: list[tuple[str, int | None]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, level = part.partition(":")
        key = key.strip()
        if not key:
            raise ValidationError(f"invalid skills filter segment: {part!r}")
        if sep:
            try:
                lvl = int(level)
            except ValueError as exc:
                raise ValidationError(f"invalid level for skill {key!r} (use 1-10)") from exc
            if not 1 <= lvl <= 10:
                raise ValidationError(f"level for {key!r} out of range 1-10")
            entries.append((key, lvl))
        else:
            entries.append((key, None))
    if not entries:
        raise ValidationError("skills filter is empty")
    return entries


async def search_postings(
    db: AsyncSession,
    user_id: UUID,
    *,
    entries: list[tuple[str, int | None]],
    mode: str = "all",
    priority: str | None = None,
    source_id: UUID | None = None,
    remote: bool | None = None,
    seniority: str | None = None,
    catalog_job_id: UUID | None = None,
    saved: bool = False,
    sort: str = "fresh",
    match_profile: bool = False,
    company: str | None = None,
    no_company: str | None = None,
) -> dict:
    """Skill+level search: `posting_skills` join on skill_id +
    required_level ≥ requested; all/any semantics; NULL-level rows are
    excluded from level-threshold matches (not yet deep-extracted)."""
    from sqlalchemy.orm import selectinload

    from app.models.job_model import Job, JobSkill, JobTag

    normalized: list[tuple[str, int | None]] = []
    for key, lvl in entries:
        normalized.append((_norm(key), lvl))
    skill_rows = await db.execute(select(Skill).where(Skill.key.in_([k for k, _ in normalized])))
    by_key = {skill.key: skill for skill in skill_rows.scalars().all()}
    unknown = [
        orig for (orig, _), (key, _) in zip(entries, normalized, strict=False) if key not in by_key
    ]
    if unknown:
        raise ValidationError(f"Unknown skills: {', '.join(sorted(set(unknown)))}")

    conditions = []
    for norm_key, lvl in normalized:
        skill = by_key.get(norm_key)
        if skill is None:
            continue
        cond = select(PostingSkill.id).where(
            PostingSkill.posting_id == JobPosting.id,
            PostingSkill.skill_id == skill.id,
        )
        if priority:
            cond = cond.where(PostingSkill.priority == priority)
        if lvl is not None:
            cond = cond.where(
                PostingSkill.required_level.is_not(None),
                PostingSkill.required_level >= lvl,
            )
        conditions.append(cond.exists())

    query = (
        select(JobPosting, PostingInteraction, Application)
        .options(
            selectinload(JobPosting.catalog_job).selectinload(Job.family),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.tag_links)
            .selectinload(JobTag.tag),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.skill_links)
            .selectinload(JobSkill.skill),
        )
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .outerjoin(
            Application,
            (Application.posting_id == JobPosting.id) & (Application.user_id == user_id),
        )
    )
    if saved:
        query = query.where(JobPosting.status != "hidden")
    else:
        query = query.where(JobPosting.status.in_(["mapped", "new"]))
    query = query.where(and_(*conditions)) if mode == "all" else query.where(or_(*conditions))
    if not saved:
        query = query.where(
            or_(
                PostingInteraction.id.is_(None),
                PostingInteraction.hidden_at.is_(None),
            )
        )
    if source_id is not None:
        query = query.where(JobPosting.source_id == source_id)
    if remote is not None:
        query = query.where(JobPosting.location["remote"].as_boolean() == remote)
    if seniority:
        query = query.where(JobPosting.seniority == seniority)
    if catalog_job_id is not None:
        query = query.where(JobPosting.catalog_job_id == catalog_job_id)
    if company is not None:
        org_id = (
            await db.execute(select(Organization.id).where(Organization.key == company))
        ).scalar_one_or_none()
        if org_id is None:
            return {"items": [], "unseen": 0, "total": 0}
        query = query.where(JobPosting.org_id == org_id)
    if no_company is not None:
        query = query.where(JobPosting.org_id.is_(None), JobPosting.org_match_state == no_company)
    rows = (await db.execute(query.order_by(JobPosting.posted_at.desc()))).all()

    items: list[dict[str, Any]] = []
    unseen = 0
    for posting, interaction, application in rows:
        seen = interaction is not None and interaction.seen_at is not None
        if saved and (interaction is None or interaction.saved_at is None):
            continue
        if not seen:
            unseen += 1
        items.append(
            {
                "posting": posting,
                "interaction": interaction,
                "application": application,
                "seen": seen,
            }
        )

    if match_profile:
        coverages = {}
        for item in items:
            coverages[item["posting"].id] = await profile_coverage(db, user_id, item["posting"])
        items.sort(
            key=lambda i: (
                0 if not i["seen"] else 1,
                -coverages[i["posting"].id],
                i["posting"].title,
            )
        )
        for item in items:
            item["coverage"] = coverages[item["posting"].id]
    elif sort == "fit":
        from app.services.postings.posting_fit_service import (
            FEED_FIT_WRITE_BUDGET,
            get_posting_fits_batch,
        )

        fits = await get_posting_fits_batch(
            db,
            user_id,
            [item["posting"] for item in items],
            write_budget=FEED_FIT_WRITE_BUDGET,
        )
        scores = {posting_id: entry["score"] for posting_id, entry in fits.items()}
        items.sort(
            key=lambda i: (
                0 if not i["seen"] else 1,
                -scores[i["posting"].id],
                i["posting"].title,
            )
        )
        for item in items:
            item["fit"] = scores[item["posting"].id]
    else:
        items.sort(key=lambda i: i["posting"].posted_at or _utcnow(), reverse=True)
    return {"items": items, "unseen": unseen, "total": len(items)}


async def profile_coverage(db: AsyncSession, user_id: UUID, posting: JobPosting) -> float:
    """Deterministic coverage of the user's skills over the posting's
    extracted requirements — the curve, no new semantics:
    per skill `min(user, required) / required`, priority-weighted, with
    fully-unmet must-have requirements capping the score at 4.0."""
    from app.models.user_model import UserSkill

    rows = await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id))
    links = [
        (link, required_level)
        for link in rows.scalars().all()
        if (required_level := link.required_level) is not None
    ]
    if not links:
        return 0.0
    level_rows = await db.execute(
        select(UserSkill.skill_id, UserSkill.level).where(
            UserSkill.user_id == user_id, UserSkill.derive_enabled
        )
    )
    user_levels: dict[UUID, int] = dict(level_rows.all())

    total_weight = 0.0
    covered = 0.0
    must_unmet = 0
    must_partial = 0
    for link, required_level in links:
        weight = PRIORITY_WEIGHT.get(link.priority or "", 1.0)
        total_weight += weight
        level = user_levels.get(link.skill_id)
        if level is None:
            if link.priority == PostingSkillPriority.MUST_HAVE.value:
                must_unmet += 1
            continue
        ratio = min(level, required_level) / max(1, required_level)
        covered += weight * ratio
        if link.priority == PostingSkillPriority.MUST_HAVE.value:
            if ratio <= 0:
                must_unmet += 1
            elif ratio < 1:
                must_partial += 1
    if total_weight <= 0:
        return 0.0
    score = 10.0 * covered / total_weight
    if must_unmet:
        score = min(score, 4.0)
    elif must_partial:
        score = min(score, 6.0)
    return round(score, 2)


async def _lazy_interaction(
    db: AsyncSession, user_id: UUID, posting_id: UUID
) -> PostingInteraction:
    rows = await db.execute(
        select(PostingInteraction).where(
            PostingInteraction.user_id == user_id,
            PostingInteraction.posting_id == posting_id,
        )
    )
    interaction = rows.scalars().first()
    if interaction is None:
        interaction = PostingInteraction(user_id=user_id, posting_id=posting_id)
        db.add(interaction)
        await db.flush()
    return interaction


async def mark_seen(db: AsyncSession, user_id: UUID, posting_ids: list[UUID]) -> int:
    marked = 0
    for posting_id in posting_ids:
        interaction = await _lazy_interaction(db, user_id, posting_id)
        if interaction.seen_at is None:
            interaction.seen_at = _utcnow()
            marked += 1
    await db.commit()
    return marked


async def set_state(
    db: AsyncSession,
    user_id: UUID,
    posting_id: UUID,
    *,
    field: str,
    value: datetime | None,
    extra: dict | None = None,
) -> PostingInteraction:
    rows = await db.execute(select(JobPosting).where(JobPosting.id == posting_id))
    if rows.scalars().first() is None:
        raise ValidationError("Posting not found")
    interaction = await _lazy_interaction(db, user_id, posting_id)
    setattr(interaction, field, value)
    if extra:
        for key, val in extra.items():
            setattr(interaction, key, val)
    await db.commit()
    await db.refresh(interaction)
    return interaction


# ------------------------------------------------------------------ alerts


async def check_new_posting_alerts(db: AsyncSession, posting: JobPosting) -> list[UUID]:
    """new_posting_match: mapped posting above a user's fit threshold —
    's rule table + dedup/cooldown machinery, new trigger.

    Returns the recipients — reuses the evaluation as the
    demand signal for extraction priority."""
    if posting.status != "mapped" or posting.catalog_job_id is None:
        return []
    from app.models.engagement_model import NotificationRule
    from app.services.notification_channels import within_quiet_hours
    from app.services.notification_service import NotificationService

    rules = (
        (
            await db.execute(
                select(NotificationRule).where(
                    NotificationRule.kind == NotificationRuleKind.NEW_POSTING_MATCH.value,
                    NotificationRule.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    recipients: list[UUID] = []
    for rule in rules:
        params = {
            "min_fit": 7.0,
            "max_per_day": 5,
            **(rule.params or {}),
        }
        if within_quiet_hours(params.get("quiet_hours")):
            continue
        fit = await posting_fit(db, rule.user_id, posting)
        if fit < float(params["min_fit"]):
            continue
        recipients.append(rule.user_id)
        await NotificationService(db).emit(
            NotificationRuleKind.NEW_POSTING_MATCH.value,
            [rule.user_id],
            title=f"New match: {posting.title}",
            body=f"{posting.org or 'A company'} posted a role mapping to your catalog — fit {fit:.1f}/10.",
            payload={
                "posting_id": str(posting.id),
                "job_id": str(posting.catalog_job_id),
                "url": posting.url,
                "score": fit,
                "link": "/postings",
            },
            dedup_key=f"posting-match:{rule.user_id}:{posting.id}",
            max_per_day=int(params["max_per_day"]),
        )
    return recipients


# ------------------------------------------------------- card skill strip

SKILL_REF_LIMIT = 40
SKILL_PRIORITY_RANK = {"must_have": 2, "nice_to_have": 1, "bonus": 0}


async def load_posting_skill_refs(
    db: AsyncSession, posting_ids: list[UUID]
) -> dict[UUID, list[PostingSkillRefOut]]:
    """Requirement-ordered skill refs for a page of postings, in ONE query.

    The order is the card's (plan 140): must-have → nice-to-have → bonus,
    then required level desc, then label — so the feed, the search rows and
    the detail page never disagree. Values are plain dicts; the wire schema
    coerces them.
    """
    from app.models.posting_model import PostingSkill

    ids = list(dict.fromkeys(posting_id for posting_id in posting_ids if posting_id))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            PostingSkill.posting_id,
            PostingSkill.required_level,
            PostingSkill.priority,
            Skill.key,
            Skill.label,
        )
        .join(Skill, Skill.id == PostingSkill.skill_id)
        .where(PostingSkill.posting_id.in_(ids))
    )
    grouped: dict[UUID, list[tuple]] = {}
    for posting_id, level, priority, key, label in rows.all():
        grouped.setdefault(posting_id, []).append((priority, level, key, label))
    out: dict[UUID, list[PostingSkillRefOut]] = {}
    for posting_id, entries in grouped.items():
        entries.sort(
            key=lambda entry: (
                -SKILL_PRIORITY_RANK.get(entry[0] or "", 0),
                -(entry[1] or 0),
                (entry[3] or "").lower(),
            )
        )
        out[posting_id] = [
            PostingSkillRefOut(
                key=key,
                label=label,
                required_level=level,
                priority=priority,
            )
            for priority, level, key, label in entries[:SKILL_REF_LIMIT]
        ]
    return out


# ------------------------------------------------------------------ expiry


async def expire_stale(db: AsyncSession, *, job_id=None) -> int:
    """expires_at passed or 45 days old → `expired` (journaled as
    `expiry` — the only writer that changes user-visible availability)."""
    from app.services.postings.change_journal import (
        EXPIRY_FIELDS,
        PostingChangeJournal,
        snapshot,
    )

    now = _utcnow()
    cutoff = now - timedelta(days=POSTING_MAX_AGE_DAYS)
    rows = await db.execute(
        select(JobPosting).where(
            JobPosting.status.in_(["new", "mapped"]),
            (JobPosting.expires_at.is_not(None) & (JobPosting.expires_at < now))
            | (JobPosting.posted_at.is_not(None) & (JobPosting.posted_at < cutoff)),
        )
    )
    actor_ref = {"job_id": str(job_id)} if job_id is not None else None
    expired = 0
    for posting in rows.scalars().all():
        before = snapshot(posting, EXPIRY_FIELDS)
        posting.status = "expired"
        PostingChangeJournal.record(
            db,
            posting.id,
            "expiry",
            actor_ref=actor_ref,
            operation={"max_age_days": POSTING_MAX_AGE_DAYS},
            before=before,
            after=snapshot(posting, EXPIRY_FIELDS),
        )
        expired += 1
    if expired:
        await db.commit()
    return expired


# ------------------------------------------------------------------- queue


async def run_sync_job(db: AsyncSession, payload: dict, *, job_id=None) -> dict:
    """POSTING_SYNC handler: one source or every enabled posting source.

    Paused sources (`paused_at`) and non-posting kinds (market demand
    sources run through their own handler) are skipped."""
    source_id = payload.get("source_id")
    if source_id:
        rows = await db.execute(select(JobSource).where(JobSource.id == UUID(source_id)))
        sources = [
            source
            for source in rows.scalars().all()
            if source.kind == "posting" and source.paused_at is None
        ]
    else:
        sources = list(
            (
                await db.execute(
                    select(JobSource).where(
                        JobSource.enabled.is_(True),
                        JobSource.kind == "posting",
                        JobSource.paused_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    totals: dict[str, Any] = {"synced": 0, "sources": len(sources), "errors": []}
    trigger = str(payload.get("trigger") or ("manual" if source_id else "scheduled"))
    for source in sources:
        result = await sync_source(db, source, trigger=trigger)
        totals["synced"] += result.get("synced", 0)
        if result.get("error"):
            totals["errors"].append(f"{source.key}: {result['error']}")
    await expire_stale(db, job_id=job_id)
    return totals
