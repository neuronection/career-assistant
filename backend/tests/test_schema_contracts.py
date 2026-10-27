"""Enum ↔ mirrored DB CHECK agreement wall (plan 113).

Every closed vocabulary that is mirrored into a database CHECK is
asserted here against the enum that owns it, on both dialects. A new
enum member without its CHECK widening (family-migration §5b) fails this
test instead of 500ing on the first insert.
"""

import asyncio
import re
from enum import StrEnum

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models.enums import (
    ApplicationActor,
    ApplicationEventKind,
    ApplicationOutcome,
    ApplicationStage,
    ApplicationVia,
    AutopilotRunStatus,
    ClaimAction,
    ClaimStatus,
    CoverageLevel,
    CrosswalkMethod,
    CvKind,
    CvPageSize,
    CvStatus,
    DeliveryStatus,
    EconPackKind,
    EconPackStatus,
    ExposureMethod,
    FeedTokenKind,
    GeoRegionKind,
    HealthStatus,
    InterviewKind,
    InterviewStatus,
    LabelEntityKind,
    LabelField,
    LabelSource,
    LabelStatus,
    LicenseClass,
    MisfirePolicy,
    NotificationChannel,
    NotificationRuleKind,
    NotificationStatus,
    PathFlag,
    PostingStatus,
    ProposalKind,
    ProposalSource,
    ProposalStatus,
    ProvenanceTier,
    ScenarioScope,
    ScenarioStatus,
    ScheduleKind,
    SearchScope,
    SkillRelationSource,
    SkillRelationStatus,
    SkillRelationType,
    SourceKind,
    WatchScopeKind,
    WebhookTarget,
)

SCHEDULE_TASKS = {
    "posting_sync",
    "digest",
    "saved_search_run",
    "radar_digest",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
    "followup_sweep",
    "market_history_capture",
    "proposal_sweep",
    "checkpoint_prune",
    "extension_reconcile",
    "demand_import",
}

CHECKS: list[tuple[str, str, StrEnum | set[str]]] = [
    ("applications", "stage_allowed", ApplicationStage),
    ("applications", "applied_via_allowed", ApplicationVia),
    ("applications", "outcome_allowed", ApplicationOutcome),
    ("application_events", "kind_allowed", ApplicationEventKind),
    ("application_events", "actor_allowed", ApplicationActor),
    ("job_sources", "kind_allowed", SourceKind),
    ("job_sources", "last_status_allowed", HealthStatus),
    ("webhook_endpoints", "target_allowed", WebhookTarget),
    ("webhook_endpoints", "last_status_allowed", HealthStatus),
    ("user_feed_tokens", "kind_allowed", FeedTokenKind),
    ("user_channel_configs", "channel_allowed", NotificationChannel),
    ("label_overrides", "entity_kind_allowed", LabelEntityKind),
    ("label_overrides", "field_allowed", LabelField),
    ("label_overrides", "source_allowed", LabelSource),
    ("label_overrides", "status_allowed", LabelStatus),
    ("user_path_flags", "flag_allowed", PathFlag),
    ("profile_proposals", "source_allowed", ProposalSource),
    ("profile_proposals", "kind_allowed", ProposalKind),
    ("profile_proposals", "status_allowed", ProposalStatus),
    ("notification_deliveries", "channel_allowed", NotificationChannel),
    ("notification_deliveries", "status_allowed", DeliveryStatus),
    ("notification_recipients", "status_allowed", NotificationStatus),
    ("notification_rules", "kind_supported", NotificationRuleKind),
    ("search_history", "scope_allowed", SearchScope),
    ("job_postings", "status_allowed", PostingStatus),
    ("interview_sessions", "kind_allowed", InterviewKind),
    ("interview_sessions", "status_allowed", InterviewStatus),
    ("autopilot_runs", "status_allowed", AutopilotRunStatus),
    ("cv_documents", "kind_allowed", CvKind),
    ("cv_documents", "status_allowed", CvStatus),
    ("cv_documents", "page_size_allowed", CvPageSize),
    ("schedules", "kind_allowed", ScheduleKind),
    ("schedules", "task_allowed", SCHEDULE_TASKS),
    ("schedules", "misfire_allowed", MisfirePolicy),
    ("skill_relations", "relation_allowed", SkillRelationType),
    ("skill_relations", "status_allowed", SkillRelationStatus),
    ("skill_relations", "source_allowed", SkillRelationSource),
    ("geo_regions", "kind_allowed", GeoRegionKind),
    ("econ_packs", "kind_allowed", EconPackKind),
    ("econ_packs", "status_allowed", EconPackStatus),
    ("econ_packs", "license_class_allowed", LicenseClass),
    ("econ_series", "coverage_level_allowed", CoverageLevel),
    ("econ_series", "license_class_allowed", LicenseClass),
    ("econ_observations", "provenance_tier_allowed", ProvenanceTier),
    ("code_crosswalks", "method_allowed", CrosswalkMethod),
    ("exposure_scores", "method_allowed", ExposureMethod),
    ("exposure_scores", "license_class_allowed", LicenseClass),
    ("scenarios", "scope_kind_allowed", ScenarioScope),
    ("scenarios", "status_allowed", ScenarioStatus),
    ("claims", "status_allowed", ClaimStatus),
    ("claim_events", "action_allowed", ClaimAction),
    ("econ_watchlist", "scope_kind_allowed", WatchScopeKind),
]


def _check_expressions(table: str) -> dict[str, str]:
    async def run() -> dict[str, str]:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                rows = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_check_constraints(table)
                )
            return {_short_name(table, str(row["name"])): str(row["sqltext"] or "") for row in rows}
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _short_name(table: str, name: str) -> str:
    prefix = f"ck_{table}_"
    return name[len(prefix) :] if name.startswith(prefix) else name


def _expected(spec: StrEnum | set[str]) -> set[str]:
    if isinstance(spec, set):
        return set(spec)
    return {member.value for member in spec}


def _values(expression: str) -> set[str]:
    return set(re.findall(r"'([^']*)'", expression))


def test_every_mirrored_check_matches_its_enum():
    failures: list[str] = []
    for table, constraint, spec in CHECKS:
        expressions = _check_expressions(table)
        assert constraint in expressions, f"{table} is missing CHECK {constraint}"
        expected = _expected(spec)
        actual = _values(expressions[constraint])
        if actual != expected:
            failures.append(
                f"{table}.{constraint}: enum has {sorted(expected)}, CHECK has {sorted(actual)}"
            )
    assert not failures, "enum ↔ CHECK drift:\n" + "\n".join(failures)


def test_posting_fit_default_tracks_the_engine_version():
    from app.models.posting_model import current_fit_version
    from app.services.postings.fit.dimensions import FIT_VERSION

    assert current_fit_version() == FIT_VERSION
