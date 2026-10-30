"""Admin surface: catalog moderation and AI audit viewer.

User management (`/admin/users`, reset-password, force-logout) is the
auth-kit's §12 surface now — see `nx_auth.user_admin` (plan 16 P3a)."""

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.errors import DomainError, ValidationError, sanitize_error_detail
from app.models.enums import BackgroundJobType
from app.models.user_model import User
from app.schemas.company import CompanyDetailOut, CompanyProfileIn
from app.schemas.i18n import (
    LocaleIn,
    LocaleStateOut,
    OverlayDraftIn,
    OverlayDraftResultOut,
    OverlayOut,
    OverlayPatchIn,
    OverlayStatusOut,
    TranslateKeysIn,
)
from app.schemas.job import JobOut
from app.schemas.scheduler import (
    ScheduleItemOut,
    ScheduleRunNowOut,
    ScheduleToggleOut,
)
from app.schemas.taxonomy import SkillBulkIn, SkillBulkOut
from app.services.catalog.job_service import JobService
from app.services.catalog.taxonomy_service import TaxonomyService
from app.services.deps import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class BulkJobActionIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)
    action: str  # "publish" | "reject"


@router.get("/jobs", response_model=list[JobOut])
async def moderation_queue(
    job_status: str = Query(default="draft", alias="status"),
    source: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[JobOut]:
    """All users' catalog drafts (default), newest last, for moderation."""
    jobs, _ = await JobService(db).list_jobs(status=job_status, source=source, page_size=limit)
    return [JobOut.from_model(j) for j in jobs]


@router.post("/jobs/bulk")
async def bulk_job_action(
    body: BulkJobActionIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish or reject (delete) catalog drafts in bulk (admin transcends ownership)."""
    if body.action not in ("publish", "reject"):
        raise ValidationError("action must be 'publish' or 'reject'")
    service = JobService(db)
    published, rejected = 0, 0
    for job_id in body.ids:
        job = await service.get_by_code_or_id(job_id)
        if job is None:
            continue
        if body.action == "publish":
            job.status = "published"
            published += 1
            await service._refit_job(job.id)
        else:
            # relations cascade via FK; ownership rules don't bind admins here
            await db.delete(job)
            rejected += 1
    await db.commit()
    return {"published": published, "rejected": rejected}


@router.get("/skills/proposals")
async def skill_proposals(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Proposed skills awaiting promotion (auto-created on unknown keys)."""
    from app.schemas.taxonomy import SkillOut

    rows = await TaxonomyService(db).proposals()
    return [SkillOut.model_validate(r).model_dump(mode="json") for r in rows]


@router.post("/skills/{skill_id}/promote")
async def promote_skill(
    skill_id: uuid.UUID,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """proposed → active; the vocabulary stays clean via admin review."""
    from app.schemas.taxonomy import SkillOut

    try:
        skill = await TaxonomyService(db).promote(skill_id, actor_ref={"user_id": str(admin.id)})
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SkillOut.model_validate(skill).model_dump(mode="json")


@router.post("/skills/{skill_id}/merge")
async def merge_skill(
    skill_id: uuid.UUID,
    body: dict,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Merge a duplicate into `target_id` (aliases redirect, joins rewritten)."""
    from app.schemas.taxonomy import SkillOut

    target_id = body.get("target_id")
    if not target_id:
        raise ValidationError("target_id is required")
    try:
        skill = await TaxonomyService(db).merge(
            skill_id,
            uuid.UUID(str(target_id)),
            actor_ref={"user_id": str(admin.id)},
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "target_id must be a UUID") from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SkillOut.model_validate(skill).model_dump(mode="json")


@router.post("/skills/bulk", response_model=SkillBulkOut)
async def bulk_skill_action(
    body: SkillBulkIn,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SkillBulkOut:
    """One lifecycle action over many skills (promote/deprecate/restore/
    delete, or many-to-one merge into `target_id`).

    Best-effort with a per-item report: ids the seams refuse (wrong status,
    still referenced, unknown) come back as failure rows, never a 4xx.
    """
    result = await TaxonomyService(db).bulk_skills(
        body.ids, body.action, body.target_id, actor_ref={"user_id": str(admin.id)}
    )
    return SkillBulkOut.model_validate(result)


@router.get("/paths")
async def path_moderation_queue(
    path_status: str = Query(default="draft", alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """All paths by status (default: AI drafts awaiting review)."""
    from app.models.career_path_model import CareerPath
    from app.services.catalog.paths_service import PathService

    rows = (
        (
            await db.execute(
                select(CareerPath)
                .options(selectinload(CareerPath.job))
                .where(CareerPath.status == path_status)
                .order_by(CareerPath.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    service = PathService(db)
    out = []
    for path in rows:
        payload = service._path_out(path).model_dump(mode="json")
        payload["job_code"] = path.job.code if path.job else None
        payload["job_title"] = path.job.title if path.job else None
        out.append(payload)
    return out


@router.post("/paths/{path_id}/publish")
async def publish_path(
    path_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish a drafted path."""
    from app.services.catalog.paths_service import PathService

    try:
        path = await PathService(db).publish(path_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(path.id), "status": path.status}


@router.post("/paths/{path_id}/reject")
async def reject_path(
    path_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a draft (published paths are withdrawn to draft instead)."""
    from app.services.catalog.paths_service import PathService

    try:
        await PathService(db).reject(path_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(path_id), "status": "rejected"}


@router.get("/postings/connectors", response_model=list[dict])
async def posting_connectors(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Registered connector engines (built-ins + allowlisted plugins)."""
    from app.extensions.registry import list_connectors

    return list_connectors()


@router.get("/postings/connectors/{key}/documentation", response_model=dict)
async def posting_connector_documentation(
    key: str,
    file: str | None = None,
    locale: str | None = None,
) -> dict:
    """The per-extension documentation surface (plan 34 wave 8 — the
    extensionDocsTree form): tree + markdown, opening on the landing
    page (§10.4). Only registry-known connectors serve; the requested
    file must be a docs-tree-listed page (basename-checked, resolved
    inside the bundle's docs/ dir); raw HTML is neutralized fence-aware
    (§10.7). The optional ``locale`` rides the §10.9 page-locale
    convention: a noted ``<page>.<locale>.md`` sibling is served when
    it exists, else the default page — ``served_file``/``served_locale``
    state what was actually served (honest fallback). Connectors
    without a tree answer with an honest absence page — the catalog's
    manifest pointer drives the affordance."""
    import os

    from app.extensions import docs as ext_docs
    from app.extensions.registry import get_connector
    from app.extensions.sdk import manifest_path

    try:
        connector = get_connector(key)
    except ValidationError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found") from None

    docs_dir = manifest_path(connector).parent / "docs"
    tree = ext_docs.load_tree(docs_dir)
    if tree is None:
        return {
            "markdown": (f"# {connector.title}\n\nNo documentation provided for this connector."),
            "tree": None,
        }

    served_file, served_locale = ext_docs.resolve_page(docs_dir, tree, file, locale)
    markdown_content = ""
    if served_file:
        target_file = os.path.basename(served_file)
        target_file_path = docs_dir / target_file
        if target_file_path.is_file():
            markdown_content = ext_docs.strip_raw_html(target_file_path.read_text(encoding="utf-8"))
        else:
            markdown_content = f"# Error\n\nCould not find file {target_file} in docs folder."
    return {
        "markdown": markdown_content,
        "tree": tree,
        "served_file": served_file,
        "served_locale": served_locale,
    }


@router.get("/postings/feature-map", response_model=dict)
async def posting_feature_map() -> dict:
    """The extraction feature map (39.3): feature → consumers, declared
    once; the AI extraction prompt is generated from these rows."""
    from app.services.feature_map import CONSUMERS, FEATURE_MAP, unmapped_features

    return {
        "consumers": CONSUMERS,
        "features": [
            {
                "key": row.key,
                "label": row.label,
                "consumers": list(row.consumers),
                "in_prompt": row.extracts,
                "inert": row.inert,
            }
            for row in FEATURE_MAP.values()
        ],
        "unmapped": unmapped_features(),
    }


@router.get("/organizations", response_model=list[dict])
async def admin_organizations(
    status: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Organizations with live posting counts (matcher review surface)."""
    from app.services.catalog.organization_service import OrganizationService

    return await OrganizationService(db).list_orgs(status=status, q=q)


@router.post("/organizations/{org_id}/promote", response_model=dict)
async def promote_organization(org_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """proposed → active (the only promotion path, like skills)."""
    from app.services.catalog.organization_service import OrganizationService

    try:
        org = await OrganizationService(db).promote(org_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"id": str(org.id), "status": org.status}


@router.post("/organizations/{org_id}/aliases", response_model=dict)
async def add_organization_alias(
    org_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Register another label that resolves to this organization."""
    from app.services.catalog.organization_service import OrganizationService

    try:
        service = OrganizationService(db)
        org = await service.add_alias(org_id, str(payload.get("alias") or ""))
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"id": str(org.id), "aliases": await service.org_aliases(org_id)}


@router.get("/organizations/{org_id}/aliases", response_model=list[dict])
async def list_organization_aliases(
    org_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Alias rows with provenance and state (the rules surface)."""
    from app.services.catalog.organization_service import OrganizationService

    return await OrganizationService(db).alias_rows(org_id)


@router.delete("/organizations/{org_id}/aliases/{alias_id}", response_model=dict)
async def delete_organization_alias(
    org_id: uuid.UUID, alias_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    from app.services.catalog.organization_service import OrganizationService

    try:
        await OrganizationService(db).remove_alias(org_id, alias_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"deleted": str(alias_id)}


@router.post("/organizations/{org_id}/aliases/{alias_id}/state", response_model=dict)
async def set_organization_alias_state(
    org_id: uuid.UUID,
    alias_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Activate or exclude one alias (excluded rows are kept as history)."""
    from app.services.catalog.organization_service import OrganizationService

    try:
        row = await OrganizationService(db).set_alias_state(
            org_id, alias_id, str(payload.get("state") or "")
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"id": str(row.id), "state": row.state}


@router.get("/organizations/exclusions", response_model=list[dict])
async def list_organization_exclusions(
    kind: str | None = Query(default=None, pattern="^(global|pair)$"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Global not-a-company labels and per-org never-link pairs."""
    from app.services.catalog.organization_service import OrganizationService

    return await OrganizationService(db).list_exclusions(kind=kind)


@router.post("/organizations/exclusions", response_model=dict)
async def create_organization_exclusion(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    from app.services.catalog.organization_service import OrganizationService

    org_id = payload.get("org_id")
    try:
        return await OrganizationService(db).create_exclusion(
            str(payload.get("label") or ""),
            org_id=uuid.UUID(str(org_id)) if org_id else None,
            reason=str(payload.get("reason") or ""),
            created_by=str(payload.get("created_by") or "admin")[:120],
        )
    except (ValueError, DomainError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.delete("/organizations/exclusions/{exclusion_id}", response_model=dict)
async def delete_organization_exclusion(
    exclusion_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    from app.services.catalog.organization_service import OrganizationService

    try:
        await OrganizationService(db).delete_exclusion(exclusion_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"deleted": str(exclusion_id)}


@router.get("/organizations/thresholds", response_model=dict)
async def get_organization_thresholds(db: AsyncSession = Depends(get_db)) -> dict:
    from app.services.catalog.organization_service import OrganizationService

    return await OrganizationService(db).get_thresholds()


@router.put("/organizations/thresholds", response_model=dict)
async def set_organization_thresholds(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    from app.services.catalog.organization_service import OrganizationService

    try:
        return await OrganizationService(db).set_thresholds(payload)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/organizations/{org_id}/merge", response_model=dict)
async def merge_organization(
    org_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """Re-point all references to the target; the duplicate is deprecated."""
    from app.services.catalog.organization_service import OrganizationService

    try:
        service = OrganizationService(db)
        target_id = uuid.UUID(str(payload.get("target_id")))
        org = await service.merge(org_id, target_id, actor_user_id=user.id)
    except (ValueError, DomainError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "id": str(org.id),
        "status": org.status,
        "aliases": await service.org_aliases(org.id),
    }


@router.post("/organizations/backfill", response_model=dict)
async def backfill_organizations(db: AsyncSession = Depends(get_db)) -> dict:
    """Run the current matcher over unjudged postings + experience items."""
    from app.services.catalog.company_triage_service import enqueue_company_triage
    from app.services.catalog.organization_service import OrganizationService

    service = OrganizationService(db)
    postings = await service.backfill_postings()
    experience = await service.backfill_experience_items()
    triage_queued = await enqueue_company_triage(db)
    return {
        "postings": postings,
        "experience": experience,
        "company_triage_queued": int(triage_queued),
    }


@router.get("/organizations/pairs", response_model=list[dict])
async def list_organization_pairs(
    status: str | None = "pending",
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Gray-band queue (the arbiter's pending pairs, matcher review)."""
    from app.services.catalog.company_triage_service import CompanyTriageService

    return await CompanyTriageService(db).list_pairs(status=status)


@router.get("/organizations/suggestions", response_model=list[dict])
async def list_organization_suggestions(
    status: str | None = "open",
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Merge suggestions with their evidence (accept merges, dismiss excludes)."""
    from app.services.catalog.company_triage_service import CompanyTriageService

    return await CompanyTriageService(db).list_suggestions(status=status)


@router.post("/organizations/suggestions/{suggestion_id}/accept", response_model=dict)
async def accept_organization_suggestion(
    suggestion_id: uuid.UUID,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept a suggestion: merge the label's org into the established one."""
    from app.services.catalog.company_triage_service import CompanyTriageService

    decided_by = str((payload or {}).get("decided_by") or "admin")[:120]
    try:
        org = await CompanyTriageService(db).accept_suggestion(suggestion_id, decided_by=decided_by)
    except (ValueError, DomainError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"id": str(org.id), "status": org.status}


@router.post("/organizations/suggestions/{suggestion_id}/dismiss", response_model=dict)
async def dismiss_organization_suggestion(
    suggestion_id: uuid.UUID,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dismiss a suggestion: different employers; the pair exclusion is written."""
    from app.services.catalog.company_triage_service import CompanyTriageService

    decided_by = str((payload or {}).get("decided_by") or "admin")[:120]
    try:
        suggestion = await CompanyTriageService(db).dismiss_suggestion(
            suggestion_id, decided_by=decided_by
        )
    except (ValueError, DomainError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"id": str(suggestion.id), "status": suggestion.status}


@router.put("/companies/{key}", response_model=CompanyDetailOut)
async def upsert_company_profile(
    key: str,
    data: CompanyProfileIn,
    db: AsyncSession = Depends(get_db),
) -> CompanyDetailOut:
    """Write the reviewed company facts (omit a field = clear to unknown)."""
    from app.services.catalog.company_service import CompanyService

    try:
        return await CompanyService(db).upsert_profile(key, data)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/jobs/enrichment", response_model=list[dict])
async def enrichment_queue(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Catalog v2-enrichment proposals awaiting moderation."""
    from app.services.catalog.catalog_enrich_service import CatalogEnrichService

    return [
        {
            "id": str(job.id),
            "code": job.code,
            "title": job.title,
            "proposal": (job.ai_metadata or {}).get("enrichment_proposal"),
            "proposed_at": (job.ai_metadata or {}).get("enrichment_proposed_at"),
        }
        for job in await CatalogEnrichService(db).pending()
    ]


@router.post("/jobs/{job_id}/enrichment/apply", response_model=dict)
async def apply_enrichment(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Merge the proposal's v2 fields into the curated attributes."""
    from app.core.errors import NotFoundError
    from app.models.job_model import Job
    from app.services.catalog.catalog_enrich_service import CatalogEnrichService

    service = CatalogEnrichService(db)
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalars().first()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    try:
        job = await service.apply(job)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(job.id), "applied": True}


@router.post("/jobs/{job_id}/enrichment/reject", response_model=dict)
async def reject_enrichment(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Discard the proposal without touching curated attributes."""
    from app.core.errors import NotFoundError
    from app.models.job_model import Job
    from app.services.catalog.catalog_enrich_service import CatalogEnrichService

    service = CatalogEnrichService(db)
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalars().first()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    try:
        job = await service.reject(job)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(job.id), "applied": False}


def _query_info(source) -> dict:
    """The merged radar query the next syncs rotate through (plan 130
    transparency: nothing hidden — keywords, location, rotation position,
    provenance). Radar data only; no secrets."""
    cache = source.query_cache or {}
    groups = cache.get("groups") or []
    index = int(cache.get("rotation_index") or 0)
    current = groups[index % len(groups)] if groups else {}
    return {
        "keywords": str((current or {}).get("keywords") or ""),
        "location": str(cache.get("location") or ""),
        "rotation": f"{(index % len(groups)) + 1}/{len(groups)}" if groups else "",
        "rotation_index": index,
        "groups": [
            {
                "terms": list(group.get("terms") or []),
                "keywords": str(group.get("keywords") or ""),
            }
            for group in groups
        ],
        "provenance": dict(cache.get("provenance") or {}),
        "group_terms": list((current or {}).get("terms") or []),
        "curated": bool(cache.get("curated")),
        "radar_ids": list(cache.get("radar_ids") or []),
        "computed_at": cache.get("computed_at"),
    }


def _managed_bundle_schema(source) -> tuple[bool, dict | None]:
    """Plan 131 managed-bundle surface: when the source's stdio command
    spawns a digest-pinned bundle entry, return the bundle manifest's
    ``configSchema`` — the form the bundle declares (manifest shape only,
    never values). Non-managed sources return ``(False, None)``."""
    from pathlib import Path
    from shlex import split as shlex_split

    from app.core.config import settings

    try:
        parts = shlex_split(str((source.config or {}).get("command") or ""))
    except ValueError:
        return False, None
    if not parts:
        return False, None
    entry = Path(parts[-1])
    if entry.name != "server.py":
        return False, None
    content_dir = entry.parent
    content_root = (Path(settings.data_dir) / "extensions").resolve()
    try:
        content_dir.resolve().relative_to(content_root)
    except ValueError:
        return False, None
    manifest_path = content_dir / "manifest.json"
    if not manifest_path.is_file():
        return False, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None
    schema = manifest.get("configSchema")
    return True, schema if isinstance(schema, dict) else None


async def _source_view(db: AsyncSession, source) -> dict:
    """Secret-safe source view: config WITHOUT any x-secret field values
    (they cannot be stored there — belt and braces for legacy rows), plus
    slot presence and key hints. Never the sealed values, never plaintext."""
    from app.core.encryption import decrypt_secret
    from app.extensions.registry import resolve_connector

    managed, tool_config_schema = _managed_bundle_schema(source)
    config = dict(source.config or {})

    from app.models.posting_model import JobPosting

    posting_count = (
        await db.execute(
            select(func.count()).select_from(JobPosting).where(JobPosting.source_id == source.id)
        )
    ).scalar_one()
    secret_hints: dict[str, dict] = {}
    if source.kind == "market":
        slots = {}
    else:
        try:
            connector = await resolve_connector(db, source.connector_key)
            slots = connector.secret_slots()
        except Exception:
            slots = {}
    for slot in slots:
        sealed = (source.secrets or {}).get(slot)
        value = decrypt_secret(sealed) if isinstance(sealed, str) else None
        config.pop(slot, None)
        secret_hints[slot] = {
            "set": bool(value),
            "hint": (f"…{value[-4:]}" if value and len(value) >= 8 else ("set" if value else None)),
        }
    return {
        "id": str(source.id),
        "key": source.key,
        "connector_key": source.connector_key,
        "kind": source.kind,
        "schedule_kind": source.schedule_kind,
        "config": config,
        "query_mode": source.query_mode,
        "query_batch_size": source.query_batch_size,
        "query_info": _query_info(source),
        "posting_count": posting_count,
        "managed": managed,
        "tool_config_schema": tool_config_schema,
        "secret_hints": secret_hints,
        "enabled": source.enabled,
        "paused_at": source.paused_at.isoformat() if source.paused_at else None,
        "last_status": source.last_status,
        "last_run_at": source.last_run_at.isoformat() if source.last_run_at else None,
        "sync_state": source.sync_state,
        "error": source.error,
    }


def _seal_source_secrets(source, secrets_payload: dict) -> None:
    """Merge a secrets payload into the sealed slot map: plaintext values
    are sealed at write; the ``***`` mask marker preserves the stored
    value; an empty string clears it (INV-4 — plaintext never lands in
    storage)."""
    from app.core.encryption import MASK_MARKER, encrypt_secret

    sealed = dict(source.secrets or {})
    for slot, value in (secrets_payload or {}).items():
        if value == MASK_MARKER:
            continue
        if value:
            sealed[slot] = encrypt_secret(str(value))
        else:
            sealed.pop(slot, None)
    source.secrets = sealed


@router.get("/postings/sources", response_model=list[dict])
async def posting_sources(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Posting sources with their sync health (secret-safe views)."""
    from app.models.posting_model import JobSource

    rows = (
        (await db.execute(select(JobSource).order_by(JobSource.created_at.desc()))).scalars().all()
    )
    return [await _source_view(db, s) for s in rows]


@router.post("/postings/sources", status_code=201)
async def create_posting_source(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    """Enable a source: connector key + config validated against the engine.

    Secret values ride the ``secrets`` payload and are sealed at write —
    a plaintext secret inside ``config`` is a 400 (the x-secret law)."""
    from app.core.encryption import encrypt_secret
    from app.extensions.registry import get_connector
    from app.models.posting_model import JobSource

    key = str(payload.get("key") or "").strip()
    connector_key = str(payload.get("connector_key") or "").strip()
    kind = str(payload.get("kind") or "posting").strip()
    query_mode = str(payload.get("query_mode") or "static").strip()
    if query_mode not in {"static", "radar"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported query_mode: {query_mode}")
    query_batch_size = int(payload.get("query_batch_size") or 2)
    if query_batch_size not in (1, 2, 3, 4, 5, 6):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "query_batch_size must be between 1 and 6")
    if kind not in ("posting", "market"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported source kind: {kind}")
    config = payload.get("config") or {}
    if kind == "market":
        from app.services.postings.demand_import_service import validate_market_config

        connector_key = connector_key or "demand_data"
        validated = validate_market_config(config)
    else:
        relax = ("keywords", "location") if query_mode == "radar" else ()
        try:
            connector = get_connector(connector_key)
            validated = connector.validate_config(config, relax_keys=relax)
        except DomainError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    source = JobSource(
        key=key,
        connector_key=connector_key,
        kind=kind,
        config=validated,
        query_mode=query_mode,
        query_batch_size=query_batch_size,
        secrets={
            slot: encrypt_secret(str(value))
            for slot, value in (payload.get("secrets") or {}).items()
            if value
        },
        enabled=bool(payload.get("enabled", True)),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return {
        "id": str(source.id),
        "key": source.key,
        "connector_key": source.connector_key,
    }


@router.put("/postings/sources/{source_id}")
async def update_posting_source(
    source_id: uuid.UUID, payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Edit config/secrets/enable state (config re-validated against the
    connector; ``***`` preserves a stored secret, empty string clears it)."""
    from app.models.posting_model import JobSource

    source = (
        (await db.execute(select(JobSource).where(JobSource.id == source_id))).scalars().first()
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if "config" in payload and payload["config"] is not None:
        effective_mode = str(payload.get("query_mode") or source.query_mode or "static").strip()
        relax = ("keywords", "location") if effective_mode == "radar" else ()
        try:
            if source.kind == "market":
                from app.services.postings.demand_import_service import validate_market_config

                source.config = validate_market_config(payload["config"])
            else:
                from app.extensions.registry import resolve_connector

                connector = await resolve_connector(db, source.connector_key)
                source.config = connector.validate_config(payload["config"], relax_keys=relax)
        except DomainError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if "secrets" in payload and payload["secrets"] is not None:
        _seal_source_secrets(source, payload["secrets"])
    if "query_mode" in payload and payload["query_mode"] is not None:
        mode = str(payload["query_mode"]).strip()
        if mode not in {"static", "radar"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported query_mode: {mode}")
        if mode != source.query_mode:
            source.query_mode = mode
            source.query_cache = None
    if "query_batch_size" in payload and payload["query_batch_size"] is not None:
        batch = int(payload["query_batch_size"])
        if batch not in (1, 2, 3, 4, 5, 6):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "query_batch_size must be between 1 and 6"
            )
        source.query_batch_size = batch
    if "enabled" in payload and payload["enabled"] is not None:
        source.enabled = bool(payload["enabled"])
    if "paused" in payload and payload["paused"] is not None:
        source.paused_at = datetime.now(UTC) if payload["paused"] else None
    await db.commit()
    return await _source_view(db, source)


@router.delete("/postings/sources/{source_id}")
async def delete_posting_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Remove a job source and its ingested data (plan 133): the schema's
    cascade is deliberate — postings, applications and autopilot rows go
    with their source — so this is a DESTRUCTIVE act the UI confirms
    explicitly with counts before calling."""

    from app.models.posting_model import JobPosting, JobSource

    source = (
        (await db.execute(select(JobSource).where(JobSource.id == source_id))).scalars().first()
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    posting_count = (
        await db.execute(
            select(func.count()).select_from(JobPosting).where(JobPosting.source_id == source.id)
        )
    ).scalar_one()
    key = source.key
    await db.delete(source)
    await db.commit()
    return {"id": str(source_id), "key": key, "deleted": True, "postings_removed": posting_count}


@router.post("/postings/sources/{source_id}/sync")
async def sync_posting_source(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manual refresh — queued via."""
    from app.models.posting_model import JobSource
    from app.services.job_worker import enqueue

    source = (
        (await db.execute(select(JobSource).where(JobSource.id == source_id))).scalars().first()
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if source.kind != "posting":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "this source is not a posting source")
    job = await enqueue(
        db,
        BackgroundJobType.POSTING_SYNC.value,
        {"source_id": str(source_id), "trigger": "manual"},
        user_id=user.id,
    )
    return {"job_id": str(job.id), "status": job.status}


@router.get("/postings/sources/{source_id}/runs", response_model=list[dict])
async def list_source_runs(
    source_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The run ledger (plan 134): newest first — when it ran, trigger,
    duration, status, items synced and the bounded error.

    Ghost healing on read: a crash can leave a ``running`` row behind and
    the page would claim "Running now" for hours (the next sync only
    closes it later). Rows past the same staleness cutoff the next run
    uses close as interrupted here, so the banner tells the truth."""
    from datetime import UTC, datetime, timedelta

    from app.models.posting_model import SourceRun
    from app.services.postings.postings_service import STALE_RUN_MINUTES

    now = datetime.now(UTC)
    stale = (
        (
            await db.execute(
                select(SourceRun).where(
                    SourceRun.source_id == source_id,
                    SourceRun.status == "running",
                    SourceRun.started_at < now - timedelta(minutes=STALE_RUN_MINUTES),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in stale:
        row.status = "failed"
        row.error = "interrupted — the run never finished"
        row.finished_at = now
    if stale:
        await db.commit()

    rows = (
        (
            await db.execute(
                select(SourceRun)
                .where(SourceRun.source_id == source_id)
                .order_by(SourceRun.started_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "trigger": row.trigger,
            "status": row.status,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "duration_ms": row.duration_ms,
            "items_synced": row.items_synced,
            "error": row.error,
            "report": row.report,
        }
        for row in rows
    ]


@router.post("/postings/sources/{source_id}/probe")
async def probe_posting_source(
    source_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One live guarded fetch through the polite runtime — the source
    management UI's Test button. Typed outcome, never a raw error string;
    needs-secret reports the missing slot instead of fetching."""
    import time as _time

    from app.extensions.polite_http import PoliteHttpError
    from app.extensions.registry import get_connector
    from app.extensions.runtime.http import build_transport
    from app.extensions.sdk import ConnectorError
    from app.models.posting_model import JobSource
    from app.services.postings.postings_service import resolve_source_secrets

    source = (
        (await db.execute(select(JobSource).where(JobSource.id == source_id))).scalars().first()
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if source.kind != "posting":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "this source is not a posting source")
    connector = get_connector(source.connector_key)
    secrets = resolve_source_secrets(source)
    missing = [
        slot
        for slot in connector.secret_slots()
        if connector.capabilities.requires_credentials and not secrets.get(slot)
    ]
    if missing:
        error = ConnectorError.needs_secret(f"missing secret slot(s): {', '.join(sorted(missing))}")
        return {"ok": False, "error": error.model_dump(mode="json")}
    started = _time.monotonic()
    audit = None
    if getattr(connector, "audits_effects", False):
        from app.extensions.runtime.mcp import mcp_effect_auditor

        audit = mcp_effect_auditor(db, source.key)
    try:
        result = await connector.fetch(
            source.config,
            {},
            transport=build_transport(
                domains=frozenset(connector.capabilities.network_scopes or []),
                requests_per_minute=connector.capabilities.max_requests_per_minute,
            ),
            secrets=secrets,
            audit=audit,
        )
    except PoliteHttpError as exc:
        error = ConnectorError.from_polite(exc)
        return {
            "ok": False,
            "error": error.model_dump(mode="json"),
            "latency_ms": int((_time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        logger.warning("provider connection test failed", exc_info=True)
        error = ConnectorError(
            code="provider", detail=sanitize_error_detail(str(exc), limit=500), retryable="yes"
        )
        return {
            "ok": False,
            "error": error.model_dump(mode="json"),
            "latency_ms": int((_time.monotonic() - started) * 1000),
        }
    if audit is not None:
        # Effect-auditing connectors wrote audit rows on the request
        # session — commit them or they vanish at session close (the
        # sync path commits with the source run; the probe must too).
        await db.commit()
    ok = not result.partial_errors
    first_error = (
        result.partial_errors[0].model_dump(mode="json") if result.partial_errors else None
    )
    return {
        "ok": ok,
        "items": len(result.items),
        "error": first_error,
        "latency_ms": int((_time.monotonic() - started) * 1000),
    }


# ---------------------------------------------------- extension sources
# The import layer (plan 32 Phase 3 / ADR-0040 D13+D22): git sources,
# consent-gated installs, digest pins and GitOps desired state.


def _lifecycle_error(exc) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND if exc.code == "not-found" else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code, f"{exc.code}: {exc.detail}")


@router.get("/extensions/sources", response_model=list[dict])
async def extension_sources(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Sources with their discovered candidates and installs (secret-safe:
    sealed credential slots surface as presence only)."""
    from app.extensions.lifecycle import list_sources

    return await list_sources(db)


@router.post("/extensions/sources", status_code=201)
async def add_extension_source(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    """Add a git source (https production descriptor, or the dev/test
    `local` variant — gated off in production boots, confined to
    allowlisted roots). Private-repo credentials ride the ``secrets``
    payload as sealed slot values, never inline in the descriptor."""
    from app.extensions.lifecycle import LifecycleError, add_source

    try:
        return await add_source(db, payload.get("descriptor") or {}, secrets=payload.get("secrets"))
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.patch("/extensions/sources/{source_id}")
async def update_extension_source(
    source_id: uuid.UUID, payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Replace a source's descriptor (the edit flow) — validated exactly
    like an add; the next sync re-resolves and reports drift normally."""
    from app.extensions.lifecycle import LifecycleError, update_source

    try:
        return await update_source(
            db,
            source_id,
            payload.get("descriptor") or {},
            secrets=payload.get("secrets"),
        )
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.post("/extensions/sources/upload", status_code=201)
async def upload_extension_source(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Zip bundle import (plan 132): a FEEDER for the sources pipeline —
    the zip is staged as a local source tree (host-owned staging dir, one
    synthetic commit), then the normal add + sync run unchanged (consent
    and digest-pinned install are still the admin's acts). Dev/test only."""
    from app.extensions.lifecycle import LifecycleError, import_zip_bundle

    data = await file.read()
    try:
        view = await import_zip_bundle(db, data)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc
    return {"id": view["id"], "kind": view["kind"], "sync": view.get("sync")}


@router.delete("/extensions/sources/{source_id}")
async def remove_extension_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Remove a source: installs park (disabled, data intact, tombstone-
    able) — removal never deletes data."""
    from app.extensions.lifecycle import LifecycleError, remove_source

    try:
        return await remove_source(db, source_id)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.post("/extensions/sources/{source_id}/sync")
async def sync_extension_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Fetch + discover + validate + update-check. A failed fetch leaves
    pins untouched and marks the source failing (typed error body)."""
    from app.extensions.lifecycle import LifecycleError, sync_source

    try:
        return await sync_source(db, source_id)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.get("/extensions/sources/{source_id}/preview/{extension_id}")
async def preview_extension_install(
    source_id: uuid.UUID, extension_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """The host-derived install preview (plan 37 Phase 3.1): re-fetch +
    re-discover + register + digest, returning the consent payload and the
    exact echo ``{digest, capabilities, version}`` the install call must
    hand back. The UI never fabricates a digest."""
    from app.extensions.lifecycle import LifecycleError, preview_install

    try:
        return await preview_install(db, source_id, extension_id)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.get("/extensions/installs/{install_id}/preview")
async def preview_extension_update(
    install_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """The host-derived update preview: the exact echo an explicit
    re-consent (apply) hands back."""
    from app.extensions.lifecycle import LifecycleError, preview_update

    try:
        return await preview_update(db, install_id)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.post("/extensions/sources/{source_id}/install", status_code=201)
async def install_from_source(
    source_id: uuid.UUID,
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Consent-gated install (D7): ``{"extension_id": ..., "consent":
    {digest, capabilities, version}}`` — the echo from the preview endpoint
    (capabilities, tier, provenance, digest and the T3 perimeter disclosure
    were shown BEFORE this call). The host re-derives the values and
    refuses drift typed. Installs are DISABLED; enabling is a separate
    explicit act."""
    from app.extensions.lifecycle import LifecycleError, install_extension

    if not payload.get("extension_id"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "extension_id is required")
    consent = payload.get("consent")
    if not isinstance(consent, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "consent must be the host-derived echo object"
        )
    try:
        return await install_extension(
            db,
            source_id,
            str(payload["extension_id"]),
            consent=consent,
            actor_id=user.id,
        )
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.post("/extensions/installs/{install_id}/apply")
async def apply_extension_update(
    install_id: uuid.UUID,
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The only apply path: an explicit re-consent to a recorded available
    update, as the host-derived echo from ``GET .../installs/{id}/preview``
    (no signing service exists — there is no auto-apply at all)."""
    from app.extensions.lifecycle import LifecycleError, apply_update

    consent = payload.get("consent")
    if not isinstance(consent, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "consent must be the host-derived echo object"
        )
    try:
        return await apply_update(db, install_id, consent=consent, actor_id=user.id)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.post("/extensions/installs/{install_id}/enabled")
async def set_extension_enabled(
    install_id: uuid.UUID, payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """The ONLY enable path — an explicit admin act. Installs, updates and
    reconcile never auto-enable (D22)."""
    from app.extensions.lifecycle import LifecycleError, set_install_enabled

    try:
        return await set_install_enabled(db, install_id, bool(payload.get("enabled")))
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.post("/extensions/installs/{install_id}/park")
async def park_extension_install(install_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Park: disabled + flagged, data intact, tombstone-able."""
    from app.extensions.lifecycle import LifecycleError, park_install

    try:
        return await park_install(db, install_id)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.post("/extensions/installs/{install_id}/tombstone")
async def tombstone_extension_install(
    install_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Tombstone (lifecycle `removed`): instance disabled, install + consent
    records retained — re-import surfaces history, never silent re-enable."""
    from app.extensions.lifecycle import LifecycleError, tombstone_install

    try:
        return await tombstone_install(db, install_id)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.get("/extensions/desired-state", response_model=dict)
async def get_extension_desired_state(db: AsyncSession = Depends(get_db)) -> dict:
    """The GitOps desired-state document (admin-owned; the model never
    authors it — ADR-0011 §7)."""
    from app.extensions.lifecycle import get_desired_state

    return await get_desired_state(db)


@router.put("/extensions/desired-state")
async def put_extension_desired_state(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    """Set the desired-state document (validated against the vendored
    desiredStateDocument schema — deletion is structurally inexpressible)."""
    from app.extensions.lifecycle import LifecycleError, put_desired_state

    try:
        return await put_desired_state(db, payload)
    except LifecycleError as exc:
        raise _lifecycle_error(exc) from exc


@router.post("/extensions/reconcile")
async def reconcile_extensions(db: AsyncSession = Depends(get_db)) -> dict:
    """Run the GitOps reconcile now (the scheduler runs it hourly; boot
    runs it once at startup). Installs and moves pins only — never
    enables, never deletes data; the report is the drift surface."""
    from app.extensions.lifecycle import reconcile

    return await reconcile(db)


@router.post("/postings/{posting_id}/map")
async def manual_map_posting(
    posting_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """Moderation fallback: human mapping wins (method=manual, never re-mapped)."""
    from app.models.enums import MappingMethod
    from app.models.posting_model import JobPosting
    from app.services.postings.change_journal import RETAG_FIELDS, PostingChangeJournal, snapshot

    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalars().first()
    )
    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posting not found")
    job_id = payload.get("catalog_job_id")
    if not job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "catalog_job_id is required")
    try:
        job = await JobService(db).require_job(uuid.UUID(str(job_id)))
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    before = snapshot(posting, RETAG_FIELDS)
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped by a moderator"
    posting.status = "mapped"
    PostingChangeJournal.record(
        db,
        posting.id,
        "manual",
        actor_ref={"user_id": str(user.id)},
        operation={"catalog_job_id": str(job.id), "catalog_job_code": job.code},
        before=before,
        after=snapshot(posting, RETAG_FIELDS),
    )
    await db.commit()
    return {
        "id": str(posting.id),
        "status": posting.status,
        "mapping_method": posting.mapping_method,
        "catalog_job_id": str(job.id),
    }


@router.get("/postings")
async def admin_list_postings(
    needs_review: bool | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Moderation surface: review-flagged / unmapped postings."""
    from app.models.enums import PostingStatus
    from app.models.posting_model import JobPosting

    query = select(JobPosting).order_by(JobPosting.created_at.desc()).limit(limit)
    if needs_review is not None:
        query = query.where(JobPosting.needs_review.is_(needs_review))
    if status:
        PostingStatus(status)  # validate against the enum
        query = query.where(JobPosting.status == status)
    rows = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "org": p.org,
            "status": p.status,
            "needs_review": p.needs_review,
            "extract_version": p.extract_version,
            "mapping_method": p.mapping_method,
            "mapping_confidence": p.mapping_confidence,
            "mapping_reason": p.mapping_reason,
            "catalog_job_id": str(p.catalog_job_id) if p.catalog_job_id else None,
            "suppressed_fields": (p.extract or {}).get("_suppressed_fields", []),
        }
        for p in rows
    ]


@router.post("/postings/reextract")
async def reextract_postings_by_ids(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    """Re-run deep extraction for the given postings (admin, bulk — the
    /postings multi-select). Same rules as the per-source bulk: only
    postings WITH a description queue; already-queued ones are skipped;
    unknown ids are reported as missing."""
    ids = [str(item) for item in (payload.get("posting_ids") or [])][:200]
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "posting_ids is required")
    from app.models.posting_model import JobPosting
    from app.services.postings.extract_service import queue_posting_extract

    queued = skipped = 0
    missing: list[str] = []
    for raw_id in ids:
        try:
            lookup_id = uuid.UUID(str(raw_id))
        except ValueError:
            missing.append(raw_id)
            continue
        posting = (
            (await db.execute(select(JobPosting).where(JobPosting.id == lookup_id)))
            .scalars()
            .first()
        )
        if posting is None or posting.status not in ("new", "mapped"):
            missing.append(raw_id)
            continue
        if not str((posting.raw or {}).get("description") or "").strip():
            skipped += 1
            continue
        if await queue_posting_extract(db, posting):
            queued += 1
        else:
            skipped += 1
    await db.commit()
    return {
        "queued": queued,
        "skipped": skipped,
        "missing": missing[:50],
        "requested": len(ids),
    }


@router.post("/postings/{posting_id}/extract")
async def reextract_posting(posting_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Re-run the deep extraction for one posting now (admin)."""
    from app.models.posting_model import JobPosting
    from app.services.postings.extract_service import extract_posting_now

    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalars().first()
    )
    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posting not found")
    try:
        return await extract_posting_now(db, posting)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/scheduler/schedules", response_model=list[ScheduleItemOut])
async def admin_schedules(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """System schedules (owner null): next run, last status, failures."""
    from app.services.scheduler.runner import SchedulerService

    service = SchedulerService(db)
    await service.ensure_system_schedules()
    rows = await service.list_schedules(None)
    return [
        {
            "id": str(s.id),
            "kind": s.kind,
            "task": s.task,
            "trigger": s.trigger,
            "payload": s.payload,
            "enabled": s.enabled,
            "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "last_status": s.last_status,
            "consecutive_failures": s.consecutive_failures,
            "misfire_policy": s.misfire_policy,
            "error": s.error,
        }
        for s in rows
    ]


@router.put("/scheduler/schedules/{schedule_id}", response_model=ScheduleToggleOut)
async def admin_update_schedule(
    schedule_id: uuid.UUID, payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Pause/resume a system schedule."""
    from app.services.scheduler.runner import SchedulerService

    enabled = payload.get("enabled")
    if enabled is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "enabled is required")
    schedule = await SchedulerService(db).set_enabled(schedule_id, bool(enabled))
    return {"id": str(schedule.id), "enabled": schedule.enabled}


@router.post("/scheduler/schedules/{schedule_id}/run-now", response_model=ScheduleRunNowOut)
async def admin_run_schedule_now(
    schedule_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Make the schedule due on the next tick."""
    from app.services.scheduler.runner import SchedulerService

    schedule = await SchedulerService(db).run_now(schedule_id)
    return {
        "id": str(schedule.id),
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
    }


async def _overlay_base_value(db: AsyncSession, overlay) -> str:
    """The catalog entity's current source-locale display value."""
    from app.models.enums import LabelEntityKind
    from app.models.job_model import Job, JobFamily
    from app.models.taxonomy_model import Skill

    kind = LabelEntityKind(overlay.entity_kind)
    if kind == LabelEntityKind.JOB:
        job = (await db.execute(select(Job).where(Job.id == overlay.entity_id))).scalars().first()
        if job is None:
            return ""
        return job.title if overlay.field == "label" else job.short_description
    if kind == LabelEntityKind.SKILL:
        skill = (
            (await db.execute(select(Skill).where(Skill.id == overlay.entity_id))).scalars().first()
        )
        if skill is None:
            return ""
        return skill.label if overlay.field == "label" else skill.description
    if kind == LabelEntityKind.FAMILY:
        family = (
            (await db.execute(select(JobFamily).where(JobFamily.id == overlay.entity_id)))
            .scalars()
            .first()
        )
        if family is None:
            return ""
        return family.label if overlay.field == "label" else family.description
    return ""


@router.get("/i18n/locale", response_model=LocaleStateOut)
async def get_instance_locale(db: AsyncSession = Depends(get_db)) -> dict:
    """Instance default UI locale plus the supported registry."""
    from app.services.locale_service import (
        SUPPORTED_LOCALES,
        instance_default_locale,
    )

    return {
        "locale": await instance_default_locale(db),
        "supported": list(SUPPORTED_LOCALES),
    }


@router.put("/i18n/locale", response_model=LocaleStateOut)
async def put_instance_locale(body: LocaleIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Set the instance default UI locale (users keep their own choice)."""
    from app.services.locale_service import SUPPORTED_LOCALES, set_instance_default_locale

    locale = await set_instance_default_locale(db, body.locale)
    return {"locale": locale, "supported": list(SUPPORTED_LOCALES)}


@router.post("/i18n/translate", response_model=dict)
async def translate_keys(
    body: TranslateKeysIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Audited UI-catalog translation batch (maintainer tooling)."""
    from app.services.translation_service import TranslationService

    translations = await TranslationService(db).translate_keys(
        body.locale, body.entries, user_id=user.id
    )
    return {"locale": body.locale, "translations": translations}


@router.get("/i18n/overlays", response_model=list[OverlayOut])
async def overlay_queue(
    locale: str | None = Query(default=None),
    overlay_status: str | None = Query(default="draft", alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Catalog-label overlays awaiting (or having completed) review."""
    from app.services.catalog.label_overlay_service import LabelOverlayService

    rows = await LabelOverlayService(db).queue(
        locale=locale, row_status=overlay_status, limit=limit
    )
    out = []
    for row in rows:
        out.append(
            {
                "id": str(row.id),
                "entity_kind": row.entity_kind,
                "entity_id": str(row.entity_id),
                "locale": row.locale,
                "field": row.field,
                "value": row.value,
                "base_value": await _overlay_base_value(db, row),
                "source": row.source,
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    return out


@router.post("/i18n/overlays/draft", response_model=OverlayDraftResultOut)
async def draft_overlays(
    body: OverlayDraftIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI-draft overlays for taxonomy rows (draft status; never renders)."""
    from app.core.errors import AINotConfiguredError, DomainError
    from app.services.translation_service import TranslationService

    try:
        drafted = await TranslationService(db).draft_catalog_labels(
            body.locale, body.entity_kinds, body.limit, user_id=user.id
        )
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"locale": body.locale, "drafted": drafted}


@router.patch("/i18n/overlays/{overlay_id}", response_model=OverlayStatusOut)
async def edit_overlay(
    overlay_id: uuid.UUID, body: OverlayPatchIn, db: AsyncSession = Depends(get_db)
) -> dict:
    """Reviewer edit of a drafted overlay value (approval stays separate)."""
    from app.core.errors import NotFoundError
    from app.services.catalog.label_overlay_service import LabelOverlayService

    try:
        row = await LabelOverlayService(db).edit_value(overlay_id, body.value)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(row.id), "value": row.value, "status": row.status}


@router.post("/i18n/overlays/{overlay_id}/approve", response_model=OverlayStatusOut)
async def approve_overlay(overlay_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Approve one overlay — the only route to rendering."""
    from app.core.errors import NotFoundError
    from app.models.enums import LabelStatus
    from app.services.catalog.label_overlay_service import LabelOverlayService

    try:
        row = await LabelOverlayService(db).set_status(overlay_id, LabelStatus.APPROVED)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(row.id), "status": row.status}


@router.post("/i18n/overlays/{overlay_id}/reject", response_model=OverlayStatusOut)
async def reject_overlay(overlay_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Reject one overlay (it never renders)."""
    from app.core.errors import NotFoundError
    from app.models.enums import LabelStatus
    from app.services.catalog.label_overlay_service import LabelOverlayService

    try:
        row = await LabelOverlayService(db).set_status(overlay_id, LabelStatus.REJECTED)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(row.id), "status": row.status}
