"""Provider abstraction: every AI call goes through ``ainvoke_structured``.

Outputs are always validated into a pydantic schema. The ``mock`` provider
produces deterministic schema-aware outputs so the full app runs offline and
tests stay hermetic.
"""

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AINotConfiguredError
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType

if TYPE_CHECKING:
    from app.ai.providers.resolution import ResolvedModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MOCK_FIXTURES: dict[str, Callable[[type[T], str], dict]] = {}


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


async def _invoke_openai(
    schema: type[T],
    system: str,
    user: str,
    resolved: "ResolvedModel",
) -> tuple[T, Optional[int], Optional[int]]:
    """Call an OpenAI-compatible chat completion and validate the output."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=resolved.api_key or "missing",
        base_url=resolved.base_url,
        timeout=settings.AI_TIMEOUT,
    )
    schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    response = await client.chat.completions.create(
        model=resolved.model_name,
        messages=[
            {
                "role": "system",
                "content": f"{system}\n\nReply with JSON matching this schema:\n{schema_hint}",
            },
            {"role": "user", "content": user},
        ],
        temperature=resolved.temperature if resolved.temperature is not None else 0.4,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    tokens_in = response.usage.prompt_tokens if response.usage else None
    tokens_out = response.usage.completion_tokens if response.usage else None
    return schema.model_validate(_extract_json(raw)), tokens_in, tokens_out


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
) -> None:
    """Persist an audit row for one AI call."""
    db.add(
        AIGeneration(
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
        )
    )
    await db.flush()


async def ainvoke_structured(
    db: AsyncSession,
    task: AITaskType,
    schema: type[T],
    system: str,
    user: str,
    user_id=None,
) -> T:
    """Run an AI task and return a schema-validated result (audited).

    The provider/model is resolved per (task, user) from the database:
    user assignment > system assignment > "default" assignment. Raises
    ``AINotConfiguredError`` when nothing is configured (or a mock provider
    is resolved in production) and ``StructuredAIError`` when no valid
    output can be produced; failures are recorded in ``ai_generations``.
    """
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
        )
        raise AINotConfiguredError(error)
    attempts = 3 if resolved.provider_type != "mock" else 1
    last_error = ""
    for attempt in range(attempts):
        try:
            if resolved.provider_type == "mock":
                await asyncio.sleep(0)
                result = _mock_output(schema, task, user)
                latency = (time.perf_counter() - started) * 1000
                await _record(
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
                )
                return result
            result, tokens_in, tokens_out = await _invoke_openai(
                schema,
                system,
                user,
                resolved,
            )
            latency = (time.perf_counter() - started) * 1000
            await _record(
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
            )
            return result
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
        if resolved.provider_type == "mock" and settings.is_production:
            raise AINotConfiguredError(
                "AI is not configured for this environment: the mock provider "
                "is dev-only. Configure a real provider in Settings → AI "
                "Configuration."
            )

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
                from openai import AsyncOpenAI

                client = AsyncOpenAI(
                    api_key=resolved.api_key or "missing",
                    base_url=resolved.base_url,
                    timeout=settings.AI_TIMEOUT,
                )
                schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
                stream = await client.chat.completions.create(
                    model=resolved.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": f"{system}\n\nReply with JSON matching this schema:\n{schema_hint}",
                        },
                        {"role": "user", "content": user},
                    ],
                    temperature=resolved.temperature
                    if resolved.temperature is not None
                    else 0.4,
                    response_format={"type": "json_object"},
                    stream=True,
                    stream_options={"include_usage": True},
                )
                async for event in stream:
                    if event.choices and event.choices[0].delta.content:
                        piece = event.choices[0].delta.content
                        self._raw.append(piece)
                        yield piece
                    if getattr(event, "usage", None):
                        self._tokens_in = event.usage.prompt_tokens
                        self._tokens_out = event.usage.completion_tokens

            latency = (time.perf_counter() - started) * 1000
            self.reply = schema.model_validate(_extract_json("".join(self._raw)))
            await _record(
                db,
                user_id,
                task,
                resolved.provider_type,
                user,
                self.reply.model_dump(mode="json"),
                getattr(self, "_tokens_in", None),
                getattr(self, "_tokens_out", None),
                latency,
                "ok",
                model_name=resolved.model_name,
                provider_type=resolved.provider_type,
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
