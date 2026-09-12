import { describe, expect, it } from "vitest";

import {
  MAX_TRACE_SUMMARY,
  MAX_TRACE_TOOLS,
  isRunningRun,
  traceFromLiveTurn,
  traceFromRun,
  traceFromTurnMeta,
} from "@/lib/cvBuildTrace";

const localize = (key: string, value?: string) => `${key}→${value ?? ""}`;

describe("traceFromRun (65.2 mirror / 65.3 runs payload)", () => {
  const run = {
    job_id: "00000000-0000-0000-0000-000000000009",
    job_type: "cv_polish",
    status: "succeeded",
    stage: "polish.iterate",
    error: null as string | null,
    created_at: "2026-09-11T09:00:00Z",
    finished_at: "2026-09-11T09:02:30Z",
    outcome: "cap",
    resumed_from: "00000000-0000-0000-0000-000000000007",
    final_version: 3,
    stages: [
      { node: "collect", at: "2026-09-11T09:01:10Z" },
      { node: "polish", at: "2026-09-11T09:01:15Z", note: "pass 2 · density" },
    ],
    iterations: [
      {
        n: 1,
        ops: [
          { op: "move_block", ok: true, detail: "Languages section moved" },
          { op: "trim_summary", ok: false, detail: "bounds clamped" },
        ],
      },
    ],
    llm_calls: [
      {
        id: "00000000-0000-0000-0000-00000000000a",
        task: "cv_polish",
        stage: "polish.iterate",
        status: "ok",
        provider: "mock",
        model: "mock-gpt",
        prompt_version: "cv-polish@1",
        tokens_in: 900,
        tokens_out: 350,
        latency_ms: 2100,
      },
    ],
    aggregate: {
      calls: 1,
      tokens_in: 900,
      tokens_out: 350,
      latency_ms_sum: 2100,
      by_task: {},
    },
  };

  it("maps stages, camelCase call ledger and ✓/✗ ops onto FlowTrace", () => {
    const trace = traceFromRun(run);
    expect(trace.stages).toHaveLength(2);
    expect(trace.stages[0]).toEqual({
      label: "collect",
      note: null,
      at: "2026-09-11T09:01:10Z",
    });
    expect(trace.stages[1]?.note).toBe("pass 2 · density");
    expect(trace.llmCalls[0]).toMatchObject({
      id: "00000000-0000-0000-0000-00000000000a",
      task: "cv_polish",
      stage: "polish.iterate",
      status: "ok",
      provider: "mock",
      tokensIn: 900,
      tokensOut: 350,
      latencyMs: 2100,
    });
    expect(trace.toolOps).toEqual([
      { label: "move_block", ok: true, detail: "Languages section moved" },
      { label: "trim_summary", ok: false, detail: "bounds clamped" },
    ]);
    expect(trace.outcome).toBe("cap");
  });

  it("badges all-mock runs as simulated", () => {
    expect(traceFromRun(run).simulated).toBe(true);
    expect(
      traceFromRun({
        ...run,
        llm_calls: [{ ...run.llm_calls[0]!, provider: "openai" }],
      } as never).simulated,
    ).toBe(false);
  });

  it("localizes stage, task, op and outcome labels through the injected hook", () => {
    const trace = traceFromRun(run, localize);
    expect(trace.stages[0]?.label).toBe("cvBuilder.runs.stage.collect→collect");
    expect(trace.llmCalls[0]?.label).toBe("cvBuilder.runs.task.cv_polish→cv_polish");
    expect(trace.toolOps?.[0]?.label).toBe("cvBuilder.ops.move_block→move_block");
    expect(trace.outcomeLabel).toBe("cvGenerate.polishOutcome.cap→cap");
  });

  it("tolerates the running job's empty ledger rows", () => {
    const live = traceFromRun({ ...run, llm_calls: [], iterations: [], stages: [] }, localize);
    expect(live.stages).toEqual([]);
    expect(live.toolOps).toEqual([]);
    expect(live.simulated).toBe(false);
  });

  it("flags non-terminal rows as running for the live card", () => {
    expect(isRunningRun({ status: "running" } as never)).toBe(true);
    expect(isRunningRun({ status: "queued" } as never)).toBe(true);
    expect(isRunningRun({ status: "succeeded" } as never)).toBe(false);
    expect(isRunningRun({ status: "failed" } as never)).toBe(false);
    expect(isRunningRun({ status: "cancelled" } as never)).toBe(false);
  });
});

describe("traceFromTurnMeta (plan 66 persisted builder-turn metadata)", () => {
  const meta = {
    surface: "cv_builder",
    model: "mock-gpt",
    tokens_in: 1200,
    tokens_out: 420,
    elapsed_ms: 1930,
    nodes: [
      { id: "ground", label: "Reading the builder state", status: "done", start_ms: 0, duration_ms: 420 },
      { id: "generate", label: "Planning changes", status: "done", start_ms: 420, duration_ms: 1510 },
    ],
    tools: [
      {
        name: "get_builder_state",
        title: "Reading the draft",
        status: "done",
        args_summary: "cv_id=…",
        result_summary: "3 blocks, 1 proposal",
        start_ms: 30,
        duration_ms: 210,
      },
      {
        name: "plan_changes",
        status: "failed",
        args_summary: "window=summary",
      },
    ],
    operations: [{ op: "set_text", ok: true, detail: "Summary updated" }],
    stream_interrupted: false,
  };

  it("maps nodes to stages with duration notes and tools to ✓/✗ ops", () => {
    const trace = traceFromTurnMeta(meta as never);
    expect(trace.stages).toEqual([
      { label: "Reading the builder state", note: "420 ms", at: null },
      { label: "Planning changes", note: "1.5 s", at: null },
    ]);
    expect(trace.toolOps).toHaveLength(2);
    expect(trace.toolOps?.[0]).toEqual({
      label: "Reading the draft",
      ok: true,
      detail: "3 blocks, 1 proposal",
    });
    expect(trace.toolOps?.[1]?.ok).toBe(false);
    expect(trace.llmCalls).toHaveLength(1);
    expect(trace.llmCalls[0]).toMatchObject({
      id: "turn",
      model: "mock-gpt",
      tokensIn: 1200,
      tokensOut: 420,
      latencyMs: 1930,
    });
    expect(trace.outcome).toBe("completed");
  });

  it("maps an interrupted turn to error call status + interrupted outcome", () => {
    const trace = traceFromTurnMeta({ ...meta, stream_interrupted: true } as never);
    expect(trace.outcome).toBe("interrupted");
    expect(trace.llmCalls[0]?.status).toBe("error");
  });

  it("returns the empty trace for legacy metadata", () => {
    expect(traceFromTurnMeta(null)).toEqual({
      stages: [],
      llmCalls: [],
      outcome: null,
    });
    expect(traceFromTurnMeta({ referenced_job_codes: ["NO-1"] } as never)).toEqual({
      stages: [],
      llmCalls: [],
      toolOps: [],
      outcome: "completed",
      outcomeLabel: null,
      simulated: false,
    });
  });

  it("enforces the backend cap contract (≤16 tools, ≤160-char summaries)", () => {
    const overflow = {
      ...meta,
      tools: Array.from({ length: MAX_TRACE_TOOLS + 3 }, (_, index) => ({
        name: `tool_${index}`,
        status: "done",
        result_summary: "x".repeat(MAX_TRACE_SUMMARY + 20),
      })),
    };
    const trace = traceFromTurnMeta(overflow as never);
    expect(trace.toolOps).toHaveLength(MAX_TRACE_TOOLS);
    for (const op of trace.toolOps ?? []) {
      expect(op.detail?.length).toBe(MAX_TRACE_SUMMARY + 1);
    }
  });
});

describe("traceFromLiveTurn (library liveTurnReducer state, camelCase)", () => {
  const live = {
    status: "streaming",
    nodes: [
      { id: "ground", label: "Reading the builder state", status: "done" },
      { id: "generate", label: "Planning changes", status: "running" },
    ],
    toolCalls: [
      {
        name: "get_builder_state",
        title: "Reading the draft",
        status: "done",
        args: '{"selected": ["skills"]}',
        result: "3 blocks",
        durationMs: 210,
      },
      {
        name: "plan_changes",
        status: "running",
        args: "{}",
      },
    ],
    startedAt: 1000,
  };

  it("normalizes camelCase reducer state onto the same FlowTrace schema", () => {
    const trace = traceFromLiveTurn(live as never);
    expect(trace.stages).toEqual([
      { label: "Reading the builder state", note: null, at: null },
      { label: "Planning changes", note: "running", at: null },
    ]);
    expect(trace.toolOps?.[0]).toEqual({
      label: "Reading the draft",
      ok: true,
      detail: "3 blocks",
    });
    expect(trace.toolOps?.[1]?.ok).toBe(true);
    expect(trace.outcome).toBe("running");
    expect(trace.llmCalls).toEqual([]);
  });

  it("marks error turns and truncates oversize summaries", () => {
    const trace = traceFromLiveTurn({
      ...live,
      status: "error",
      error: { code: "timeout", message: "stream stalled" },
      toolCalls: [
        { name: "plan_changes", status: "failed", args: "a".repeat(200) },
      ],
    } as never);
    expect(trace.outcome).toBe("error");
    expect(trace.toolOps?.[0]).toEqual({
      label: "plan_changes",
      ok: false,
      detail: `${"a".repeat(160)}…`,
    });
  });

  it("caps the op results to the same 16-tool contract", () => {
    const trace = traceFromLiveTurn({
      status: "done",
      toolCalls: Array.from({ length: 20 }, (_, index) => ({
        name: `tool_${index}`,
        status: "done",
      })),
    });
    expect(trace.toolOps).toHaveLength(MAX_TRACE_TOOLS);
  });
});
