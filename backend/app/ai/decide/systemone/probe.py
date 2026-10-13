"""Decision probe — D13 validation for decision-only providers.

One minimal typed question under the abort timeout; a classified
failure persists nothing (the caller rolls back). The probe can never
serve as an answer oracle without a valid key: every failure maps to
the shared error classification (401/402/403 → the corresponding codes).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.models.ai_provider_model import AIModel, AIProvider

from ..types import DECISION_PROBE_TIMEOUT_SECONDS, DecisionCapability
from .client import (
    SystemOneCallParams,
    SystemOneClient,
    TypeSafeClientConfig,
    TypeSafeError,
    TypeSafeQuestion,
    TypeSafeSdkSystemOneClient,
    resolve_systemone_base_url,
)

PROBE_QUESTION_ID = "__probe__"


@dataclass(frozen=True)
class DecisionProbeResult:
    ok: bool
    latency_ms: int
    resolved_model: str | None = None
    status: int | None = None
    kind: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class DecisionProbeInput:
    provider: AIProvider
    model: AIModel
    api_key: str
    timeout_seconds: float | None = None
    transport: Any = None
    client: SystemOneClient | None = None


async def probe_decision_provider(probe_input: DecisionProbeInput) -> DecisionProbeResult:
    started_at = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - started_at) * 1000)

    base_url = resolve_systemone_base_url(probe_input.provider, probe_input.model)
    if base_url is None:
        return DecisionProbeResult(
            ok=False, latency_ms=0, error="The provider base URL is missing or invalid."
        )
    timeout_seconds = probe_input.timeout_seconds or DECISION_PROBE_TIMEOUT_SECONDS
    client: SystemOneClient = probe_input.client or TypeSafeSdkSystemOneClient(
        TypeSafeClientConfig(
            api_key=probe_input.api_key,
            base_url=base_url,
            model=probe_input.model.model_name,
            timeout_seconds=timeout_seconds,
            max_retries=0,
            transport=probe_input.transport,
        )
    )
    try:
        result = await asyncio.wait_for(
            client.system_one(
                SystemOneCallParams(
                    state="connectivity check",
                    questions={
                        PROBE_QUESTION_ID: TypeSafeQuestion(
                            type=DecisionCapability.BOOLEAN_GATE,
                            instructions=("Is this a working decision endpoint? Answer true."),
                        )
                    },
                )
            ),
            timeout=timeout_seconds,
        )
        return DecisionProbeResult(
            ok=True,
            latency_ms=elapsed_ms(),
            resolved_model=result.model or None,
        )
    except TypeSafeError as error:
        return DecisionProbeResult(
            ok=False,
            latency_ms=elapsed_ms(),
            status=error.status,
            kind=error.kind.value,
            error=error.message[:300],
        )
    except TimeoutError:
        return DecisionProbeResult(
            ok=False,
            latency_ms=elapsed_ms(),
            kind="timeout",
            error="decision probe timed out",
        )
    except Exception as error:
        return DecisionProbeResult(
            ok=False,
            latency_ms=elapsed_ms(),
            error=str(error)[:300],
        )
