"""The optional OTel export seam (plan 168 S4.4).

Default is a no-op: no exporter, no spans, desktop inert. With a span
processor injected (the test seam), the gateway's ``llm.call`` spans and
the autopilot's ``node``/``run`` spans carry the metadata vocabulary —
run_id, goal_id, node, task_type, provider, model, tokens, latency,
status — and NEVER prompt or output text. The env-built export path
(``CAREER_OTEL_EXPORT=console|otlp``) is pinned end-to-end: the exporter
captured at its construction site must receive a real span, and the
tracer must come from the provider the sink built. A tracing failure
never fails the wrapped call; a misconfiguration degrades to disabled
with exactly one warning. The tests pass on both install modes: without
the ``otel`` extra the guarded import keeps everything a no-op (SDK
absence is simulated explicitly too), so no skip is ever created.
"""

import logging
import sys

import pytest

from app.ai import tracing
from app.ai.gateway import ainvoke_structured
from app.ai.schemas import ChatReply
from app.ai.tracing import TraceSink, sink
from app.models.enums import AITaskType


@pytest.fixture
def fresh_sink(monkeypatch):
    """A pristine sink per test: default-disabled settings, reset provider."""
    monkeypatch.setattr("app.core.config.settings.otel_export", "")
    monkeypatch.setattr("app.core.config.settings.otel_endpoint", None)
    monkeypatch.setattr("app.core.config.settings.otel_service_name", "career-assistant")
    fresh = TraceSink()
    monkeypatch.setattr(tracing, "_SINK", fresh)
    yield fresh
    fresh.reset()


def _in_memory_processor():
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    return SimpleSpanProcessor(exporter), exporter


def _sdk_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("opentelemetry.sdk") is not None


def _capture(fresh: TraceSink):
    processor, exporter = _in_memory_processor()
    fresh.use_processor(processor)
    return exporter


async def test_default_is_a_noop_without_any_exporter(fresh_sink, db, client, auth_headers):
    """No CAREER_OTEL_EXPORT ⇒ no provider, no spans, desktop inert —
    and the wrapped gateway call still answers (plan 168 S4.2)."""
    result = await ainvoke_structured(
        db, AITaskType.ASSIST, ChatReply, system="s", user="CONTEXT_JSON: {}"
    )
    assert isinstance(result, ChatReply)
    assert fresh_sink._provider is None, "no exporter was ever built"
    assert fresh_sink._enabled_mode() == ""


async def test_sink_failure_never_fails_the_gateway_call(fresh_sink, db, client, auth_headers):
    """A broken tracer degrades to the no-op span; the call still answers
    (plan 168 S4.4)."""

    class ExplodingTracer:
        def start_as_current_span(self, *args, **kwargs):
            raise RuntimeError("tracer exploded")

    fresh_sink._tracer = ExplodingTracer()
    fresh_sink._provider = object()
    result = await ainvoke_structured(
        db, AITaskType.ASSIST, ChatReply, system="s", user="CONTEXT_JSON: {}"
    )
    assert isinstance(result, ChatReply)


async def test_spans_carry_the_metadata_vocabulary_and_parentage(
    fresh_sink, db, client, auth_headers
):
    """With a processor installed, one autopilot run emits an
    ``autopilot.run`` root, ``autopilot.node`` children and ``llm.call``
    gateway spans, each stamped run_id/goal_id; a node's parent is the
    run (plan 168 S4.3)."""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.models.autopilot_model import AutopilotGoal
    from app.services.growth.autopilot_service import AutopilotService
    from tests.conftest import decode_session_token

    exporter = _capture(fresh_sink) if _sdk_available() else None

    user_id = decode_session_token(auth_headers["Authorization"].split(" ", 1)[1])[0]
    goal = AutopilotGoal(
        user_id=user_id,
        goal_text="Junior QA job, remote",
        constraints={},
        budget={},
    )
    db.add(goal)
    await db.commit()

    result = await AutopilotService(db, checkpointer=InMemorySaver()).run_goal(goal.id, user_id)
    await db.commit()
    assert result["status"] in ("completed", "budget_aborted")

    if exporter is None:
        assert fresh_sink._provider is None, (
            "no SDK installed ⇒ no provider; the capture contract runs in the CI --extra otel step"
        )
        return

    spans = exporter.get_finished_spans()
    names = [span.name for span in spans]
    assert "autopilot.run" in names
    assert "autopilot.node" in names
    assert "llm.call" in names

    run_span = next(span for span in spans if span.name == "autopilot.run")
    node_span = next(span for span in spans if span.name == "autopilot.node")
    assert run_span.attributes["run_id"] == result["run_id"]
    assert run_span.attributes["goal_id"] == str(goal.id)
    assert node_span.attributes["run_id"] == result["run_id"], "context lost ⇒ still stamped"
    assert node_span.parent is not None
    assert node_span.parent.span_id == run_span.context.span_id, "nodes nest under the run"
    for span in spans:
        assert (
            span.attributes.get("goal_id") is not None or span.attributes.get("run_id") is not None
        )


async def test_prompt_text_never_reaches_a_span_attribute(fresh_sink, db, client, auth_headers):
    """The needle (the goal text inside the planner prompt) appears in no
    span attribute value (plan 168 S1.4 assumption 4 / S4.3)."""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.models.autopilot_model import AutopilotGoal
    from app.services.growth.autopilot_service import AutopilotService
    from tests.conftest import decode_session_token

    exporter = _capture(fresh_sink) if _sdk_available() else None
    needle = "xyzzyspanshouldnevercarrythis"

    user_id = decode_session_token(auth_headers["Authorization"].split(" ", 1)[1])[0]
    goal = AutopilotGoal(
        user_id=user_id,
        goal_text=needle,
        constraints={},
        budget={},
    )
    db.add(goal)
    await db.commit()

    await AutopilotService(db, checkpointer=InMemorySaver()).run_goal(goal.id, user_id)
    await db.commit()

    if exporter is None:
        assert fresh_sink._provider is None, (
            "no SDK installed ⇒ nothing exported; the privacy contract is "
            "pinned against real spans in the CI --extra otel step"
        )
        return

    spans = exporter.get_finished_spans()
    assert spans, "the run emitted spans"
    for span in spans:
        blob = repr(dict(span.attributes or {}))
        assert needle not in blob
        assert "SearchPlan" not in blob


def test_misconfiguration_disables_with_exactly_one_warning(fresh_sink, caplog):
    """`otlp` without an endpoint, and an unparsable value, disable the
    sink and warn ONCE each — never crash (plan 168 S4.2)."""
    fresh_sink._warned.clear()
    with caplog.at_level(logging.WARNING, logger="app.ai.tracing"):
        fresh_sink._warned.clear()
        import app.core.config as config_module

        config_module.settings.otel_export = "otlp"
        config_module.settings.otel_endpoint = None
        assert fresh_sink._enabled_mode() == ""
        assert fresh_sink._enabled_mode() == "", "second read stays disabled"
        assert sum("needs CAREER_OTEL_ENDPOINT" in record.message for record in caplog.records) == 1

        caplog.clear()
        config_module.settings.otel_export = "bogus"
        assert fresh_sink._enabled_mode() == ""
        assert sum("not console|otlp" in record.message for record in caplog.records) == 1

    import app.core.config as config_module

    config_module.settings.otel_export = ""
    config_module.settings.otel_endpoint = None


def test_sdk_absence_is_simulated_and_stays_a_noop(fresh_sink, monkeypatch):
    """Without the `otel` extra (or with every cached `opentelemetry*`
    module evicted, simulating true absence), spans are no-ops and nothing
    raises — no skip is ever created (plan 168 S4.1)."""
    monkeypatch.setattr("app.core.config.settings.otel_export", "console", raising=False)
    import app.core.config as config_module

    config_module.settings.otel_export = "console"
    cached = [name for name in sys.modules if name.startswith("opentelemetry")]
    for name in cached:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    with sink().span("llm.call", {"task_type": "probe"}) as span:
        span.set({"status": "ok"})
    assert fresh_sink._provider is None
    config_module.settings.otel_export = ""


def test_otlp_with_an_endpoint_enables_the_mode(fresh_sink):
    """A sane otlp configuration passes the gate (the exporter itself is
    exercised by the CI `--extra otel` step)."""
    import app.core.config as config_module

    config_module.settings.otel_export = "otlp"
    config_module.settings.otel_endpoint = "http://127.0.0.1:4318/v1/traces"
    assert fresh_sink._enabled_mode() == "otlp"
    config_module.settings.otel_export = ""
    config_module.settings.otel_endpoint = None


def test_env_console_path_exports_a_real_span(fresh_sink, monkeypatch):
    """CAREER_OTEL_EXPORT=console builds the sink's OWN provider and takes
    the tracer from it: a span driven through the env-built path lands on
    the exporter captured at that construction site — not via
    `use_processor` (plan 168 S4.2)."""
    if not _sdk_available():
        assert fresh_sink._provider is None
        return
    import opentelemetry.sdk.trace.export as export_module
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    monkeypatch.setattr(export_module, "ConsoleSpanExporter", lambda: exporter)
    monkeypatch.setattr(export_module, "BatchSpanProcessor", lambda exp: SimpleSpanProcessor(exp))
    import app.core.config as config_module

    config_module.settings.otel_export = "console"
    try:
        assert fresh_sink._provider is None, "inert until the env enables the sink"
        with sink().span("autopilot.node", {"node": "deliver", "kind": "deterministic"}) as span:
            span.set({"status": "ok", "latency_ms": 12})
        assert fresh_sink._tracer is not None, "the tracer comes from the built provider"
        fresh_sink.flush()
        spans = exporter.get_finished_spans()
        assert [s.name for s in spans] == ["autopilot.node"]
        assert spans[0].attributes["node"] == "deliver"
        assert spans[0].attributes["status"] == "ok"
    finally:
        config_module.settings.otel_export = ""


def test_env_otlp_path_builds_the_otlp_exporter(fresh_sink, monkeypatch):
    """CAREER_OTEL_EXPORT=otlp + endpoint builds an OTLPSpanExporter with
    the configured endpoint on the sink's own provider (plan 168 S4.2)."""
    import importlib.util

    if (
        importlib.util.find_spec("opentelemetry.sdk") is None
        or importlib.util.find_spec("opentelemetry.exporter.otlp") is None
    ):
        assert fresh_sink._provider is None
        return
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as otlp_module
    import opentelemetry.sdk.trace.export as export_module
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    built: dict = {}

    class StubExporter:
        def __init__(self, endpoint=None, **kwargs):
            built["endpoint"] = endpoint

        def export(self, _spans):
            from opentelemetry.sdk.trace.export import SpanExportResult

            return SpanExportResult.SUCCESS

        def force_flush(self, timeout_millis=None):
            return True

        def shutdown(self):
            return None

    monkeypatch.setattr(otlp_module, "OTLPSpanExporter", StubExporter)
    monkeypatch.setattr(export_module, "BatchSpanProcessor", lambda exp: SimpleSpanProcessor(exp))
    import app.core.config as config_module

    config_module.settings.otel_export = "otlp"
    config_module.settings.otel_endpoint = "http://127.0.0.1:4318/v1/traces"
    try:
        assert fresh_sink._provider is None, "inert until the env enables the sink"
        with sink().span("llm.call", {"task_type": "assist"}) as span:
            span.set({"status": "ok"})
        assert fresh_sink._tracer is not None, "the tracer comes from the built provider"
        assert built["endpoint"] == "http://127.0.0.1:4318/v1/traces"
    finally:
        config_module.settings.otel_export = ""
        config_module.settings.otel_endpoint = None
