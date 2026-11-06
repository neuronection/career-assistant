"""Gateway: every AI call goes through ``ainvoke_structured``.

Outputs are always validated into a pydantic schema. The ``mock`` provider
produces deterministic schema-aware outputs so the full app runs offline and
tests stay hermetic.
"""

import asyncio
import base64
import json
import logging
import random
import re
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload

import httpx
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_models import build_chat_model
from app.core.config import settings
from app.core.errors import AINotConfiguredError, sanitize_error_detail
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType

if TYPE_CHECKING:
    from app.ai.providers.resolution import ResolvedModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MOCK_FIXTURES: dict[str, Callable[[Any, str], dict]] = {}

_MOCK_REGISTRY_LOADED = False


def ensure_mock_registry() -> None:
    """Make sure the deterministic mock fixtures are registered.

    Registration lives in ``app.ai.mock_chat`` (import side effect), but
    that module is only imported by the dev bootstrap — a pre-seeded
    mock configuration (E2E scratch DBs, older seeds) resolves without
    ever running it, which would leave CHAT/CHAT_OPS/agent-round mocks
    unregistered and the smoke suite answering with generic mocks.
    Dev/test only; production blocks the mock provider outright.
    """
    global _MOCK_REGISTRY_LOADED
    if not _MOCK_REGISTRY_LOADED:
        _MOCK_REGISTRY_LOADED = True
        import importlib

        importlib.import_module("app.ai.mock_chat")


class RunRef(BaseModel):
    """Opt-in run linkage for multi-step flows: the audit row records
    which background run (and which stage of it) a call served. Plain
    columns, no FK — the ledger outlives the run."""

    id: uuid.UUID = Field(..., description="The run id (e.g. background job id)")
    stage: str = Field(..., description="Stage label, e.g. 'cv_draft.plan'")


def register_mock_fixture[T: BaseModel](
    task: AITaskType, builder: Callable[[type[T], str], dict]
) -> None:
    """Register a deterministic mock output builder for a task type."""
    MOCK_FIXTURES[task.value] = builder


def _rebalanced_prefix(prefix: str) -> str | None:
    """Close whatever the truncated JSON prefix left open, or None.

    Minimal-only scan: track string state and the bracket stack; a cut
    is recoverable when the string state resolves (drop a volatile
    trailing backslash, close an open quote) and the stack closes
    cleanly."""
    stack: list[str] = []
    closers = {"{": "}", "[": "]"}
    in_string = escape = False
    for ch in prefix:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack or closers[stack[-1]] != ch:
                return None
            stack.pop()
    if escape:
        return None
    repaired = prefix + '"' if in_string else prefix
    if stack:
        repaired += "".join(closers[bracket] for bracket in reversed(stack))
    return repaired


def _extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from a model reply."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Prose-wrapped reply: take the widest {...} region it contains.
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            candidate = match.group(0)
        elif text.startswith("{"):
            # Unguarded truncation: the object started but never closed.
            candidate = text
        else:
            raise
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Truncated object (stream hit a length/finish cutoff): keep
            # the largest cut that still parses with auto-closures — the
            # "answer" field usually landed long before the cut. Cuts
            # walk newest-first over value boundaries only (a value end
            # or a comma), bounded so pathological input terminates.
            attempts = 0
            position = len(candidate)
            while position > 1 and attempts < 64:
                attempts += 1
                boundary = max(
                    (m.start() for m in re.finditer(r"\}|,", candidate[:position])),
                    default=0,
                )
                if boundary < 1:
                    break
                repaired = _rebalanced_prefix(candidate[:boundary])
                if repaired is not None:
                    try:
                        return json.loads(repaired)
                    except json.JSONDecodeError:
                        pass
                position = boundary
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


def _finish_reason(message: BaseMessage) -> str:
    """The provider finish reason of a reply chunk/message ('' if absent)."""
    meta = getattr(message, "response_metadata", None) or {}
    return str(meta.get("finish_reason") or "")


def _stream_failure_message(finish_reason: str) -> str:
    """User-facing failure text; names the token cap when it fired."""
    detail = "The model's reply was not usable structured output"
    if finish_reason.upper().startswith("MAX_TOKENS"):
        detail += (
            " (the reply hit the token cap — raise the model's max_tokens "
            "in Settings → AI Configuration)"
        )
    return detail + " — please retry."


def _user_content(
    user: str, images: list[tuple[str, bytes]] | None
) -> str | list[str | dict[str, Any]]:
    """The user message as sent: plain text, or text + base64 image
    parts (the vision path shared by invoke and stream)."""
    if not images:
        return user
    parts: list[str | dict[str, Any]] = [{"type": "text", "text": user}]
    for mime, data in images:
        encoded = base64.b64encode(data).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
        )
    return parts


async def _invoke_model[T: BaseModel](
    schema: type[T],
    system: str,
    user: str,
    resolved: "ResolvedModel",
    images: list[tuple[str, bytes]] | None = None,
) -> tuple[T, int | None, int | None]:
    """Call the resolved model through the LangChain factory and validate.

    `images` are (mime, bytes) parts appended to the user message as
    base64 data URLs — the vision path used by OCR-style tasks.
    """
    model = build_chat_model(resolved)
    message = await model.ainvoke(
        [
            SystemMessage(
                content=f"{system}\n\nReply with JSON matching this schema:\n{_schema_hint(schema)}"
            ),
            HumanMessage(content=_user_content(user, images)),
        ]
    )
    usage: dict[str, Any] = dict(message.usage_metadata or {})
    return (
        schema.model_validate(_extract_json(_message_text(message))),
        usage.get("input_tokens"),
        usage.get("output_tokens"),
    )


def _mock_output[T: BaseModel](schema: type[T], task: AITaskType, user: str) -> T:
    """Build a deterministic mock output for the given schema."""
    ensure_mock_registry()
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
                    out[name] = target["enum"][0] if target.get("enum") else fill(target)
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
                out[name] = prop.get("minimum") if prop.get("minimum") is not None else 1
            elif ptype == "number":
                out[name] = prop.get("maximum") if prop.get("maximum") is not None else 5
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
    output: dict | None,
    tokens_in: int | None,
    tokens_out: int | None,
    latency_ms: float,
    status: str,
    error: str = "",
    provider_type: str | None = None,
    model_name: str | None = None,
    pack_key: str | None = None,
    pack_version: int | None = None,
    run_id: uuid.UUID | None = None,
    run_stage: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AIGeneration:
    """Persist an audit row for one AI call (the row is returned so the
    `with_audit_ref` opt-in can hand back exactly what was written).

    ``metadata`` is the caller-supplied retrieval seam (plan 51 Q1a): the
    gateway stores exactly the tags it was handed (space/kind/view/chunk
    index) and never invents one. A row without tags keeps the column
    default ``{}``.
    """
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
    if metadata:
        row.metadata_json = dict(metadata)
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


@overload
async def ainvoke_structured[T: BaseModel](
    db: AsyncSession,
    task: AITaskType,
    schema: type[T],
    system: str,
    user: str,
    user_id=None,
    images: list[tuple[str, bytes]] | None = None,
    run: RunRef | None = None,
    with_audit_ref: Literal[False] = False,
) -> "T": ...


@overload
async def ainvoke_structured[T: BaseModel](
    db: AsyncSession,
    task: AITaskType,
    schema: type[T],
    system: str,
    user: str,
    user_id=None,
    images: list[tuple[str, bytes]] | None = None,
    run: RunRef | None = None,
    with_audit_ref: Literal[True] = True,
) -> "tuple[T, dict]": ...


async def ainvoke_structured[T: BaseModel](
    db: AsyncSession,
    task: AITaskType,
    schema: type[T],
    system: str,
    user: str,
    user_id=None,
    images: list[tuple[str, bytes]] | None = None,
    run: RunRef | None = None,
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

    if user_id is not None and settings.ratelimit_ai > 0:
        from app.core.errors import DomainError
        from app.middleware import RATE_LIMIT_POLICY

        # Raw keyed window (plan 21): the gateway limiter keys on the AI
        # ceiling alone — RATelimit_ENABLED gates only the middleware.
        retry_after = await RATE_LIMIT_POLICY.hit(f"ai:user:{user_id}", limit=settings.ratelimit_ai)
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
    from app.ai.prompt_versions import prompt_version
    from app.ai.tracing import sink

    pack = await resolve_pack(db, task.value, user_id=user_id)
    effective_system = compose_system(system, pack)
    attempts = 3 if resolved.provider_type != "mock" else 1
    last_error = ""
    with sink().span(
        "llm.call",
        {
            "run_id": str(run_id) if run_id else None,
            "task_type": task.value,
            "provider": resolved.provider_type,
            "model": resolved.model_name,
            "attempt_cap": attempts,
        },
    ) as llm_span:
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
                    llm_span.set(
                        {
                            "status": "ok",
                            "latency_ms": int(latency),
                            "prompt_version": prompt_version(task.value),
                        }
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
                llm_span.set(
                    {
                        "status": "ok",
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "latency_ms": int(latency),
                        "prompt_version": prompt_version(task.value),
                    }
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
        llm_span.set({"status": "error", "latency_ms": int(latency)})
        raise StructuredAIError(
            f"AI task '{task.value}' failed after {attempts} attempts: {last_error}"
        )


AGENT_MOCK_SCRIPTS: dict[str, Callable[[str, list[str]], Any]] = {}


def register_agent_mock(task: str, builder: Callable[[str, list[str]], Any]) -> None:
    """Register a deterministic agent-round mock (test/E2E only).

    The builder receives ``(user_text, tool_names)`` and returns an object
    with ``content`` and optional ``tool_calls`` (name/args dicts) — the
    mock stand-in for a bound-tools AIMessage.
    """
    AGENT_MOCK_SCRIPTS[task] = builder


def _agent_mock_output(task: AITaskType, user: str, tools: list[dict]) -> AIMessage:
    """Deterministic agent-round reply for the mock provider.

    Default: a no-tool-call message (the graph proceeds to the structured
    synth node — mock parity with the legacy single-call turn). Tests can
    script tool calls via ``register_agent_mock``.
    """
    ensure_mock_registry()
    builder = AGENT_MOCK_SCRIPTS.get(task.value)
    if builder is not None:
        out = builder(user, [spec["function"]["name"] for spec in tools])
        return AIMessage(
            content=out.get("content", ""),
            tool_calls=[
                {"name": call["name"], "args": call.get("args", {}), "id": call["id"]}
                for call in out.get("tool_calls", [])
            ],
        )
    return AIMessage(content="")


async def ainvoke_agent(
    db: AsyncSession,
    task: AITaskType,
    *,
    system: str,
    messages: list[BaseMessage],
    tools: list[dict],
    user_id=None,
    run: RunRef | None = None,
) -> AIMessage:
    """One native tool-round model call through the standard funnel.

    The agent-round counterpart of ``ainvoke_structured`` (ADR-0016): the
    model is built with ``json_mode=False`` and bound to the given
    OpenAI function-format tool specs; the returned ``AIMessage`` carries
    ``.tool_calls`` (args are untrusted until ``run_tool`` validates
    them). Resolution, budgets, packs, retries and the audit row follow
    the structured path; the audit output records the tool calls + text
    (``run_id``/``run_stage`` pin the turn via ``run``).
    """
    from app.ai.providers.resolution import resolve_task_model

    if user_id is not None and settings.ratelimit_ai > 0:
        from app.core.errors import DomainError
        from app.middleware import RATE_LIMIT_POLICY

        # Raw keyed window (plan 21): the gateway limiter keys on the AI
        # ceiling alone — RATelimit_ENABLED gates only the middleware.
        retry_after = await RATE_LIMIT_POLICY.hit(f"ai:user:{user_id}", limit=settings.ratelimit_ai)
        if retry_after is not None:
            raise DomainError(f"AI rate limit reached; retry in {retry_after}s")

    resolved = await resolve_task_model(db, task.value, user_id)
    run_id = run.id if run is not None else None
    run_stage = run.stage if run is not None else None
    started = time.perf_counter()
    user_text = _message_text(messages[-1]) if messages else ""
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
            user_text,
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
            user_text,
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
                message = _agent_mock_output(task, user_text, tools)
            else:
                model = build_chat_model(resolved, json_mode=False)
                bound = model.bind_tools(tools) if tools else model
                message = await bound.ainvoke([SystemMessage(content=effective_system), *messages])
            usage: dict[str, Any] = dict(getattr(message, "usage_metadata", None) or {})
            latency = (time.perf_counter() - started) * 1000
            await _record(
                db,
                user_id,
                task,
                resolved.model_name,
                user_text,
                {
                    "tool_calls": [
                        {"name": call["name"], "args": call.get("args", {})}
                        for call in (message.tool_calls or [])
                    ],
                    "text": _message_text(message)[:1000],
                },
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                latency,
                "ok",
                provider_type=resolved.provider_type,
                pack_key=pack.key if pack else None,
                pack_version=pack.version if pack else None,
                run_id=run_id,
                run_stage=run_stage,
            )
            return message
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "agent attempt %d for task %s failed: %s",
                attempt + 1,
                task.value,
                last_error,
            )
    latency = (time.perf_counter() - started) * 1000
    await _record(
        db,
        user_id,
        task,
        resolved.model_name,
        user_text,
        None,
        None,
        None,
        latency,
        "error",
        last_error,
        provider_type=resolved.provider_type,
        run_id=run_id,
        run_stage=run_stage,
    )
    raise StructuredAIError(
        f"AI task '{task.value}' failed after {attempts} attempts: {last_error}"
    )


def utcnow() -> datetime:
    """Current UTC time."""
    return datetime.now(UTC)


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
        self.reply: BaseModel | None = None
        self.error: str = ""
        self.model: str | None = None
        # Usage from the last streamed chunk, when the provider reports it
        # (surfaced on the turn trace for the UI).
        self.tokens_in: int | None = None
        self.tokens_out: int | None = None
        self._raw: list[str] = []

    async def chunks(
        self,
        db: AsyncSession,
        task: AITaskType,
        schema: type[T],
        system: str,
        user: str,
        user_id=None,
        images: list[tuple[str, bytes]] | None = None,
    ):
        from app.ai.providers.resolution import resolve_task_model

        if user_id is not None and settings.ratelimit_ai > 0:
            from app.core.errors import DomainError
            from app.middleware import RATE_LIMIT_POLICY

            # Raw keyed window (plan 21): keyed on the AI ceiling alone.
            retry_after = await RATE_LIMIT_POLICY.hit(
                f"ai:user:{user_id}", limit=settings.ratelimit_ai
            )
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

        model = None
        messages: list | None = None
        finish_reason = ""
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
                        content=f"{effective_system}\n\nReply with JSON matching this schema:\n{_schema_hint(schema)}"  # noqa: E501 -- long message string; reflow when touched
                    ),
                    HumanMessage(content=_user_content(user, images)),
                ]
                async for chunk in model.astream(messages):
                    piece = _message_text(chunk)
                    if piece:
                        self._raw.append(piece)
                        yield piece
                    finish_reason = _finish_reason(chunk) or finish_reason
                    usage = chunk.usage_metadata
                    if usage:
                        self.tokens_in = usage.get("input_tokens")
                        self.tokens_out = usage.get("output_tokens")
                if not "".join(self._raw).strip():
                    # Some replies stream zero usable text (whitespace
                    # only, safety block, or the answer lands outside the
                    # text parts) — one non-streaming attempt before
                    # failing, else every such turn died on
                    # json.loads("") downstream.
                    message = await model.ainvoke(messages)
                    text = _message_text(message)
                    if text:
                        self._raw.append(text)
                        yield text
                    finish_reason = _finish_reason(message) or finish_reason
                    usage = getattr(message, "usage_metadata", None)
                    if usage:
                        self.tokens_in = usage.get("input_tokens")
                        self.tokens_out = usage.get("output_tokens")

            latency = (time.perf_counter() - started) * 1000
            if not "".join(self._raw).strip():
                raise StructuredAIError(
                    "The model returned no text content (it may have been "
                    "safety-blocked) — please retry."
                )
            accumulated = "".join(self._raw)
            try:
                self.reply = schema.model_validate(_extract_json(accumulated))
            except (json.JSONDecodeError, PydanticValidationError) as exc:
                # One non-streaming rescue — but never when answer text
                # already streamed (the UI showed it; a diverging retry
                # would contradict it).
                if model is None or messages is None or partial_answer_text(accumulated).strip():
                    raise StructuredAIError(_stream_failure_message(finish_reason)) from exc
                message = await model.ainvoke(messages)
                text = _message_text(message)
                finish_reason = _finish_reason(message) or finish_reason
                usage = getattr(message, "usage_metadata", None)
                if usage:
                    self.tokens_in = usage.get("input_tokens")
                    self.tokens_out = usage.get("output_tokens")
                if not text.strip():
                    raise StructuredAIError(_stream_failure_message(finish_reason)) from exc
                self._raw.append(text)
                yield text
                try:
                    self.reply = schema.model_validate(_extract_json("".join(self._raw)))
                except (json.JSONDecodeError, PydanticValidationError) as rescue_exc:
                    raise StructuredAIError(_stream_failure_message(finish_reason)) from rescue_exc
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
        except Exception as exc:
            self.error = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
            audit_error = self.error
            if self.reply is None:
                raw_snippet = "".join(self._raw).strip()
                if raw_snippet:
                    # Debuggability: the audit `output` keeps the full raw
                    # reply (the error column cap hides the tail that
                    # actually broke validation), the error line keeps a
                    # 600-char head.
                    audit_error = f"{audit_error} | raw={raw_snippet[:600]!r}"
                    if "AINotConfigured" not in self.error:
                        latency = (time.perf_counter() - started) * 1000
                        await _record(
                            db,
                            user_id,
                            task,
                            resolved.provider_type,
                            user,
                            {"raw": raw_snippet[:4000]},
                            self.tokens_in,
                            self.tokens_out,
                            latency,
                            "error",
                            audit_error,
                            provider_type=resolved.provider_type,
                        )
                elif "AINotConfigured" not in self.error:
                    latency = (time.perf_counter() - started) * 1000
                    await _record(
                        db,
                        user_id,
                        task,
                        resolved.provider_type,
                        user,
                        None,
                        self.tokens_in,
                        self.tokens_out,
                        latency,
                        "error",
                        audit_error,
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


@dataclass(frozen=True)
class EmbedBatch:
    """One provider request's worth of texts (plan 201 S4).

    ``tokens`` is the caller's counted input tokens for the audit row;
    ``tags`` is that batch's retrieval-tag map (a batch may span documents,
    in which case it carries the coarse ids only — plan 201 S7 adds the
    per-batch document seam).
    """

    texts: tuple[str, ...]
    tokens: int | None = None
    tags: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class EmbedBatchOutcome:
    """One batch's result, aligned with the ``embed_batches`` input order."""

    vectors: list[list[float]] | None
    error: str | None = None
    error_exc: BaseException | None = None
    tokens_in: int | None = None
    latency_ms: float = 0.0


async def embed_texts(
    db: AsyncSession,
    texts: list[str],
    user_id=None,
    run: RunRef | None = None,
    metadata: Mapping[str, Any] | None = None,
    *,
    tokens_in: int | None = None,
) -> list[list[float]]:
    """Embed one batch of texts via the ``embed`` task (serial, one request).

    Same funnel as every gateway call: rate limit, resolve (503 when
    unassigned), budgets, audit — see :func:`embed_batches`. The mock provider
    synthesizes deterministic unit vectors (dim ``MOCK_EMBED_DIM``) so ranking
    is testable without a provider; real providers go through the cached
    embeddings model.

    ``metadata`` is the caller's retrieval tagging seam (plan 51 Q1a) and
    ``tokens_in`` the caller's counted input tokens (plan 201 S1) — both land
    on the audit row exactly as supplied. Transient provider failures retry
    inside the funnel (plan 201 S3); the audit keeps ONE row per request
    outcome.
    """
    outcome = (
        await embed_batches(
            db,
            [EmbedBatch(tuple(texts), tokens_in, metadata)],
            concurrency=1,
            user_id=user_id,
            run=run,
        )
    )[0]
    if outcome.vectors is None:
        raise outcome.error_exc or RuntimeError(outcome.error or "embed failed")
    return outcome.vectors


async def embed_batches(
    db: AsyncSession,
    batches: Sequence[EmbedBatch],
    *,
    concurrency: int | None = None,
    user_id=None,
    run: RunRef | None = None,
) -> list[EmbedBatchOutcome]:
    """Embed several batches through ONE funnel pass (plan 201 S4).

    Rate limit, task resolution, the production mock guard, the token budget
    and the client are handled **once** for the whole group; the provider
    calls then run under a semaphore (`settings.embed_concurrency`, ``None``
    = auto: 1 on SQLite, 4 elsewhere). The concurrent section touches no
    database — SQLite's single writer is never held across a network call
    (plans 192/194) — and the per-batch audit rows are written sequentially
    after the calls settle, each with its own batch tags.

    Returns one :class:`EmbedBatchOutcome` per batch, in input order; a
    failed batch carries ``vectors=None`` plus the original exception (callers
    that need it raise ``outcome.error_exc``). Unconfigured/budget failures
    raise before any batch runs.
    """
    from app.ai.providers.resolution import resolve_task_model

    outcomes = [EmbedBatchOutcome(vectors=None, error="not attempted") for _ in batches]
    if not batches:
        return outcomes
    effective = _auto_embed_concurrency(db) if concurrency is None else max(int(concurrency), 1)

    if user_id is not None and settings.ratelimit_ai > 0:
        from app.core.errors import DomainError
        from app.middleware import RATE_LIMIT_POLICY

        # Raw keyed window (plan 21): the gateway limiter keys on the AI
        # ceiling alone — RATELIMIT_ENABLED gates only the middleware. One hit
        # per funnel call, so a grouped request costs one window slot, not one
        # per batch.
        retry_after = await RATE_LIMIT_POLICY.hit(f"ai:user:{user_id}", limit=settings.ratelimit_ai)
        if retry_after is not None:
            raise DomainError(f"AI rate limit reached; retry in {retry_after}s")

    resolved = await resolve_task_model(db, AITaskType.EMBED.value, user_id)
    run_id = run.id if run is not None else None
    run_stage = run.stage if run is not None else None
    total_texts = sum(len(batch.texts) for batch in batches)
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
            f"embed {total_texts} text(s)",
            None,
            None,
            None,
            latency,
            "error",
            error,
            provider_type="none",
            run_id=run_id,
            run_stage=run_stage,
            metadata=batches[0].tags,
        )
        raise AINotConfiguredError(error)
    if resolved.provider_type == "mock" and settings.is_production:
        raise AINotConfiguredError(
            "AI is not configured for this environment: the mock provider is "
            "dev-only. Configure a real provider in Settings → AI Configuration."
        )
    from app.ai.budgets import enforce_budgets
    from app.ai.tracing import sink

    await enforce_budgets(db, AITaskType.EMBED, user_id)
    with sink().span(
        "llm.call",
        {
            "run_id": str(run_id) if run_id else None,
            "task_type": AITaskType.EMBED.value,
            "provider": resolved.provider_type,
            "model": resolved.model_name,
        },
    ) as llm_span:
        semaphore = asyncio.Semaphore(effective)
        attempts = _embed_attempts(resolved.provider_type)

        async def _run_batch(index: int, batch: EmbedBatch) -> EmbedBatchOutcome:
            batch_started = time.perf_counter()
            texts = list(batch.texts)
            async with semaphore:
                last_error: BaseException | None = None
                for attempt in range(attempts):
                    try:
                        if resolved.provider_type == "mock":
                            raw = [_mock_embedding(text) for text in texts]
                        else:
                            from app.ai.model_cache import get_embedding_model

                            model = get_embedding_model(resolved)
                            raw = await model.aembed_documents(texts, chunk_size=max(len(texts), 1))
                        vectors = [list(map(float, vector)) for vector in raw]
                        return EmbedBatchOutcome(
                            vectors=vectors,
                            tokens_in=batch.tokens,
                            latency_ms=(time.perf_counter() - batch_started) * 1000,
                        )
                    except Exception as exc:
                        last_error = exc
                        if attempt + 1 >= attempts:
                            break
                        logger.warning(
                            "embed batch %d attempt %d/%d failed: %s: %s",
                            index,
                            attempt + 1,
                            attempts,
                            type(exc).__name__,
                            exc,
                        )
                        await asyncio.sleep(_embed_retry_delay(attempt, exc))
                error = f"{type(last_error).__name__}: {last_error}"
                return EmbedBatchOutcome(
                    vectors=None,
                    error=error,
                    error_exc=last_error,
                    tokens_in=batch.tokens,
                    latency_ms=(time.perf_counter() - batch_started) * 1000,
                )

        results = list(
            await asyncio.gather(*(_run_batch(index, batch) for index, batch in enumerate(batches)))
        )
        # The audit rows are written AFTER the concurrent section: this await
        # flushes into the caller's session, and holding SQLite's single
        # writer across network calls is the plans 192/194 deadlock.
        for batch, outcome in zip(batches, results, strict=True):
            if outcome.vectors is not None:
                await _record(
                    db,
                    user_id,
                    AITaskType.EMBED,
                    resolved.provider_type,
                    f"embed {len(batch.texts)} text(s), dim "
                    f"{len(outcome.vectors[0]) if outcome.vectors else 0}",
                    {
                        "count": len(outcome.vectors),
                        "dim": len(outcome.vectors[0]) if outcome.vectors else 0,
                    },
                    outcome.tokens_in,
                    None,
                    outcome.latency_ms,
                    "ok",
                    model_name=resolved.model_name,
                    provider_type=resolved.provider_type,
                    run_id=run_id,
                    run_stage=run_stage,
                    metadata=batch.tags,
                )
            else:
                await _record(
                    db,
                    user_id,
                    AITaskType.EMBED,
                    resolved.model_name,
                    f"embed {len(batch.texts)} text(s)",
                    None,
                    None,
                    None,
                    outcome.latency_ms,
                    "error",
                    outcome.error or "",
                    run_id=run_id,
                    run_stage=run_stage,
                    metadata=batch.tags,
                )
        ok = sum(1 for outcome in results if outcome.vectors is not None)
        llm_span.set(
            {
                "status": "ok" if ok == len(results) else "error",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "texts": total_texts,
                "batches": len(results),
                "batches_ok": ok,
            }
        )
        return results


def _auto_embed_concurrency(db: AsyncSession) -> int:
    """``None`` = auto: 1 on SQLite (one writer), 4 elsewhere (plan 201 S4)."""
    configured = settings.embed_concurrency
    if configured is not None:
        return max(int(configured), 1)
    return 1 if db.get_bind().dialect.name == "sqlite" else 4


#: Attempts before an embedding batch fails (plan 201 S3). The mock provider
#: stays single-shot so tests are deterministic.
EMBED_ATTEMPTS = 3
#: Base backoff between embedding attempts; exponential with jitter, capped.
EMBED_RETRY_BASE_SECONDS = 0.5
EMBED_RETRY_MAX_SECONDS = 30.0


def _embed_attempts(provider_type: str) -> int:
    return 1 if provider_type == "mock" else EMBED_ATTEMPTS


def _retry_after_seconds(exc: BaseException) -> float | None:
    """The provider's ``Retry-After`` hint, when it exposes one (429)."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if not headers:
        return None
    raw = None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        return None


def _embed_retry_delay(attempt: int, exc: BaseException) -> float:
    """Jittered exponential backoff, never shorter than the provider's hint."""
    import random

    base = EMBED_RETRY_BASE_SECONDS * (2**attempt)
    hinted = _retry_after_seconds(exc) or 0.0
    return min(max(base, hinted) + random.uniform(0.0, 0.25), EMBED_RETRY_MAX_SECONDS)


async def transcribe_audio(
    db: AsyncSession,
    *,
    user_id=None,
    data: bytes,
    mime: str,
    language: str | None = None,
) -> tuple[str, str]:
    """Speech-to-text for dictation. Resolves the
    ``transcribe`` task like every gateway call (budget, rate limit,
    audit), then uses the provider's audio API — audio is not a
    LangChain chat capability. Returns ``(text, model_name)``."""
    from app.ai.providers.resolution import resolve_task_model
    from app.ai.transcribe import transcribe_with

    if user_id is not None and settings.ratelimit_ai > 0:
        from app.core.errors import DomainError
        from app.middleware import RATE_LIMIT_POLICY

        # Raw keyed window (plan 21): the gateway limiter keys on the AI
        # ceiling alone — RATelimit_ENABLED gates only the middleware.
        retry_after = await RATE_LIMIT_POLICY.hit(f"ai:user:{user_id}", limit=settings.ratelimit_ai)
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
    except Exception as exc:
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
