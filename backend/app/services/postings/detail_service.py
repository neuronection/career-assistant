"""Detail enrichment (the smart-fetch funnel): decide app-side which
postings deserve their job-description page, then fetch it in paced,
budgeted batches through the connector's ``detail_ids`` contract.

``config.detail_mode``: ``off`` · ``sample`` (inline during sync — the
connector's own newest-N) · ``smart`` · ``all``. smart/all run this
pipeline: deterministic Layer 1 ranking (radar match + recency + salary)
always; the optional LLM re-rank happens only here in the background job
and falls back to Layer 1's order when AI is unconfigured. The connector
stays a pure normalizer — it fetches exactly the ids it is given."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.enums import BackgroundJobType
from app.models.posting_model import JobPosting, JobSource

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BATCH = 10
TRIAGE_WINDOW = 40
MAX_BATCHES_PER_RUN = 5

_DETAIL_FIELDS = ("seniority", "employment_type", "contract_type", "onsite_policy")


def detail_limit(source: JobSource) -> int:
    """How many detail pages one enrichment run may fetch — the source's
    ``detail_limit`` knob (the same "Detail-page budget" field that caps
    sample mode), read from the options layer like the mode."""
    config = source.config or {}
    options = config.get("options")
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except ValueError:
            options = {}
    try:
        limit = int(config.get("detail_limit") or (options or {}).get("detail_limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    return max(1, min(10, limit))


def detail_mode(source: JobSource) -> str:
    """The source's enrichment mode (never trusts free text).

    Managed-spawn sources keep the bundle knobs in ``config.options``
    (a JSON-encoded string — the mcp passthrough layer), so the mode is
    read from there as well as the top level."""
    config = source.config or {}
    options = config.get("options")
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except ValueError:
            options = {}
    mode = str(config.get("detail_mode") or (options or {}).get("detail_mode") or "all")
    return mode if mode in ("off", "sample", "smart", "all") else "all"


async def _radar_terms(db: AsyncSession) -> tuple[set[str], object | None]:
    """Merged keyword terms + the first enabled radar (Layer-1 backdrop)."""
    from app.services.postings.radar_service import list_enabled_radars

    radars = await list_enabled_radars(db)
    terms: set[str] = set()
    for radar in radars:
        for term in radar.keywords or []:
            text = str(term).strip().lower()
            if text:
                terms.add(text)
    return terms, (radars[0] if radars else None)


def score_candidate(posting: JobPosting, terms: set[str], radar) -> float:
    """Deterministic Layer 1: worth-a-detail-page score in 0..1.

    Radar keyword match is the backbone; seniority/onsite agreement, a
    stated (and radar-meeting) salary and recency break ties. `all`
    mode reuses this as the fetch order — better first."""
    score = 0.0
    text = f"{posting.title} {posting.org}".lower()
    if terms:
        hits = sum(1 for term in terms if term in text)
        score += 0.6 * (hits / len(terms))
    if radar is not None:
        if posting.seniority and posting.seniority in (radar.seniority or []):
            score += 0.15
        if (
            posting.onsite_policy
            and radar.onsite_policy
            and posting.onsite_policy == radar.onsite_policy
        ):
            score += 0.1
        if posting.salary_normalized_min is not None or posting.salary_min is not None:
            score += 0.1
            floor = getattr(radar, "salary_min_annual", None)
            if (
                floor
                and posting.salary_normalized_min is not None
                and posting.salary_normalized_min >= floor
            ):
                score += 0.05
    if posting.posted_at is not None:
        age_days = (datetime.now(UTC) - posting.posted_at).total_seconds() / 86400
        score += 0.15 * max(0.0, 1.0 - min(max(age_days, 0.0), 30.0) / 30.0)
    return round(score, 4)


async def plan_details(
    db: AsyncSession, source: JobSource, limit: int | None = None
) -> list[JobPosting]:
    """One enrichment batch: the queue head, ranked. The queue is the
    postings still missing their description — retried across runs, with
    a give-up cutoff at MAX_ATTEMPTS. The batch size is the source's
    ``detail_limit`` knob unless overridden."""
    rows = await db.execute(
        select(JobPosting)
        .where(
            JobPosting.source_id == source.id,
            JobPosting.detail_fetched_at.is_(None),
            JobPosting.detail_attempts < MAX_ATTEMPTS,
            JobPosting.status.in_(("new", "mapped")),
        )
        .order_by(JobPosting.posted_at.desc().nullslast())
        .limit(TRIAGE_WINDOW)
    )
    candidates = list(rows.scalars().all())
    if not candidates:
        return []
    if limit is None:
        limit = detail_limit(source)
    terms, radar = await _radar_terms(db)
    ranked = sorted(candidates, key=lambda p: score_candidate(p, terms, radar), reverse=True)

    try:
        from app.ai.agents.detail_triage import triage_candidates

        picks = await triage_candidates(
            db,
            None,
            [
                {
                    "external_id": p.external_id,
                    "title": p.title,
                    "org": p.org,
                    "seniority": p.seniority,
                    "salary": (
                        f"{p.salary_normalized_min or p.salary_min}"
                        if p.salary_min is not None or p.salary_normalized_min is not None
                        else ""
                    ),
                }
                for p in ranked
            ],
        )
    except Exception:
        picks = None
    if picks:
        ranked.sort(
            key=lambda p: (picks.get(p.external_id, 0.0), score_candidate(p, terms, radar)),
            reverse=True,
        )
    return ranked[:limit]


def merge_detail(
    posting: JobPosting,
    row,
    *,
    actor_ref: dict | None = None,
    operation: dict | None = None,
) -> bool:
    """Fold one detail row into its posting. Only fields the detail page
    actually states are merged — list-derived fields are never wiped;
    typed fields fill gaps (the detail page wins when the list said
    nothing). Returns True when anything changed; the change journals as
    `detail_fetch` in the caller's transaction."""
    from app.services.postings.change_journal import (
        DETAIL_FIELDS,
        PostingChangeJournal,
        raw_summary,
        snapshot,
    )

    before = {**snapshot(posting, DETAIL_FIELDS), "raw_summary": raw_summary(posting)}
    detail = dict(row.raw or {})
    changed = False
    if detail.get("description"):
        merged = dict(posting.raw or {})
        merged["description"] = detail["description"]
        posting.raw = merged
        flag_modified(posting, "raw")
        changed = True
    # The detail rung's provenance rides along (which extractor produced the
    # description: jsonld / dom_fallback / two_pane …) — observability, never
    # a data field.
    provenance = {
        key: detail[key] for key in ("detail_extractor", "source_page") if detail.get(key)
    }
    if provenance:
        merged = dict(posting.raw or {})
        if any(merged.get(k) != v for k, v in provenance.items()):
            merged.update(provenance)
            posting.raw = merged
            flag_modified(posting, "raw")
            changed = True
    for attr in _DETAIL_FIELDS:
        value = getattr(row, attr, None)
        if value is not None and getattr(posting, attr) is None:
            setattr(posting, attr, value)
            changed = True
    if row.salary is not None and posting.salary_min is None and posting.salary_max is None:
        posting.salary_currency = row.salary.currency
        posting.salary_min = row.salary.min
        posting.salary_max = row.salary.max
        posting.salary_period = row.salary.period
        posting.salary_basis = row.salary.basis
        changed = True
    if changed:
        from sqlalchemy.orm import object_session

        session = object_session(posting)
        if session is not None:
            PostingChangeJournal.record(
                session,
                posting.id,
                "detail_fetch",
                actor_ref=actor_ref,
                operation=operation,
                before=before,
                after={**snapshot(posting, DETAIL_FIELDS), "raw_summary": raw_summary(posting)},
            )
    return changed


async def _fetch_details(db: AsyncSession, source: JobSource, ids: list[str]):
    """One targeted connector call: (rows, partial errors, error, run_summary)."""
    from app.extensions import registry
    from app.extensions.runtime.http import build_transport

    try:
        connector = await registry.resolve_connector(db, source.connector_key)
    except Exception as exc:
        return [], [], str(exc), None
    from app.extensions.runtime.sandbox.connector import SandboxConnector
    from app.services.postings.postings_service import resolve_source_secrets

    secrets = resolve_source_secrets(source)
    transport = build_transport(
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
    call_config = {
        **dict(source.config or {}),
        "detail_mode": "off",
        "detail_ids": ",".join(ids),
        "detail_limit": len(ids),
    }
    try:
        result = await connector.fetch(
            call_config, {}, transport=transport, secrets=secrets, audit=audit
        )
    except Exception as exc:
        return [], [], str(exc), None
    return (
        list(result.items),
        [entry.model_dump(mode="json") for entry in result.partial_errors],
        None,
        result.run_summary,
    )


async def run_detail_enrichment(
    db: AsyncSession, payload: dict, user_id=None, *, job_id=None
) -> dict:
    """DETAIL_ENRICHMENT handler: drain batches under a per-run cap.
    Never raises — a failing batch is a report line, not a crashed job."""
    from app.services.postings.change_journal import PostingChangeJournal, snapshot
    from app.services.postings.postings_service import (
        _begin_run,
        _finish_run,
        _update_run_progress,
    )

    source = (
        (await db.execute(select(JobSource).where(JobSource.id == payload.get("source_id"))))
        .scalars()
        .first()
    )
    if source is None:
        return {"skipped": "source gone"}
    if detail_mode(source) not in ("smart", "all"):
        return {"skipped": "detail mode is not smart/all"}
    started = datetime.now(UTC)
    run_row = await _begin_run(db, source, trigger="scheduled", started=started, stage="enriching")
    actor_ref: dict = {}
    if run_row is not None:
        actor_ref["run_id"] = str(run_row.id)
    if job_id is not None:
        actor_ref["job_id"] = str(job_id)
    enriched = 0
    fetched = 0
    re_extract: list[JobPosting] = []
    errors: list[dict] = []
    summaries: list[dict] = []
    # Drain the backlog: up to MAX_BATCHES_PER_RUN knob-sized batches per
    # enrichment run (the queue also drains across syncs — each sync
    # enqueues the next run).
    for batch_no in range(1, MAX_BATCHES_PER_RUN + 1):
        batch = await plan_details(db, source, limit=detail_limit(source))
        if not batch:
            break
        ids = [posting.external_id for posting in batch]
        rows, partials, error, run_summary = await _fetch_details(db, source, ids)
        fetched += len(rows)
        errors.extend(partials)
        if run_summary is not None:
            summaries.append(run_summary)
        if error:
            errors.append({"code": "io", "detail": error[:500], "retryable": "yes"})
        by_id = {row.external_id: row for row in rows}
        for posting in batch:
            row = by_id.get(posting.external_id)
            posting.detail_attempts += 1
            if row is not None and merge_detail(
                posting, row, actor_ref=actor_ref or None, operation={"source": source.key}
            ):
                before = snapshot(posting, ("detail_fetched_at", "extract_version"))
                posting.detail_fetched_at = datetime.now(UTC)
                # The description materially changed — the earlier extract
                # (made from list-card data) is stale. Reset it so the
                # deep pass re-runs on the full text.
                posting.extract = None
                posting.extract_version = None
                re_extract.append(posting)
                enriched += 1
                PostingChangeJournal.record(
                    db,
                    posting.id,
                    "detail_fetch",
                    actor_ref=actor_ref or None,
                    operation={"source": source.key, "batch": batch_no},
                    before=before,
                    after=snapshot(posting, ("detail_fetched_at", "extract_version")),
                )
        await db.commit()
        if run_row is not None:
            await _update_run_progress(
                db,
                run_row.id,
                stage="enriching",
                batch=batch_no,
                enriched=enriched,
                detail_rows=fetched,
            )
        if error or not rows:
            break
    if re_extract:
        from app.services.postings.extract_service import plan_extractions

        await plan_extractions(db, [(posting, False) for posting in re_extract])
    report = {
        "enriched": enriched,
        "detail_rows": fetched,
        "extract_requeued": len(re_extract),
        "errors": errors[:20],
        "batches": len(summaries),
    }
    if summaries:
        report["run_summary"] = summaries[-1]
    if run_row is not None:
        await _finish_run(db, run_row.id, started=started, report=report)
    return report


async def enqueue_details(db: AsyncSession, source: JobSource) -> int:
    """Post-sync hook: smart/all sources queue one enrichment job per
    sync (the job drains batches). Returns 1 when queued."""
    if detail_mode(source) not in ("smart", "all"):
        return 0
    from app.services.job_worker import enqueue

    await enqueue(
        db,
        BackgroundJobType.DETAIL_ENRICHMENT.value,
        {"source_id": str(source.id)},
    )
    return 1
