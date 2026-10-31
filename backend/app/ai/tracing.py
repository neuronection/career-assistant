"""Optional OpenTelemetry span export for AI flows (plan 168, ADR-0044).

A trace SINK, never a surface: the in-app trace is the durable
``run_steps`` ledger and the audited ``ai_generations`` rows; this module
only mirrors spans out when an operator opts in via ``CAREER_OTEL_EXPORT``
(``console`` | ``otlp``). The import is guarded — without the ``otel``
extra installed every span is a no-op, so desktop stays zero-setup and
inert. Bad configuration degrades to disabled with one warning, never a
crash. Spans carry run/node/task metadata ONLY — never prompt or output
text (those live in the admin audit ledger).
"""

import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from types import TracebackType
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_RUN_ATTRS: ContextVar[dict | None] = ContextVar("career_trace_run_attrs", default=None)


class _NoopSpan:
    """The disabled-mode span: accepts attribute sets, records nothing."""

    def set(self, _attrs: dict) -> None:
        return None

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


_NOOP_SPAN = _NoopSpan()


class TraceSink:
    """The one tracing seam: ``sink().span(name, attrs)`` per logical step.

    Disabled by default; ``CAREER_OTEL_EXPORT`` selects ``console`` or
    ``otlp`` (``CAREER_OTEL_ENDPOINT`` required for the latter). Every
    span merges the ambient run context (``run_id``/``goal_id`` from
    ``run_scope``) beneath its explicit attributes, so a lost asyncio
    context still leaves each span correlatable.
    """

    def __init__(self) -> None:
        self._provider: Any = None
        self._tracer: Any = None
        self._warned: set[str] = set()

    def _warn_once(self, message: str, *, exc_info: bool = False) -> None:
        if message in self._warned:
            return
        self._warned.add(message)
        logger.warning(message, exc_info=exc_info)

    def _enabled_mode(self) -> str:
        mode = (settings.otel_export or "").strip().lower()
        if mode and mode not in ("console", "otlp"):
            self._warn_once(
                f"CAREER_OTEL_EXPORT={mode!r} is not console|otlp — tracing stays disabled"
            )
            return ""
        if mode == "otlp" and not (settings.otel_endpoint or "").strip():
            self._warn_once(
                "CAREER_OTEL_EXPORT=otlp needs CAREER_OTEL_ENDPOINT — tracing stays disabled"
            )
            return ""
        return mode

    def use_processor(self, processor) -> None:
        """Alternative-exporter seam (tests, future in-process consumers):
        build the tracer around an explicit span processor instead of the
        env-selected exporter."""
        self.reset()
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": settings.otel_service_name or "career-assistant"}
            )
        )
        provider.add_span_processor(processor)
        self._provider = provider
        self._tracer = provider.get_tracer(settings.otel_service_name or "career-assistant")

    def reset(self) -> None:
        """Drop a configured provider (tests, re-configuration)."""
        provider, self._provider, self._tracer = self._provider, None, None
        if provider is None:
            return
        with contextlib.suppress(Exception):
            provider.shutdown()

    def _tracer_for(self, mode: str):
        if self._tracer is not None:
            return self._tracer
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            self._warn_once("opentelemetry is not installed — CAREER_OTEL_EXPORT is ignored")
            return None
        try:
            provider = TracerProvider(
                resource=Resource.create(
                    {"service.name": settings.otel_service_name or "career-assistant"}
                )
            )
            if mode == "console":
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter

                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            else:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
                )
        except Exception:
            self._warn_once("tracing exporter setup failed — tracing stays disabled", exc_info=True)
            return None
        self._provider = provider
        self._tracer = trace.get_tracer(settings.otel_service_name or "career-assistant")
        return self._tracer

    @contextlib.contextmanager
    def span(self, name: str, attrs: dict | None = None) -> Iterator:
        """One span around a logical step; a no-op when disabled, the SDK
        is absent, or tracing itself fails — the wrapped body always runs."""
        merged = {**(_RUN_ATTRS.get() or {}), **(attrs or {})}
        tracer = None
        mode = self._enabled_mode()
        if self._tracer is not None:
            tracer = self._tracer
        elif mode:
            try:
                tracer = self._tracer_for(mode)
            except Exception:
                self._warn_once("tracing setup failed — tracing stays disabled", exc_info=True)
        if tracer is None:
            yield _NOOP_SPAN
            return
        clean = {key: value for key, value in merged.items() if value is not None}
        try:
            cm = tracer.start_as_current_span(name, attributes=clean)
            otel_span = cm.__enter__()
        except Exception:
            self._warn_once(
                "tracing failed to start a span — tracing stays disabled",
                exc_info=True,
            )
            yield _NOOP_SPAN
            return
        try:
            yield _OtelSpan(otel_span)
        except BaseException as exc:
            with contextlib.suppress(Exception):
                cm.__exit__(type(exc), exc, exc.__traceback__)
            raise
        with contextlib.suppress(Exception):
            cm.__exit__(None, None, None)

    @contextlib.contextmanager
    def run_scope(self, run_id: str, goal_id: str) -> Iterator[None]:
        """Stamp run_id/goal_id into the ambient context so every nested
        span carries them as attributes, context or no context."""
        token = _RUN_ATTRS.set({"run_id": run_id, "goal_id": goal_id})
        try:
            yield
        finally:
            _RUN_ATTRS.reset(token)

    def flush(self) -> None:
        """Force-export pending spans (bounded); best-effort by design."""
        if self._provider is None:
            return
        try:
            self._provider.force_flush(timeout_millis=5000)
        except Exception:
            logger.warning("Tracing flush failed", exc_info=True)

    def shutdown(self) -> None:
        """Flush and release the provider (app lifespan shutdown)."""
        provider, self._provider, self._tracer = self._provider, None, None
        if provider is None:
            return
        try:
            provider.shutdown()
        except Exception:
            logger.warning("Tracing shutdown failed", exc_info=True)


class _OtelSpan:
    """The enabled-mode span handle: post-hoc metadata lands here."""

    def __init__(self, otel_span) -> None:
        self._span = otel_span

    def set(self, attrs: dict) -> None:
        try:
            self._span.set_attributes(
                {key: value for key, value in attrs.items() if value is not None}
            )
        except Exception:
            logger.debug("span attribute set failed", exc_info=True)

    def __enter__(self) -> "_OtelSpan":
        return self

    def __exit__(
        self, exc_type: type | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None


_SINK = TraceSink()


def sink() -> TraceSink:
    """The process-wide sink (one provider, one configuration)."""
    return _SINK
