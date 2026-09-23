"""CV synth service: the synthesized-variant library + policy engine.

Variants are user-level rows over CV context source items. Staleness is
computed on read (stored source content hash vs the resolver's payload
now); matching is deterministic — active rows only, language must
equal the CV's, posting-scoped rows apply only to their posting and
beat generic ones, `variant_key` "default" first then newest. Manual text edits and an
explicit review refresh `source_state` (plan 102) — staleness then
tracks source drift *after* the user last spoke. Activation supersedes:
other active rows in the same
variant slot auto-archive, so one slot holds one active variant.

AI generation (62.2) runs through the gateway funnel only
(`app.ai.agents.cv_synthetizer`); drafts must cite the request's refs
and are post-verified — anything out of the allowlist is dropped
before persisting. Commits before returning so `ai_generations`
audit rows survive.

Plan 102: approval = activation. Manual payload edits re-ground the
per-ref content hashes (the writer owned the text), and an explicit
review (`refresh_source_state`) does the same without touching text —
staleness then tracks source drift *after* the user spoke.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.ai.gateway import RunRef
from app.core.errors import NotFoundError, ValidationError
from app.models.cv_synth_model import CvSynthItem
from app.models.cv_model import CvDocument
from app.models.enums import CvSynthSource, CvSynthStatus
from app.schemas.cv_synth import (
    CvSynthItemCreate,
    CvSynthItemGenerate,
    CvSynthItemUpdate,
)
from app.services.cv_context_service import CV_CONTEXT_SOURCES, resolve_sources
from app.services.engagement_service import canonical_hash

NO_SYNTH_SOURCES = {"basics"}
SYNC_LIMIT = 5
BULLETS_PIN_SUFFIX = ":bullets"
TEXT_SCOPES = ("item", "summary")


def swap_variant_payload(
    payload: dict, ref: tuple[str, str], variant: CvSynthItem
) -> None:
    """Swap one variant into an item payload by FIELD PRESENCE
    (plan 110 AD1 — one variant per item, one pin slot): each present
    field of the variant's payload OWNS that layer, `scope` is pure
    provenance and no longer branches the swap.

    `description`/`summary` present → swap the text layer;
    `achievements` present → REPLACE the profile's canonical
    `achievements: [{"text"}]` list (generated from that item's
    evidence, staleness hashes catch drift); absent layers stay with
    the profile or any other pinned variant's remaining fields."""
    if not isinstance(payload, dict):
        return
    synth = variant.payload or {}
    if not synth:
        return
    if ref[0] == "summary":
        if synth.get("summary"):
            payload["summary"] = synth["summary"]
        return
    if synth.get("description") is not None:
        payload["description"] = synth["description"]
    if synth.get("summary"):
        payload["summary"] = synth["summary"]
    if synth.get("omit_bullets"):
        # Plan 110: the explicit omission deal — the pinned row clears
        # the item's bullet list entirely (empty `achievements` is the
        # default serialization of text-only rows, never a signal).
        payload["achievements"] = []
    elif synth.get("achievements"):
        payload["achievements"] = list(synth["achievements"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ref_tuple(ref: dict) -> tuple[str, str]:
    return (str(ref.get("source_key") or ""), str(ref.get("item_id") or ""))


async def _context_index(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[tuple[str, str], dict]:
    """`{(source_key, item_id): payload}` over every registered source."""
    resolved = await resolve_sources(db, user_id)
    index: dict[tuple[str, str], dict] = {}
    for source_key, items in resolved.items():
        if source_key in NO_SYNTH_SOURCES:
            continue
        for item in items:
            index[(source_key, str(item.item_id))] = dict(item.payload)
    return index


def _payload_hash(payload: dict) -> str:
    return canonical_hash({k: v for k, v in (payload or {}).items() if k != "photo"})


def _source_state_of(
    refs: list[dict], context: dict[tuple[str, str], dict]
) -> list[dict]:
    """Per-ref content hash of the source payload at creation time."""
    state = []
    for ref in refs:
        key = _ref_tuple(ref)
        payload = context.get(key)
        state.append(
            {
                "source_key": key[0],
                "item_id": key[1],
                "content_hash": _payload_hash(payload) if payload else None,
            }
        )
    return state


def _set_hash(refs: list[dict]) -> str:
    """Canonical hash of the sorted typed refs (lookup + dedupe key)."""
    return canonical_hash(sorted(_ref_tuple(ref) for ref in refs))


def _posting_text(posting) -> str:
    """The posting's prompt-facing text (title + raw description +
    extracted skills/responsibilities), capped for one prompt slot."""
    from app.services.embedding_service import compose_posting_text

    return compose_posting_text(posting)[:2000]


def _validate_refs(refs: list[dict]) -> None:
    if not refs:
        raise ValidationError("A variant needs at least one source ref")
    for ref in refs:
        key = ref.get("source_key", "")
        if key not in CV_CONTEXT_SOURCES:
            raise ValidationError(f"Unknown context source: {key}")
        if key in NO_SYNTH_SOURCES:
            raise ValidationError(f"Source '{key}' is never synthesized")


def _evidence_entry(context: dict[tuple[str, str], dict], ref: dict) -> dict:
    """The compact evidence block the agent prompt cites."""
    key = _ref_tuple(ref)
    payload = context.get(key) or {}
    label = payload.get("title") or payload.get("label") or key[1]
    text = payload.get("description") or payload.get("summary") or ""
    return {
        "source_key": key[0],
        "item_id": key[1],
        "label": label,
        "detail": payload.get("org") or payload.get("institution") or "",
        "payload": {
            "description": text,
            "skills": payload.get("skills") or [],
        },
    }


def _refs_dump(refs: list) -> list[dict]:
    return [{"source_key": ref[0], "item_id": ref[1]} for ref in refs]


class CvSynthService:
    """CRUD + the matching policy for the caller's synthesized variants."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------- library CRUD -------------------------

    async def create_manual(
        self, user_id: uuid.UUID, payload: CvSynthItemCreate
    ) -> CvSynthItem:
        """A user-written variant (no AI; goes live immediately)."""
        refs = [
            {"source_key": r.source_key, "item_id": r.item_id} for r in payload.refs
        ]
        _validate_refs(refs)
        if payload.scope == "bullets":
            if not payload.payload.achievements:
                raise ValidationError("A bullets variant needs at least one bullet")
        elif not payload.payload.text() and not payload.payload.achievements:
            raise ValidationError("A variant needs text")
        context = await _context_index(self.db, user_id)
        row = CvSynthItem(
            user_id=user_id,
            scope=payload.scope,
            variant_key=payload.variant_key,
            target_posting_id=payload.target_posting_id,
            source_refs=refs,
            source_state=_source_state_of(refs, context),
            source_set_hash=_set_hash(refs),
            payload=payload.payload.model_dump(mode="json"),
            evidence_refs=refs,
            voice=payload.voice.model_dump(mode="json"),
            status=CvSynthStatus.ACTIVE.value,
            source=CvSynthSource.MANUAL.value,
            verified=True,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def list_rows(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        source_key: str | None = None,
        posting_id: uuid.UUID | None = None,
        language: str | None = None,
        stale: bool | None = None,
    ) -> list[dict]:
        """The library with computed state, newest first."""
        query = select(CvSynthItem).where(CvSynthItem.user_id == user_id)
        if status is not None:
            query = query.where(CvSynthItem.status == status)
        if posting_id is not None:
            query = query.where(CvSynthItem.target_posting_id == posting_id)
        rows = list(
            (await self.db.execute(query.order_by(CvSynthItem.created_at.desc())))
            .scalars()
            .all()
        )
        context = await _context_index(self.db, user_id)
        out = []
        for row in rows:
            state = self._state_of(row, context)
            if source_key is not None and not any(
                _ref_tuple(ref)[0] == source_key for ref in row.source_refs
            ):
                continue
            if language is not None and row.voice.get("language") != language:
                continue
            if stale is not None and state["stale"] != stale:
                continue
            out.append({"row": row, **state})
        return out

    def _state_of(self, row: CvSynthItem, context: dict[tuple[str, str], dict]) -> dict:
        """Computed read state: staleness + orphaning."""
        stale = False
        orphaned = False
        for ref, entry in zip(row.source_refs, row.source_state):
            payload = context.get(_ref_tuple(ref))
            if payload is None:
                orphaned = True
                continue
            if entry.get("content_hash") != _payload_hash(payload):
                stale = True
        return {"stale": stale, "orphaned": orphaned}

    async def get_owned(self, item_id: uuid.UUID, user_id: uuid.UUID) -> CvSynthItem:
        """Fetch a variant belonging to the caller."""
        row = (
            (
                await self.db.execute(
                    select(CvSynthItem).where(
                        CvSynthItem.id == item_id, CvSynthItem.user_id == user_id
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise NotFoundError("Synthesized item not found")
        return row

    async def update(
        self, item_id: uuid.UUID, user_id: uuid.UUID, payload: CvSynthItemUpdate
    ) -> CvSynthItem:
        """Text edits + status transitions. Activation supersedes siblings.

        A payload edit re-grounds the variant (plan 102): the writer
        owned the text against the current source, so the per-ref
        content hashes refresh and `stale` clears unless the source
        drifts again afterwards."""
        row = await self.get_owned(item_id, user_id)
        if payload.payload is not None:
            row.payload = payload.payload.model_dump(mode="json")
            await self._refresh_source_state(row)
        if payload.variant_key is not None:
            row.variant_key = payload.variant_key
        if payload.status is not None:
            # Multi-active library model: activation no longer sweeps
            # the slot — many rows of one item can be enabled at once.
            # Per-CV usage stays single via the pin (`synth_pins`): the
            # star decides what actually renders, and the pin-priority
            # block in `match_for_user` beats every fallback.
            row.status = payload.status
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def _refresh_source_state(self, row: CvSynthItem) -> None:
        """Snapshot the current source payloads into `source_state`."""
        context = await _context_index(self.db, row.user_id)
        row.source_state = _source_state_of(
            [dict(ref) for ref in row.source_refs], context
        )

    async def refresh_source_state(
        self, item_id: uuid.UUID, user_id: uuid.UUID
    ) -> CvSynthItem:
        """Mark a stale variant reviewed: re-snapshot source hashes.

        Plan 102's "Reset": the user judged the text still right after a
        source change — payload untouched, staleness recomputed from the
        fresh snapshots (clears unless the source moved again)."""
        row = await self.get_owned(item_id, user_id)
        await self._refresh_source_state(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete(self, item_id: uuid.UUID, user_id: uuid.UUID) -> None:
        row = await self.get_owned(item_id, user_id)
        cvs = await self.db.execute(
            select(CvDocument).where(
                CvDocument.user_id == user_id,
                CvDocument.context.isnot(None),
            )
        )
        self._strip_pins(cvs.scalars().all(), {str(item_id)})
        await self.db.delete(row)
        await self.db.commit()

    async def pin_single(
        self,
        cv: CvDocument,
        user_id: uuid.UUID,
        source_key: str,
        item_id: str,
        synth_id: Optional[str],
    ) -> CvDocument:
        """Star (or unstar) ONE item's variant on one CV.

        A surgical read-modify-write of `context.synth_pins` — never a
        whole-map replace, so concurrent writers cannot erase each
        other's stars. Pinning promotes a draft to active (plan 102:
        the star IS the approval); archived rows refuse. Returns the
        refreshed CV document."""
        if ":" in item_id:
            raise ValidationError(f"malformed item id: {item_id!r}")
        key = f"{source_key}:{item_id}"
        context = dict(cv.context or {})
        pins = dict(context.get("synth_pins") or {})
        if synth_id:
            try:
                row_id = uuid.UUID(synth_id)
            except ValueError as exc:
                raise ValidationError(f"malformed variant id: {synth_id!r}") from exc
            row = await self.get_owned(row_id, user_id)
            if row.status == CvSynthStatus.ARCHIVED.value:
                raise ValidationError(
                    "archived variants cannot be pinned — restore the row first"
                )
            if row.status == CvSynthStatus.DRAFT.value:
                row.status = CvSynthStatus.ACTIVE.value
            pins[key] = str(row.id)
        else:
            pins.pop(key, None)
            pins.pop(key + BULLETS_PIN_SUFFIX, None)
        context["synth_pins"] = pins
        cv.context = context
        await self.db.commit()
        await self.db.refresh(cv)
        return cv

    async def bulk(
        self,
        user_id: uuid.UUID,
        ids: list[uuid.UUID],
        action: str,
    ) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        """Archive / restore / delete many rows in one committed call.

        Library hygiene across mods: archive also strips any star
        (``synth_pins``) pointing at the archived ids so the slot star
        doesn't dangle on a retired row, unarchive activates through
        the same supersede path as single-row activation, delete pops
        the stars before the rows go. Unknown ids fail with the full
        offending list (a bulk call is one atomic decision, never a
        partial one). Returns (affected, deleted).
        """
        if action not in ("archive", "unarchive", "delete"):
            raise ValidationError(f"Unknown bulk action: {action!r}")
        rows = await self.db.execute(
            select(CvSynthItem).where(
                CvSynthItem.user_id == user_id, CvSynthItem.id.in_(ids)
            )
        )
        found = list(rows.scalars().all())
        known_ids = {row.id for row in found}
        missing = [str(item_id) for item_id in ids if item_id not in known_ids]
        if missing:
            raise ValidationError(
                f"Unknown variant id(s): {', '.join(missing[:5])}"
                + ("…" if len(missing) > 5 else "")
            )
        id_set = {str(item_id) for item_id in ids}
        affected: list[uuid.UUID] = []
        deleted: list[uuid.UUID] = []
        cvs = await self.db.execute(
            select(CvDocument).where(
                CvDocument.user_id == user_id,
                CvDocument.context.isnot(None),
            )
        )
        cv_rows = cvs.scalars().all()
        if action == "archive":
            for row in found:
                if row.status == CvSynthStatus.ARCHIVED.value:
                    continue
                row.status = CvSynthStatus.ARCHIVED.value
                affected.append(row.id)
            if affected:
                self._strip_pins(cv_rows, {str(i) for i in affected})
        elif action == "unarchive":
            # Back to draft — restoring N rows of one slot must NOT
            # cascade-supersede each other (a loop of activations would
            # archive all but the newest). Draft is the safe restore
            # state; the single-slot star flow promotes from there.
            for row in found:
                if row.status == CvSynthStatus.ARCHIVED.value:
                    row.status = CvSynthStatus.DRAFT.value
                    affected.append(row.id)
        else:
            for cv in cv_rows:
                self._strip_pins([cv], id_set)
            for row in found:
                await self.db.delete(row)
            deleted = list(ids)
        await self.db.commit()
        return affected, deleted

    @staticmethod
    def _strip_pins(cv_rows, doomed: set[str]) -> None:
        """Drop `synth_pins` keys whose star points at a doomed row id."""
        for cv in cv_rows:
            pins = (cv.context or {}).get("synth_pins")
            if not isinstance(pins, dict) or not pins:
                continue
            keep = {
                key: value for key, value in pins.items() if str(value) not in doomed
            }
            if len(keep) != len(pins):
                (cv.context or {})["synth_pins"] = keep
                flag_modified(cv, "context")

    async def mark_used(self, ids: list[uuid.UUID]) -> None:
        """Stamp `last_used_at` on the applying rows (resolver hook)."""
        if not ids:
            return
        rows = await self.db.execute(
            select(CvSynthItem).where(CvSynthItem.id.in_(list(ids)))
        )
        for row in rows.scalars().all():
            row.last_used_at = _now()
        await self.db.commit()

    async def pin_variants_on_cv(
        self, user_id: uuid.UUID, cv_id: uuid.UUID, rows: list[CvSynthItem]
    ) -> bool:
        """Auto-star freshly activated variants on one owned CV.

        Approve-and-pin semantics (plan-104 follow-up): the pairing is
        the proposing CV, so accepting the card saves the rows in the
        library AND puts them live on that CV in one gesture. The pin
        key is the single-slot per-item key; the rest of the context
        selection (mode/include/exclude) is preserved; unpin reverts.
        No-op when the CV is not owned or the rows carry no refs.
        """
        if not rows or cv_id is None:
            return False
        from app.schemas.cv import CvContextSelection, CvDocumentUpdate
        from app.services.cv_service import CvService

        owned = await self.db.execute(
            select(CvDocument).where(
                CvDocument.user_id == user_id, CvDocument.id == cv_id
            )
        )
        cv = owned.scalars().first()
        if cv is None:
            return False
        selection = CvContextSelection.model_validate(cv.context or {})
        pins = dict(selection.synth_pins)
        for row in rows:
            for ref in row.source_refs or []:
                key = f"{ref['source_key']}:{ref['item_id']}"
                if key.endswith(BULLETS_PIN_SUFFIX):
                    key = key[: -len(BULLETS_PIN_SUFFIX)]
                pins[key] = str(row.id)
        await CvService(self.db).update(
            cv.id,
            user_id,
            CvDocumentUpdate(
                context=CvContextSelection(
                    mode=selection.mode,
                    include=selection.include,
                    exclude=selection.exclude,
                    synth_pins=pins,
                )
            ),
        )
        await self.mark_used([row.id for row in rows])
        return True

    # ------------------------- AI generation -------------------------

    async def generate(
        self,
        user_id: uuid.UUID,
        request: CvSynthItemGenerate,
        *,
        run: Optional[RunRef] = None,
        base_texts: Optional[dict[tuple[str, str], str]] = None,
    ) -> list[CvSynthItem]:
        """One CV_SYNTH run → AI draft rows (verified, committed audit).

        Evidence = exactly the requested refs; `posting_fit` additionally
        receives the posting's must-have skills. `translate` runs off an
        existing master variant (`translate_of`): the master's payload is
        translated (tailoring carries over) while the new row keeps the
        master's source refs + fresh source hashes. AI items must cite
        the request's refs — anything out of the allowlist is dropped.
        `base_texts` optionally replaces a ref's evidence description
        with the caller's current text (the polish loop grounds its
        compaction restyles from the CV's rendered text, not the raw
        profile text), keeping prior tailoring across rounds. Commits
        before returning (ai_generations audit rule)."""
        from app.ai.agents.cv_synthetizer import synthesize

        if request.action == "translate":
            return await self.generate_translation(user_id, request, run=run)
        refs = [
            {"source_key": ref.source_key, "item_id": ref.item_id}
            for ref in request.refs
        ]
        _validate_refs(refs)
        variant_key = request.variant_key or "default"
        context = await _context_index(self.db, user_id)
        missing = [ref for ref in refs if _ref_tuple(ref) not in context]
        if missing:
            raise ValidationError(
                "Refs not in the user's context: "
                + ", ".join(f"{r['source_key']}:{r['item_id']}" for r in missing)
            )
        posting_brief = None
        if request.posting_id is not None:
            posting_brief = await self._posting_brief(
                user_id, request.posting_id, request.action
            )
        evidence = [_evidence_entry(context, ref) for ref in refs]
        for index, ref in enumerate(refs):
            base = (base_texts or {}).get(_ref_tuple(ref))
            if base:
                entry = evidence[index]
                entry["payload"] = {
                    **(entry.get("payload") or {}),
                    "description": base,
                }
        language = (request.language or "en").strip().lower()[:10]
        if not (2 <= len(language) <= 10):
            raise ValidationError("Invalid language code")
        batch = await synthesize(
            self.db,
            user_id,
            action=request.action,
            evidence=evidence,
            targets=evidence,
            posting=posting_brief,
            language=language,
            target_language=request.target_language,
            tone=request.tone,
            length=request.length,
            instruction=request.instruction,
            run=run,
        )
        rows = await self._persist_batch(
            user_id,
            request,
            batch,
            refs,
            context,
            language=language,
            variant_key=variant_key,
        )
        return rows

    async def generate_translation(
        self,
        user_id: uuid.UUID,
        request: CvSynthItemGenerate,
        *,
        run: Optional[RunRef] = None,
    ) -> list[CvSynthItem]:
        """Translate an existing master variant into the target language.

        The master's refs + variant carry over; only `voice.language`
        differs. Draft-then-approve applies like every variant."""
        from app.ai.agents.cv_synthetizer import synthesize

        master = await self.get_owned(request.translate_of, user_id)
        if request.target_language is None:
            raise ValidationError("Translate needs target_language")
        target = request.target_language.strip().lower()[:10]
        if not (2 <= len(target) <= 10):
            raise ValidationError("Invalid target language")
        if not target or master.voice.get("language") == target:
            raise ValidationError("Target language equals the master's language")
        refs = [dict(ref) for ref in master.source_refs]
        _validate_refs(refs)
        context = await _context_index(self.db, user_id)
        texts: dict[str, str] = {}
        for ref in refs:
            key = _ref_tuple(ref)
            texts[f"{key[0]}:{key[1]}"] = self._variant_text_for(master, key)
        evidence = [_evidence_entry(context, ref) for ref in refs]
        batch = await synthesize(
            self.db,
            user_id,
            action="translate",
            evidence=evidence,
            targets=evidence,
            language=master.voice.get("language") or "en",
            target_language=request.target_language,
            variant_texts=texts,
            tone=request.tone,
            length=request.length,
            instruction=request.instruction,
            run=run,
        )
        rows = await self._persist_batch(
            user_id, request, batch, refs, context, language=target
        )
        return rows

    @staticmethod
    def _variant_text_for(row: CvSynthItem, ref: tuple[str, str]) -> str:
        """The master text to translate: its description/summary/bullets."""
        payload = row.payload or {}
        text = payload.get("description") or payload.get("summary") or ""
        if not text and payload.get("achievements"):
            text = "\n".join(
                str(entry.get("text") or "") for entry in payload["achievements"]
            )
        return text or ""

    async def regenerate(
        self, user_id: uuid.UUID, item_id: uuid.UUID
    ) -> list[CvSynthItem]:
        """Re-run a stored AI variant's exact params → a fresh draft."""
        row = await self.get_owned(item_id, user_id)
        if row.source != CvSynthSource.AI.value:
            raise ValidationError("Manual variants have no stored params to rerun")
        action = str(row.voice.get("action") or "summarize")
        request = CvSynthItemGenerate(
            refs=[
                {"source_key": ref["source_key"], "item_id": ref["item_id"]}
                for ref in row.source_refs
            ],
            action=action,
            tone=row.voice.get("tone"),
            length=row.voice.get("length"),
            instruction=row.voice.get("instruction"),
            language=row.voice.get("language") or "en",
            target_language=row.voice.get("language")
            if action == "translate"
            else None,
            translate_of=uuid.UUID(str(row.voice["translate_of"]))
            if action == "translate" and row.voice.get("translate_of")
            else (row.id if action == "translate" else None),
            posting_id=row.target_posting_id,
            variant_key=row.variant_key,
        )
        rows = await self.generate(user_id, request)
        return rows

    async def _posting_brief(
        self, user_id: uuid.UUID, posting_id: uuid.UUID, action: str
    ) -> dict:
        """The posting digest the prompt sees (tailor pattern)."""
        from app.ai.agents.posting_extractor import PostingExtract
        from app.models.posting_model import JobPosting

        posting = (
            (
                await self.db.execute(
                    select(JobPosting).where(JobPosting.id == posting_id)
                )
            )
            .scalars()
            .first()
        )
        if posting is None:
            raise NotFoundError("Posting not found")
        if action == "posting_fit":
            if not posting.extract:
                raise ValidationError(
                    "The posting has no deep extraction yet — run the extract first"
                )
            extract = PostingExtract.model_validate(posting.extract)
            return {
                "title": extract.title_norm or posting.title,
                "must_have_skills": [
                    skill.skill_key
                    for skill in extract.skills
                    if skill.priority == "must_have"
                ],
                "text": _posting_text(posting),
            }
        return {
            "title": posting.title,
            "must_have_skills": [],
            "text": _posting_text(posting),
        }

    async def _persist_batch(
        self,
        user_id: uuid.UUID,
        request: CvSynthItemGenerate,
        batch,
        refs: list[dict],
        context: dict[tuple[str, str], dict],
        *,
        language: str,
        variant_key: str | None = None,
    ) -> list[CvSynthItem]:
        """Verified draft persistence for one batch (the honesty gate).

        The model's echoed refs drive attribution; an out-of-allowlist
        citation is cut — an in-allowlist subset persists, a single-ref
        request falls back to the authoritative request refs (the draft
        text was grounded on exactly that evidence), and a multi-ref
        request with no usable citation is dropped (the target is
        ambiguous)."""
        allowlist = {_ref_tuple(ref) for ref in refs}
        request_refs = [_ref_tuple(ref) for ref in refs]
        fallback = request_refs if len(allowlist) == 1 else None
        created: list[CvSynthItem] = []
        for item in batch.items:
            listed = [(str(r.source_key), str(r.item_id)) for r in item.refs]
            cited = list(dict.fromkeys(listed))
            cited_valid = [ref for ref in cited if ref in allowlist]
            if cited_valid:
                refs_out = _refs_dump(cited_valid)
            elif fallback is not None:
                refs_out = _refs_dump(fallback)
            else:
                continue
            final_refs = [_ref_tuple(ref) for ref in refs_out]
            payload = item.payload.model_dump(mode="json")
            if (
                not payload.get("description")
                and not payload.get("summary")
                and not payload.get("achievements")
            ):
                continue
            evidence_refs = [
                {"source_key": str(r.source_key), "item_id": str(r.item_id)}
                for r in item.evidence_refs
                if (str(r.source_key), str(r.item_id)) in allowlist
            ]
            row = CvSynthItem(
                user_id=user_id,
                scope=request.scope,
                variant_key=variant_key or (request.variant_key or "default"),
                target_posting_id=request.posting_id,
                source_refs=refs_out,
                source_state=_source_state_of(refs_out, context),
                source_set_hash=_set_hash(refs_out),
                payload=payload,
                evidence_refs=evidence_refs,
                voice={
                    "language": language,
                    "tone": request.tone,
                    "length": request.length,
                    "action": request.action,
                    "instruction": request.instruction,
                    "translate_of": str(request.translate_of)
                    if request.translate_of
                    else None,
                },
                status=CvSynthStatus.DRAFT.value,
                source=CvSynthSource.AI.value,
                verified=bool(evidence_refs)
                and all(ref in allowlist for ref in final_refs),
            )
            self.db.add(row)
            created.append(row)
        if created:
            await self.db.commit()
            for row in created:
                await self.db.refresh(row)
        return created

    # ------------------------- resolution + matching -------------------------

    async def match_for_cv(
        self, cv, refs: list[tuple[str, str]] | None = None
    ) -> dict[tuple[str, str], CvSynthItem]:
        """Per ref, the applying variant for this CV (deterministic).

        Delegates to `match_for_user` with the CV's match context
        (plan 69: generation matches before any CvDocument exists)."""
        return await self.match_for_user(
            cv.user_id, cv.language, cv.target_posting_id, refs
        )

    async def pin_overlay_snapshot(
        self,
        user_id: uuid.UUID,
        language: str,
        target_posting_id: Optional[uuid.UUID],
        pins: dict,
        snapshot: dict,
        snapshot_index: dict[str, list[str]],
    ) -> None:
        """Re-assert the user's stars AFTER the override layer.

        Layer precedence is `pin > override > source` (plan 110 follow-up):
        the star is the most explicit user decision — an older captured
        override must not mute the pinned variant's own text (the exact
        "pinned variant shows only its bullets" bug when an older
        override still owned the description). Fields the row does not
        carry stay with the override/source layers.
        Mutates ``snapshot`` rows in place; called per render, never
        stored."""
        if not pins or not snapshot:
            return
        normalized: dict[str, str] = {}
        for key, value in pins.items():
            if key.endswith(BULLETS_PIN_SUFFIX):
                key = key[: -len(BULLETS_PIN_SUFFIX)]
            if value:
                normalized[str(key)] = str(value)
        if not normalized:
            return
        ref_keys: list[tuple[str, str]] = []
        for source_key, ids in snapshot_index.items():
            key = "summary" if source_key == "summary" else source_key
            for item_id in ids:
                ref_keys.append((key, item_id))
        matches = await self.match_for_user(
            user_id,
            language,
            target_posting_id,
            refs=ref_keys,
            pins=normalized,
        )
        matches = {
            ref: variant
            for ref, variant in matches.items()
            if str(normalized.get(f"{ref[0]}:{ref[1]}", "")) == str(variant.id)
        }
        for (source_key, item_id), variant in matches.items():
            index = snapshot_index.get(source_key) or []
            rows = snapshot.get(source_key)
            if isinstance(rows, dict):
                swap_variant_payload(rows, (source_key, item_id), variant)
            elif isinstance(rows, list):
                for position, existing in enumerate(index):
                    if existing == item_id and position < len(rows):
                        swap_variant_payload(
                            rows[position], (source_key, item_id), variant
                        )

    async def match_for_user(
        self,
        user_id: uuid.UUID,
        language: str,
        target_posting_id: Optional[uuid.UUID],
        refs: list[tuple[str, str]] | None = None,
        pins: dict | None = None,
    ) -> dict[tuple[str, str], CvSynthItem]:
        """Per ref, the applying variant for a match context (deterministic).

        Precedence: a per-ref pin (plan 72 follow-up, `{ref_key:
        synth_id}`, active rows only) beats everything, then active →
        `voice.language` == `language` → posting-scoped (only this
        target posting) beats generic → `variant_key` "default" first,
        then newest-first.
        """
        if refs is None:
            return {}
        if not refs:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(CvSynthItem).where(
                        CvSynthItem.user_id == user_id,
                        CvSynthItem.status == CvSynthStatus.ACTIVE.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_ref: dict[tuple[str, str], list[CvSynthItem]] = {}
        for row in rows:
            for ref in row.source_refs:
                by_ref.setdefault(_ref_tuple(ref), []).append(row)
        keys = {_ref_tuple(r) if isinstance(r, dict) else r for r in refs}
        applying: dict[tuple[str, str], CvSynthItem] = {}
        for ref in keys:
            pinned = str(pins.get(f"{ref[0]}:{ref[1]}", "")) if pins else ""
            if pinned:
                pinned_row = next((row for row in rows if str(row.id) == pinned), None)
                if pinned_row is not None:
                    if (
                        pinned_row.target_posting_id
                        in (
                            None,
                            target_posting_id,
                        )
                        and pinned_row.voice.get("language") == language
                    ):
                        applying[ref] = pinned_row
                        continue
            candidates = [
                r for r in by_ref.get(ref, []) if r.voice.get("language") == language
            ]
            scoped = [
                r
                for r in candidates
                if r.target_posting_id is not None
                and r.target_posting_id == target_posting_id
            ]
            generic = [r for r in candidates if r.target_posting_id is None]
            pool = scoped or generic
            if not pool:
                continue
            pool.sort(
                key=lambda r: (
                    r.variant_key != "default",
                    -r.created_at.timestamp(),
                    str(r.id),
                )
            )
            applying[ref] = pool[0]
        return applying

    # ------------------------- resolution overlay -------------------------

    async def apply_to_resolution(
        self, cv, resolution, pins: dict | None = None
    ) -> dict:
        """Per-item overlay for a stored CV; delegates to `apply_to_items`."""
        return await self.apply_to_items(
            cv.user_id,
            cv.language,
            cv.target_posting_id,
            resolution,
            pins=pins,
        )

    async def apply_to_items(
        self,
        user_id: uuid.UUID,
        language: str,
        target_posting_id: Optional[uuid.UUID],
        resolution,
        pins: dict | None = None,
    ) -> dict:
        """Overlay: swap each pinned variant's PRESENT fields into the
        snapshot (plan 110 AD1/AD3b: ONE pin slot per item,
        `"{source}:{id}"` — a row applies what its payload carries, so
        text and bullets compose on one starred row; matches are
        scope-agnostic). Legacy `"{source}:{id}:bullets"` keys from
        pre-110 versions are read with tolerance and folded into the
        single slot here — write paths emit ONLY the single form.
        Precedence `override > synth > source` holds because the
        editor's `apply_overrides` runs AFTER this (the builder calls
        it in `render_state`), so a manual field patch always wins.
        Returns the `synth_applied` trace map (`{ref_key: synth_id}`)
        recorded into `CvVersion` `context_resolution` at compile."""
        if not pins:
            return {}
        normalized: dict[str, str] = {}
        for key, value in pins.items():
            if key.endswith(BULLETS_PIN_SUFFIX):
                key = key[: -len(BULLETS_PIN_SUFFIX)]
            if value:
                normalized[key] = value
        applied: dict[str, str] = {}
        ref_by_id: dict[str, str] = {}
        for key, ids in resolution.snapshot_index.items():
            for item_id in ids:
                ref_by_id.setdefault(item_id, key)
        if normalized:
            matches = await self.match_for_user(
                user_id,
                language,
                target_posting_id,
                refs=[(key, item_id) for item_id, key in ref_by_id.items()],
                pins=normalized,
            )
            matches = {
                ref: variant
                for ref, variant in matches.items()
                if str(normalized.get(f"{ref[0]}:{ref[1]}", "")) == str(variant.id)
            }
            for (source_key, item_id), variant in matches.items():
                self._swap_ref(resolution, source_key, item_id, variant)
                applied[f"{source_key}:{item_id}"] = str(variant.id)
            if matches:
                await self.mark_used([variant.id for variant in matches.values()])
        return applied

    @staticmethod
    def _swap_ref(resolution, source_key: str, item_id: str, variant) -> None:
        """Swap one variant into its resolution item + snapshot rows."""
        ref = (source_key, item_id)
        for item in resolution.items:
            if item.item_id == item_id:
                swap_variant_payload(item.payload, ref, variant)
        index = resolution.snapshot_index.get(source_key) or []
        rows = resolution.snapshot.get(source_key)
        if isinstance(rows, dict):
            swap_variant_payload(rows, ref, variant)
        else:
            for position, existing in enumerate(index or []):
                if existing == item_id and position < len(rows):
                    swap_variant_payload(rows[position], ref, variant)
