"""Gateway: every AI call goes through ``ainvoke_structured``.

Outputs are always validated into a pydantic schema. The ``mock`` provider
produces deterministic schema-aware outputs so the full app runs offline and
tests stay hermetic.
"""

import asyncio
import base64
import httpx
import json
import logging
import random
import re
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_models import build_chat_model
from app.core.config import settings
from app.core.errors import AINotConfiguredError
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType

if TYPE_CHECKING:
    from app.ai.providers.resolution import ResolvedModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MOCK_FIXTURES: dict[str, Callable[[Any, str], dict]] = {}


class RunRef(BaseModel):
    """Opt-in run linkage for multi-step flows: the audit row records
    which background run (and which stage of it) a call served. Plain
    columns, no FK — the ledger outlives the run."""

    id: uuid.UUID = Field(..., description="The run id (e.g. background job id)")
    stage: str = Field(..., description="Stage label, e.g. 'cv_draft.plan'")


def register_mock_fixture(
    task: AITaskType, builder: Callable[[type[T], str], dict]
) -> None:
    """Register a deterministic mock output builder for a task type."""
    MOCK_FIXTURES[task.value] = builder


def _extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from a model reply."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


class StructuredAIError(Exception):
    """Raised when the model cannot produce a schema-valid output."""


def _message_text(message: BaseMessage) -> str:
    """The plain text of a LangChain message (str or text content blocks)."""
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                value = block.get("text")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return ""


def _schema_hint(schema: type[BaseModel]) -> str:
    """The system-prompt suffix asking for schema-conforming JSON."""
    return json.dumps(schema.model_json_schema(), ensure_ascii=False)


async def _invoke_model(
    schema: type[T],
    system: str,
    user: str,
    resolved: "ResolvedModel",
    images: Optional[list[tuple[str, bytes]]] = None,
) -> tuple[T, Optional[int], Optional[int]]:
    """Call the resolved model through the LangChain factory and validate.

    `images` are (mime, bytes) parts appended to the user message as
    base64 data URLs — the vision path used by OCR-style tasks.
    """
    content: str | list[str | dict[str, Any]] = user
    if images:
        parts: list[str | dict[str, Any]] = [{"type": "text", "text": user}]
        for mime, data in images:
            encoded = base64.b64encode(data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                }
            )
        content = parts
    model = build_chat_model(resolved)
    message = await model.ainvoke(
        [
            SystemMessage(
                content=f"{system}\n\nReply with JSON matching this schema:\n{_schema_hint(schema)}"
            ),
            HumanMessage(content=content),
        ]
    )
    usage: dict[str, Any] = dict(message.usage_metadata or {})
    return (
        schema.model_validate(_extract_json(_message_text(message))),
        usage.get("input_tokens"),
        usage.get("output_tokens"),
    )


def _mock_output(schema: type[T], task: AITaskType, user: str) -> T:
    """Build a deterministic mock output for the given schema."""
    builder = MOCK_FIXTURES.get(task.value)
    data = builder(schema, user) if builder else _generic_mock(schema)
    return schema.model_validate(data)


def _generic_mock(schema: type[BaseModel]) -> dict:
    """Minimal schema-shaped dict satisfying required primitive fields."""
    js = schema.model_json_schema()
    defs = js.get("$defs", {})

    def resolve(ref: str) -> dict:
        return defs.get(ref.split("/")[-1], {})

    def fill(node: dict) -> dict:
        out: dict = {}
        props = node.get("properties", {})
        for name in node.get("required", []):
            prop = props.get(name, {})
            if "$ref" in prop:
                target = resolve(prop["$ref"])
                if target.get("enum"):
                    out[name] = target["enum"][0]
                else:
                    out[name] = fill(target)
                continue
            if prop.get("anyOf"):
                branch = prop["anyOf"][0]
                if "$ref" in branch:
                    target = resolve(branch["$ref"])
                    out[name] = (
                        target["enum"][0] if target.get("enum") else fill(target)
                    )
                    continue
                enum = branch.get("enum")
                if enum:
                    out[name] = enum[0]
                    continue
            ptype = prop.get("type")
            if ptype == "array":
                items = prop.get("items", {})
                if "$ref" in items:
                    target = resolve(items["$ref"])
                    if target.get("enum"):
                        out[name] = [target["enum"][0]]
                    else:
                        out[name] = [fill(target)]
                else:
                    out[name] = []
            elif ptype == "object":
                out[name] = fill(prop)
            elif ptype == "integer":
                out[name] = (
                    prop.get("minimum") if prop.get("minimum") is not None else 1
                )
            elif ptype == "number":
                out[name] = (
                    prop.get("maximum") if prop.get("maximum") is not None else 5
                )
            elif ptype == "boolean":
                out[name] = True
            else:
                enum = prop.get("enum")
                out[name] = enum[0] if enum else f"mock_{name}"
        return out

    return fill(js)


async def _record(
    db: AsyncSession,
    user_id,
    task: AITaskType,
    model: str,
    prompt: str,
    output: Optional[dict],
    tokens_in: Optional[int],
    tokens_out: Optional[int],
    latency_ms: float,
    status: str,
    error: str = "",
    provider_type: Optional[str] = None,
    model_name: Optional[str] = None,
    pack_key: Optional[str] = None,
    pack_version: Optional[int] = None,
    run_id: Optional[uuid.UUID] = None,
    run_stage: Optional[str] = None,
) -> AIGeneration:
    """Persist an audit row for one AI call (the row is returned so the
    `with_audit_ref` opt-in can hand back exactly what was written)."""
    from app.ai.prompt_versions import prompt_version
    from app.ai.tasks import task_tier

    row = AIGeneration(
        user_id=user_id,
        task_type=task.value,
        provider=provider_type or "unknown",
        model=model_name or model,
        prompt=prompt[:4000],
        output=output,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        status=status,
        error=error[:1000],
        task_tier=task_tier(task.value),
        prompt_version=prompt_version(task.value),
        pack_key=pack_key,
        pack_version=pack_version,
        run_id=run_id,
        run_stage=run_stage,
    )
    db.add(row)
    await db.flush()
    return row


def _audit_ref(row: AIGeneration) -> dict:
    """The compact per-call summary flipped on by `with_audit_ref` —
    exactly the fields `_record` just wrote, no second read."""
    return {
        "id": str(row.id),
        "task_type": row.task_type,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "latency_ms": int(row.latency_ms) if row.latency_ms is not None else None,
    }


async def ainvoke_structured(
    db: AsyncSession,
    task: AITaskType,
    schema: type[T],
    system: str,
    user: str,
    user_id=None,
    images: Optional[list[tuple[str, bytes]]] = None,
    run: Optional[RunRef] = None,
    with_audit_ref: bool = False,
) -> "T | tuple[T, dict]":
    """Run an AI task and return a schema-validated result (audited).

    The provider/model is resolved per (task, user) from the database:
    user assignment > system assignment > "default" assignment. Raises
    ``AINotConfiguredError`` when nothing is configured (or a mock provider
    is resolved in production) and ``StructuredAIError`` when no valid
    output can be produced; failures are recorded in ``ai_generations``.
    ``images`` (mime, bytes) adds vision content parts; the mock provider
    ignores them and builds deterministic output from the prompt context.
    ``run`` optionally links the audit row to a multi-step flow run and
    stage; absent (the default) the row's run columns stay NULL exactly
    as every single-call path today. ``with_audit_ref`` opt-in changes
    the return to ``(value, audit_ref)`` where ``audit_ref`` is the
    compact summary of the audit row just written (id, task, tokens,
    latency) — read back in the same transaction, no second SELECT.
    """
    from app.ai.providers.resolution import resolve_task_model

    if user_id is not None and settings.AI_RATE_LIMIT > 0:
        from app.core.errors import DomainError
        from app.core.ratelimit import limiter

        retry_after = limiter.check("ai", f"user:{user_id}")
        if retry_after is not None:
            raise DomainError(f"AI rate limit reached; retry in {retry_after}s")

    resolved = await resolve_task_model(db, task.value, user_id)
    run_id = run.id if run is not None else None
    run_stage = run.stage if run is not None else None
    started = time.perf_counter()
    if resolved is None:
        error = (
            "AI is not configured yet. An admin can add a provider and assign "
            "models in Settings → AI Configuration."
        )
        latency = (time.perf_counter() - started) * 1000
        await _record(
            db,
            user_id,
            task,
            "unconfigured",
            user,
            None,
            None,
            None,
            latency,
            "error",
            error,
            provider_type="none",
            run_id=run_id,
            run_stage=run_stage,
        )
        raise AINotConfiguredError(error)
    if resolved.provider_type == "mock" and settings.is_production:
        error = (
            "AI is not configured for this environment: the mock provider is "
            "dev-only. Configure a real provider in Settings → AI Configuration."
        )
        latency = (time.perf_counter() - started) * 1000
        await _record(
            db,
            user_id,
            task,
            resolved.model_name,
            user,
            None,
            None,
            None,
            latency,
            "error",
            error,
            provider_type="mock",
            run_id=run_id,
            run_stage=run_stage,
        )
        raise AINotConfiguredError(error)
    from app.ai.budgets import enforce_budgets

    await enforce_budgets(db, task, user_id)
    from app.ai.packs import compose_system, resolve_pack

    pack = await resolve_pack(db, task.value, user_id=user_id)
    effective_system = compose_system(system, pack)
    attempts = 3 if resolved.provider_type != "mock" else 1
    last_error = ""
    for attempt in range(attempts):
        try:
            if resolved.provider_type == "mock":
                await asyncio.sleep(0)
                result = _mock_output(schema, task, user)
                latency = (time.perf_counter() - started) * 1000
                row = await _record(
                    db,
                    user_id,
                    task,
                    resolved.provider_type,
                    user,
                    result.model_dump(mode="json"),
                    None,
                    None,
                    latency,
                    "ok",
                    model_name=resolved.model_name,
                    provider_type=resolved.provider_type,
                    pack_key=pack.key if pack else None,
                    pack_version=pack.version if pack else None,
                    run_id=run_id,
                    run_stage=run_stage,
                )
                return (result, _audit_ref(row)) if with_audit_ref else result
            result, tokens_in, tokens_out = await _invoke_model(
                schema,
                effective_system,
                user,
                resolved,
                images=images,
            )
            latency = (time.perf_counter() - started) * 1000
            row = await _record(
                db,
                user_id,
                task,
                resolved.model_name,
                user,
                result.model_dump(mode="json"),
                tokens_in,
                tokens_out,
                latency,
                "ok",
                provider_type=resolved.provider_type,
                pack_key=pack.key if pack else None,
                pack_version=pack.version if pack else None,
                run_id=run_id,
                run_stage=run_stage,
            )
            return (result, _audit_ref(row)) if with_audit_ref else result
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "AI task %s attempt %d failed: %s", task.value, attempt + 1, last_error
            )
            if resolved.provider_type == "mock":
                break
    latency = (time.perf_counter() - started) * 1000
    await _record(
        db,
        user_id,
        task,
        resolved.model_name,
        user,
        None,
        None,
        None,
        latency,
        "error",
        last_error,
        run_id=run_id,
        run_stage=run_stage,
    )
    raise StructuredAIError(
        f"AI task '{task.value}' failed after {attempts} attempts: {last_error}"
    )


def utcnow() -> datetime:
    """Current UTC time."""
    return datetime.now(timezone.utc)


def stable_hash(text: str) -> int:
    """Deterministic small hash used by mock fixtures for variety."""
    return random.Random(text).randint(0, 10**6)


def partial_answer_text(raw: str) -> str:
    """Extract the in-progress value of the JSON ``answer`` string field.

    Tolerant of incomplete input: returns whatever of the value has arrived
    so far (with common escapes resolved), or ``""`` before it starts.
    """
    marker = '"answer"'
    start = raw.find(marker)
    if start == -1:
        return ""
    rest = raw[start + len(marker) :]
    colon = rest.find(":")
    if colon == -1:
        return ""
    rest = rest[colon + 1 :].lstrip()
    if not rest.startswith('"'):
        return ""
    out: list[str] = []
    escaped = False
    for ch in rest[1:]:
        if escaped:
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(ch, ""))
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            break
        out.append(ch)
    return "".join(out)


class StructuredStream:
    """Streaming variant of ``ainvoke_structured`` (chat only).

    Iterate ``chunks()`` to receive raw completion text as it arrives; when
    the iterator finishes, ``reply`` holds the validated, audited result (or
    ``error``/exception carries the failure, audited like every other call).
    """

    def __init__(self) -> None:
        self.reply: Optional[BaseModel] = None
        self.error: str = ""
        self.model: Optional[str] = None
        # Usage from the last streamed chunk, when the provider reports it
        # (surfaced on the turn trace for the UI).
        self.tokens_in: Optional[int] = None
        self.tokens_out: Optional[int] = None
        self._raw: list[str] = []

    async def chunks(
        self,
        db: AsyncSession,
        task: AITaskType,
        schema: type[T],
        system: str,
        user: str,
        user_id=None,
    ):
        from app.ai.providers.resolution import resolve_task_model

        if user_id is not None and settings.AI_RATE_LIMIT > 0:
            from app.core.errors import DomainError
            from app.core.ratelimit import limiter

            retry_after = limiter.check("ai", f"user:{user_id}")
            if retry_after is not None:
                raise DomainError(f"AI rate limit reached; retry in {retry_after}s")

        resolved = await resolve_task_model(db, task.value, user_id)
        started = time.perf_counter()
        if resolved is None:
            raise AINotConfiguredError(
                "AI is not configured yet. An admin can add a provider and "
                "assign models in Settings → AI Configuration."
            )
        self.model = resolved.model_name
        if resolved.provider_type == "mock" and settings.is_production:
            raise AINotConfiguredError(
                "AI is not configured for this environment: the mock provider "
                "is dev-only. Configure a real provider in Settings → AI "
                "Configuration."
            )
        from app.ai.budgets import enforce_budgets

        await enforce_budgets(db, task, user_id)
        from app.ai.packs import compose_system, resolve_pack

        pack = await resolve_pack(db, task.value, user_id=user_id)
        effective_system = compose_system(system, pack)

        try:
            if resolved.provider_type == "mock":
                raw = json.dumps(
                    _mock_output(schema, task, user).model_dump(mode="json"),
                    ensure_ascii=False,
                )
                size = max(len(raw) // 4, 1)
                for i in range(0, len(raw), size):
                    piece = raw[i : i + size]
                    self._raw.append(piece)
                    yield piece
                    await asyncio.sleep(0)
            else:
                model = build_chat_model(resolved)
                messages = [
                    SystemMessage(
                        content=f"{effective_system}\n\nReply with JSON matching this schema:\n{_schema_hint(schema)}"
                    ),
                    HumanMessage(content=user),
                ]
                async for chunk in model.astream(messages):
                    piece = _message_text(chunk)
                    if piece:
                        self._raw.append(piece)
                        yield piece
                    usage = chunk.usage_metadata
                    if usage:
                        self.tokens_in = usage.get("input_tokens")
                        self.tokens_out = usage.get("output_tokens")

            latency = (time.perf_counter() - started) * 1000
            self.reply = schema.model_validate(_extract_json("".join(self._raw)))
            await _record(
                db,
                user_id,
                task,
                resolved.provider_type,
                user,
                self.reply.model_dump(mode="json"),
                self.tokens_in,
                self.tokens_out,
                latency,
                "ok",
                model_name=resolved.model_name,
                provider_type=resolved.provider_type,
                pack_key=pack.key if pack else None,
                pack_version=pack.version if pack else None,
            )
        except Exception as exc:  # noqa: BLE001 — failures audited, then raised
            self.error = f"{type(exc).__name__}: {exc}"
            if self.reply is None and "AINotConfigured" not in self.error:
                latency = (time.perf_counter() - started) * 1000
                await _record(
                    db,
                    user_id,
                    task,
                    resolved.provider_type,
                    user,
                    None,
                    None,
                    None,
                    latency,
                    "error",
                    self.error,
                    provider_type=resolved.provider_type,
                )
            raise


MOCK_EMBED_DIM = 64


def _mock_embedding(text: str) -> list[float]:
    """Deterministic pseudo-vector from the text hash — stable across
    runs so cosine ranking is testable without a provider."""
    import hashlib
    import math

    seed = hashlib.sha256(text.encode("utf-8")).digest()
    vector = []
    for i in range(MOCK_EMBED_DIM):
        byte = seed[i % len(seed)]
        vector.append(math.sin(byte + i * 0.37) * 0.5)
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 6) for v in vector]


async def embed_texts(
    db: AsyncSession,
    texts: list[str],
    user_id=None,
) -> list[list[float]]:
    """Embed a batch of texts via the ``embed`` task.

    Same funnel as every gateway call: rate limit, resolve (503 when
    unassigned), budgets, audit. The mock provider synthesizes
    deterministic unit vectors (dim ``MOCK_EMBED_DIM``) so ranking is
    testable without a provider; real providers go through the
    embeddings model factory.
    """
    from app.ai.providers.resolution import resolve_task_model

    if user_id is not None and settings.AI_RATE_LIMIT > 0:
        from app.core.errors import DomainError
        from app.core.ratelimit import limiter

        retry_after = limiter.check("ai", f"user:{user_id}")
        if retry_after is not None:
            raise DomainError(f"AI rate limit reached; retry in {retry_after}s")

    resolved = await resolve_task_model(db, AITaskType.EMBED.value, user_id)
    started = time.perf_counter()
    if resolved is None:
        error = (
            "AI is not configured yet. An admin can add a provider and assign "
            "models in Settings → AI Configuration."
        )
        latency = (time.perf_counter() - started) * 1000
        await _record(
            db,
            user_id,
            AITaskType.EMBED,
            "unconfigured",
            f"embed {len(texts)} text(s)",
            None,
            None,
            None,
            latency,
            "error",
            error,
            provider_type="none",
        )
        raise AINotConfiguredError(error)
    if resolved.provider_type == "mock" and settings.is_production:
        raise AINotConfiguredError(
            "AI is not configured for this environment: the mock provider is "
            "dev-only. Configure a real provider in Settings → AI Configuration."
        )
    from app.ai.budgets import enforce_budgets

    await enforce_budgets(db, AITaskType.EMBED, user_id)
    try:
        if resolved.provider_type == "mock":
            vectors = [_mock_embedding(text) for text in texts]
        else:
            from app.ai.chat_models import build_embedding_model

            model = build_embedding_model(resolved)
            vectors = [list(map(float, v)) for v in await model.aembed_documents(texts)]
        latency = (time.perf_counter() - started) * 1000
        await _record(
            db,
            user_id,
            AITaskType.EMBED,
            resolved.provider_type,
            f"embed {len(texts)} text(s), dim {len(vectors[0]) if vectors else 0}",
            {"count": len(vectors), "dim": len(vectors[0]) if vectors else 0},
            None,
            None,
            latency,
            "ok",
            model_name=resolved.model_name,
            provider_type=resolved.provider_type,
        )
        return vectors
    except Exception as exc:
        latency = (time.perf_counter() - started) * 1000
        await _record(
            db,
            user_id,
            AITaskType.EMBED,
            resolved.model_name,
            f"embed {len(texts)} text(s)",
            None,
            None,
            None,
            latency,
            "error",
            f"{type(exc).__name__}: {exc}",
        )
        raise


async def transcribe_audio(
    db: AsyncSession,
    *,
    user_id=None,
    data: bytes,
    mime: str,
    language: Optional[str] = None,
) -> tuple[str, str]:
    """Speech-to-text for dictation. Resolves the
    ``transcribe`` task like every gateway call (budget, rate limit,
    audit), then uses the provider's audio API — audio is not a
    LangChain chat capability. Returns ``(text, model_name)``."""
    from app.ai.providers.resolution import resolve_task_model
    from app.ai.transcribe import transcribe_with

    if user_id is not None and settings.AI_RATE_LIMIT > 0:
        from app.core.errors import DomainError
        from app.core.ratelimit import limiter

        retry_after = limiter.check("ai", f"user:{user_id}")
        if retry_after is not None:
            raise DomainError(f"AI rate limit reached; retry in {retry_after}s")

    resolved = await resolve_task_model(db, AITaskType.TRANSCRIBE.value, user_id)
    started = time.perf_counter()
    if resolved is None:
        raise AINotConfiguredError(
            "AI is not configured yet. An admin can add a provider and "
            "assign models in Settings → AI Configuration."
        )
    if resolved.provider_type == "mock" and settings.is_production:
        raise AINotConfiguredError(
            "AI is not configured for this environment: the mock provider "
            "is dev-only. Configure a real provider in Settings → AI "
            "Configuration."
        )
    from app.ai.budgets import enforce_budgets

    await enforce_budgets(db, AITaskType.TRANSCRIBE, user_id)

    status = "ok"
    error = ""
    text = ""
    try:
        if resolved.provider_type == "mock":
            text = "Mock transcription of your recording."
        else:
            with httpx.Client(timeout=60) as client:
                text = await asyncio.to_thread(
                    transcribe_with, client, resolved, data, mime, language
                )
    except Exception as exc:  # noqa: BLE001 — failures audited, then raised
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        latency = (time.perf_counter() - started) * 1000
        await _record(
            db,
            user_id,
            AITaskType.TRANSCRIBE,
            resolved.provider_type,
            f"[audio {mime} {len(data)} bytes]",
            {"text": text} if status == "ok" else None,
            None,
            None,
            latency,
            status,
            error,
            provider_type=resolved.provider_type,
            model_name=resolved.model_name,
        )
        # Unlike the chat flow (a service commit follows the audit flush),
        # transcription has no downstream writer — commit the audit here.
        await db.commit()
    return text, resolved.model_name
