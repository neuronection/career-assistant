import type { FlowTrace } from "@/components/ui";
import type {
  ChatMessage,
} from "@/types";
import type { CvPolishTrace, CvRunCall, CvRunOut } from "@/types/cv";

/** i18next-shaped optional localizer; absent → backend keys pass through. */
export type TraceLocalize = (
  key: string,
  defaultValue?: string,
) => string;

/** Mirrors backend cap contract (plan 66): ≤16 tools, ≤160-char. */
export const MAX_TRACE_TOOLS = 16;
export const MAX_TRACE_SUMMARY = 160;

const identity = (value: string) => value;

function localizeWith(
  localizer: TraceLocalize | undefined,
  key: string,
  defaultValue: string,
): string {
  if (!localizer || localizer === identity) {
    return defaultValue;
  }
  return localizer(key, defaultValue);
}

function cap(value: string | undefined | null, limit = MAX_TRACE_SUMMARY): string | null {
  if (typeof value !== "string") return null;
  return value.length <= limit ? value : `${value.slice(0, limit)}…`;
}

function durationNote(ms?: number | null): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function emptyTrace(): FlowTrace {
  return { stages: [], llmCalls: [], outcome: null };
}

/** Map a `cv_generate`/`cv_polish` run row (plans 65.2/65.3) onto the
 * library `FlowTrace` schema (65.4) — the single render target for both
 * the run history (RunsPanel) and the builder's live Run card (plan 67),
 * fed by the mid-run mirror + the finished run's ledger. */
export function traceFromRun(
  run: Pick<
    CvRunOut,
    "job_type" | "status" | "error" | "stages" | "iterations" | "llm_calls" | "outcome" | "resumed_from"
  >,
  localizer?: TraceLocalize,
): FlowTrace {
  const t = localizer;
  return {
    stages: (run.stages ?? []).map((stage) => ({
      label: localizeWith(t, `cvBuilder.runs.stage.${stage.node}`, stage.node),
      note: stage.note ?? null,
      at: stage.at ?? null,
    })),
    llmCalls: (run.llm_calls ?? []).map((call) => ({
      id: call.id,
      task: call.task,
      label: localizeWith(t, `cvBuilder.runs.task.${call.task}`, call.task),
      stage: call.stage ?? null,
      status: call.status === "ok" ? "ok" : "error",
      provider: call.provider,
      model: call.model,
      promptVersion: call.prompt_version ?? null,
      tokensIn: call.tokens_in ?? null,
      tokensOut: call.tokens_out ?? null,
      latencyMs: call.latency_ms ?? null,
    })),
    toolOps: (run.iterations ?? []).flatMap((iteration) =>
      (iteration.ops ?? []).map((op) => ({
        label: localizeWith(t, `cvBuilder.ops.${op.op}`, op.op),
        ok: Boolean(op.ok),
        detail: op.detail ?? null,
      })),
    ),
    outcome: run.outcome ?? null,
    outcomeLabel: run.outcome
      ? localizeWith(
          t,
          `cvGenerate.polishOutcome.${run.outcome}`,
          run.outcome,
        )
      : null,
    simulated:
      (run.llm_calls ?? []).length > 0 &&
      (run.llm_calls ?? []).every((call) => call.provider === "mock"),
  };
}

/** Partial rows of a finished `CvRunOut` used by the live card flip. */
export function isRunningRun(run: Pick<CvRunOut, "status">): boolean {
  return run.status === "queued" || run.status === "running";
}

/** Adapter: the create-flow's polish mirror payload (`CvPolishTrace`,
 * mid-job result.polish) rides the same `FlowTrace` render target —
 * retires the app-local PolishTimeline (plan 67.5). */
export function traceFromPolishTrace(
  polish: Pick<
    CvPolishTrace,
    "outcome" | "llm_calls" | "iterations" | "run"
  > | undefined,
  localizer?: TraceLocalize,
): FlowTrace {
  if (!polish) {
    return emptyTrace();
  }
  return traceFromRun(
    {
      job_type: "cv_polish",
      status: "running",
      error: polish.outcome?.error ?? null,
      stages: polish.run?.stages ?? [],
      iterations: (polish.iterations ?? []) as CvRunOut["iterations"],
      llm_calls: (polish.llm_calls ?? []).map((call, index) => ({
        ...call,
        id: call.id ?? `call-${index}`,
      })) as CvRunCall[],
      outcome: polish.outcome?.status ?? null,
    },
    localizer,
  );
}

type TurnNode = NonNullable<NonNullable<ChatMessage["metadata_json"]>["nodes"]>[number];
type TurnTool = NonNullable<NonNullable<ChatMessage["metadata_json"]>["tools"]>[number];

/** Map a persisted copilot turn's `metadata_json` (plan 66) onto the
 * library `FlowTrace`: `nodes` → stages (duration in the note), the
 * per-call LLM ledger from model/tokens/elapsed, ops from `tools` with
 * caps mirrored from the backend contract. */
export function traceFromTurnMeta(
  meta: ChatMessage["metadata_json"],
): FlowTrace {
  if (!meta) return emptyTrace();
  const nodes = meta.nodes ?? [];
  const tools = (meta.tools ?? []).slice(0, MAX_TRACE_TOOLS);
  const interrupted = meta.stream_interrupted === true;
  const llmCalls =
    meta.model || meta.elapsed_ms || meta.tokens_out
      ? [
          {
            id: "turn",
            task: "copilot_turn",
            label: "Copilot turn",
            stage: null,
            status: interrupted ? ("error" as const) : ("ok" as const),
            provider: null,
            model: meta.model ?? null,
            promptVersion: null,
            tokensIn: meta.tokens_in ?? null,
            tokensOut: meta.tokens_out ?? null,
            latencyMs: meta.elapsed_ms ?? null,
          },
        ]
      : [];
  return {
    stages: nodes.map((node: TurnNode) => ({
      label: node.label ?? node.id,
      note: durationNote(node.duration_ms),
      at: null,
    })),
    llmCalls,
    toolOps: tools.map((tool: TurnTool) => ({
      label: tool.title ?? tool.name,
      ok: tool.status !== "failed",
      detail: cap(tool.result_summary ?? tool.args_summary ?? null),
    })),
    outcome: interrupted ? "interrupted" : "completed",
    outcomeLabel: null,
    simulated: false,
  };
}

/** Structural snapshot of the library live-turn reducer state
 * (`useChatStream`'s `stream.*`, camelCase). Ephemeral input — the
 * mapper normalizes it so the builder card and chat render the same
 * shape without a backend round-trip. */
export interface LiveTurnTraceInput {
  status?: "idle" | "pending" | "streaming" | "interrupted" | "done" | "error";
  nodes?: { id: string; label?: string; status: "pending" | "running" | "done" | "failed" | "interrupted" }[];
  toolCalls?: {
    name: string;
    title?: string;
    status: "running" | "done" | "failed";
    args?: string;
    result?: string;
    durationMs?: number;
  }[];
  startedAt?: number | null;
  finishedAt?: number | null;
  error?: { code: string; message: string } | null;
}

/** Map in-flight reducer state onto the same `FlowTrace` schema. */
export function traceFromLiveTurn(state: LiveTurnTraceInput): FlowTrace {
  const nodes = state.nodes ?? [];
  const tools = (state.toolCalls ?? []).slice(0, MAX_TRACE_TOOLS);
  const failed =
    state.status === "error" || (state.error != null && state.error.code !== "");
  return {
    stages: nodes.map((node) => ({
      label: node.label ?? node.id,
      note: node.status === "done" ? null : node.status,
      at: null,
    })),
    llmCalls: [],
    toolOps: tools.map((tool) => ({
      label: tool.title ?? tool.name,
      ok: tool.status !== "failed",
      detail: cap(tool.result ?? tool.args ?? null),
    })),
    outcome: failed ? "error" : state.status === "done" ? "completed" : "running",
    outcomeLabel: null,
    simulated: false,
  };
}
