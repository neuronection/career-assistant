"""Admin surface: catalog moderation and AI audit viewer.

User management (`/admin/users`, reset-password, force-logout) is the
auth-kit's §12 surface now — see `nx_auth.user_admin` (plan 16 P3a)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.errors import DomainError, ValidationError
from app.models.ai_model import AIGeneration
from app.models.enums import BackgroundJobType
from app.models.user_model import User
from app.schemas.job import JobOut
from app.services.deps import get_current_user, require_admin
from app.services.job_service import JobService
from app.services.taxonomy_service import TaxonomyService

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


class AIGenerationOut(BaseModel):
    id: uuid.UUID
    task_type: str
    provider: str
    model: str
    prompt: str
    output: dict | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: float | None
    status: str
    error: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/ai/generations")
async def audit_generations(
    task: str | None = Query(default=None),
    model: str | None = Query(default=None),
    generation_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Paginated AI audit trail with filters."""
    conditions = []
    if task:
        conditions.append(AIGeneration.task_type == task)
    if model:
        conditions.append(AIGeneration.model == model)
    if generation_status:
        conditions.append(AIGeneration.status == generation_status)

    base = select(AIGeneration)
    count_query = select(func.count(AIGeneration.id))
    if conditions:
        base = base.where(*conditions)
        count_query = count_query.where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0
    rows = (
        (
            await db.execute(
                base.order_by(AIGeneration.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "items": [AIGenerationOut.model_validate(r) for r in rows],
    }


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
    db: AsyncSession = Depends(get_db),
) -> dict:
    """proposed → active; the vocabulary stays clean via admin review."""
    from app.schemas.taxonomy import SkillOut

    try:
        skill = await TaxonomyService(db).promote(skill_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SkillOut.model_validate(skill).model_dump(mode="json")


@router.post("/skills/{skill_id}/merge")
async def merge_skill(
    skill_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Merge a duplicate into `target_id` (aliases redirect, joins rewritten)."""
    from app.schemas.taxonomy import SkillOut

    target_id = body.get("target_id")
    if not target_id:
        raise ValidationError("target_id is required")
    try:
        skill = await TaxonomyService(db).merge(skill_id, uuid.UUID(str(target_id)))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "target_id must be a UUID") from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SkillOut.model_validate(skill).model_dump(mode="json")


@router.get("/paths")
async def path_moderation_queue(
    path_status: str = Query(default="draft", alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """All paths by status (default: AI drafts awaiting review)."""
    from app.models.career_path_model import CareerPath
    from app.services.paths_service import PathService

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
    from app.services.paths_service import PathService

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
    from app.services.paths_service import PathService

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
    from app.services.organization_service import OrganizationService

    return await OrganizationService(db).list_orgs(status=status, q=q)


@router.post("/organizations/{org_id}/promote", response_model=dict)
async def promote_organization(org_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """proposed → active (the only promotion path, like skills)."""
    from app.services.organization_service import OrganizationService

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
    from app.services.organization_service import OrganizationService

    try:
        org = await OrganizationService(db).add_alias(org_id, str(payload.get("alias") or ""))
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"id": str(org.id), "aliases": org.aliases or []}


@router.post("/organizations/{org_id}/merge", response_model=dict)
async def merge_organization(
    org_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-point all references to the target; the duplicate is deprecated."""
    from app.services.organization_service import OrganizationService

    try:
        target_id = uuid.UUID(str(payload.get("target_id")))
        org = await OrganizationService(db).merge(org_id, target_id)
    except (ValueError, DomainError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "id": str(org.id),
        "status": org.status,
        "aliases": org.aliases or [],
    }


@router.post("/organizations/backfill", response_model=dict)
async def backfill_organizations(db: AsyncSession = Depends(get_db)) -> dict:
    """Run the matcher over postings ingested before it existed."""
    from app.services.organization_service import OrganizationService

    return await OrganizationService(db).backfill_postings()


@router.get("/jobs/enrichment", response_model=list[dict])
async def enrichment_queue(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Catalog v2-enrichment proposals awaiting moderation."""
    from app.services.catalog_enrich_service import CatalogEnrichService

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
    from app.services.catalog_enrich_service import CatalogEnrichService

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
    from app.services.catalog_enrich_service import CatalogEnrichService

    service = CatalogEnrichService(db)
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalars().first()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    try:
        job = await service.reject(job)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(job.id), "applied": False}


async def _source_view(db: AsyncSession, source) -> dict:
    """Secret-safe source view: config WITHOUT any x-secret field values
    (they cannot be stored there — belt and braces for legacy rows), plus
    slot presence and key hints. Never the sealed values, never plaintext."""
    from app.core.encryption import decrypt_secret
    from app.extensions.registry import resolve_connector

    config = dict(source.config or {})
    secret_hints: dict[str, dict] = {}
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
        "config": config,
        "secret_hints": secret_hints,
        "enabled": source.enabled,
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
    config = payload.get("config") or {}
    try:
        connector = get_connector(connector_key)
        validated = connector.validate_config(config)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    source = JobSource(
        key=key,
        connector_key=connector_key,
        config=validated,
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
        try:
            from app.extensions.registry import resolve_connector

            connector = await resolve_connector(db, source.connector_key)
            source.config = connector.validate_config(payload["config"])
        except DomainError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if "secrets" in payload and payload["secrets"] is not None:
        _seal_source_secrets(source, payload["secrets"])
    if "enabled" in payload and payload["enabled"] is not None:
        source.enabled = bool(payload["enabled"])
    await db.commit()
    return await _source_view(db, source)


@router.post("/postings/sources/{source_id}/sync")
async def sync_posting_source(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manual refresh — queued via."""
    from app.services.job_worker import enqueue

    job = await enqueue(
        db,
        BackgroundJobType.POSTING_SYNC.value,
        {"source_id": str(source_id)},
        user_id=user.id,
    )
    return {"job_id": str(job.id), "status": job.status}


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
    from app.services.postings_service import resolve_source_secrets

    source = (
        (await db.execute(select(JobSource).where(JobSource.id == source_id))).scalars().first()
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
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
        error = ConnectorError(code="provider", detail=str(exc)[:500], retryable="yes")
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
    try:
        return await install_extension(
            db,
            source_id,
            str(payload["extension_id"]),
            consent=payload.get("consent"),
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

    try:
        return await apply_update(db, install_id, consent=payload.get("consent"), actor_id=user.id)
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
    posting_id: uuid.UUID, payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Moderation fallback: human mapping wins (method=manual, never re-mapped)."""
    from app.models.enums import MappingMethod
    from app.models.posting_model import JobPosting

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
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped by a moderator"
    posting.status = "mapped"
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


@router.post("/postings/{posting_id}/extract")
async def reextract_posting(posting_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Re-run the deep extraction for one posting now (admin)."""
    from app.models.posting_model import JobPosting
    from app.services.extract_service import extract_posting_now

    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalars().first()
    )
    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posting not found")
    try:
        return await extract_posting_now(db, posting)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/scheduler/schedules", response_model=list[dict])
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


@router.put("/scheduler/schedules/{schedule_id}")
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


@router.post("/scheduler/schedules/{schedule_id}/run-now")
async def admin_run_schedule_now(
    schedule_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Make the schedule due on the next tick."""
    from app.services.scheduler.runner import SchedulerService

    schedule = await SchedulerService(db).run_now(schedule_id)
    return {"id": str(schedule.id), "next_run_at": schedule.next_run_at.isoformat()}
