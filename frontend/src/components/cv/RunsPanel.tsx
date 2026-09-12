import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { History } from "lucide-react";

import type { CvDocumentOut, CvPolishTrace, CvRunOut } from "@/types/cv";
import { fetchCvRuns } from "@/api/cv";
import {
  FlowTelemetryStrip,
  FlowTraceCard,
  PanelModal,
  type FlowTrace,
} from "@/components/ui";

/**
 * The live strip under the progress card's polish timeline (plan 65.5):
 * compact calls · tokens in/out · edits counters sourced from the
 * mirrored trace's run-linked LLM-call ledger. Mock-provider runs badge
 * themselves as simulated — the strip never pretends fake spend is real.
 */
export function RunTelemetryStrip({
  trace,
}: {
  trace?: CvPolishTrace | null;
}) {
  const { t } = useTranslation();
  const calls = trace?.llm_calls ?? [];
  if (calls.length === 0) return null;
  return (
    <div data-testid="cv-generate-telemetry">
      <FlowTelemetryStrip
      calls={calls.length}
      tokensIn={calls.reduce((sum, call) => sum + (call.tokens_in ?? 0), 0)}
      tokensOut={calls.reduce((sum, call) => sum + (call.tokens_out ?? 0), 0)}
      edits={(trace?.iterations ?? []).reduce(
        (sum, iteration) =>
          sum + (iteration.ops ?? []).filter((op) => op.ok).length,
        0,
      )}
      simulated={calls.every((call) => call.provider === "mock")}
      labels={{
        calls: t("cvBuilder.runs.telemetry.calls", "call(s)"),
        tokensIn: t("cvBuilder.runs.telemetry.tokensIn", "tokens in"),
        tokensOut: t("cvBuilder.runs.telemetry.tokensOut", "tokens out"),
        edits: t("cvBuilder.runs.telemetry.edits", "edits"),
        simulated: t("cvBuilder.runs.telemetry.simulated", "Simulated"),
      }}
      />
    </div>
  );
}

/**
 * Runs & metrics (plan 65.5): the CV's generation run + every polish
 * re-run, newest first, each expandable into the library `FlowTraceCard`
 * (stage timeline, per-call LLM ledger, ops ledger, coverage drops)
 * with per-run aggregates from `GET /cv/{id}/runs`. Presentational
 * mapping onto the library `FlowTrace` schema — the endpoint stays app
 * glue; mock-provider runs badge themselves as simulated.
 */
export function RunsPanelModal({
  open,
  onOpenChange,
  cv,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  cv: CvDocumentOut;
}) {
  const { t } = useTranslation();
  const [runs, setRuns] = useState<CvRunOut[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    setRuns(null);
    let cancelled = false;
    fetchCvRuns(cv.id)
      .then((data) => {
        if (!cancelled) setRuns(data);
      })
      .catch(() => {
        if (!cancelled) setError(t("cvBuilder.runs.error"));
      });
    return () => {
      cancelled = true;
    };
  }, [open, cv.id, t]);

  return (
    <PanelModal
      open={open}
      onOpenChange={onOpenChange}
      title={t("cvBuilder.runs.title")}
      data-testid="runs-panel"
    >
      <div
        className="max-h-[70vh] space-y-3 overflow-y-auto px-4 pb-4 pt-2"
        data-testid="cv-runs-list"
      >
        {error ? (
          <p role="alert" className="text-xs text-red-700">
            {error}
          </p>
        ) : runs === null ? (
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("cvBuilder.runs.loading")}
          </p>
        ) : runs.length === 0 ? (
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("cvBuilder.runs.empty")}
          </p>
        ) : (
          runs.map((run) => <RunRow key={run.job_id} run={run} />)
        )}
      </div>
    </PanelModal>
  );
}

function RunRow({ run }: { run: CvRunOut }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const trace = runTrace(run, t);
  return (
    <div
      className="rounded-[var(--as-radius)] border border-[var(--as-border)] p-3"
      data-testid="cv-run-row"
      data-run-type={run.job_type}
      data-run-status={run.status}
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
          data-testid="cv-run-toggle"
        >
          <History
            className="size-3.5 shrink-0 text-[var(--as-muted-fg)]"
            aria-hidden
          />
          <span className="text-xs font-medium">
            {t(`cvBuilder.runs.type.${run.job_type}`, { defaultValue: run.job_type })}
          </span>
          <span
            className="min-w-0 truncate text-[10px] text-[var(--as-muted-fg)]"
            data-testid="cv-runs-meta"
          >
            {t("cvBuilder.runs.meta", {
              calls: run.aggregate.calls,
              tokensIn: run.aggregate.tokens_in,
              tokensOut: run.aggregate.tokens_out,
            })}
            {run.final_version
              ? ` · ${t("cvBuilder.runs.finalVersion", { version: run.final_version })}`
              : ""}
          </span>
        </button>
        {run.outcome ? (
          <span
            className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
            data-testid="cv-runs-outcome"
          >
            {t(`cvGenerate.polishOutcome.${run.outcome}`, {
              defaultValue: run.outcome,
            })}
          </span>
        ) : null}
      </div>
      {expanded ? (
        <div className="mt-3 space-y-2" data-testid="cv-runs-detail">
          {run.error ? (
            <p
              role="alert"
              className="whitespace-pre-wrap break-words text-xs text-red-700"
            >
              {run.error}
            </p>
          ) : null}
          <FlowTraceCard
            trace={trace}
            labels={{
              title: t("cvBuilder.runs.traceTitle"),
              stages: t("cvBuilder.runs.stages"),
              calls: t("cvBuilder.runs.calls"),
              ops: t("cvBuilder.runs.ops"),
            }}
          />
          {(run.iterations ?? []).map((iteration) => {
            const labels = (iteration.coverage?.missing ?? []).map(
              (ref) => ref.label || ref.item_id,
            );
            if (labels.length === 0) return null;
            return (
              <p
                key={iteration.n}
                className="text-[10px] text-amber-700"
                data-testid="cv-runs-coverage"
              >
                {t("cvGenerate.polish.coverageDrops", {
                  items: labels.join(", "),
                })}
              </p>
            );
          })}
          {run.resumed_from ? (
            <p className="text-[10px] text-[var(--as-muted-fg)]">
              {t("cvBuilder.runs.chained")}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Map a run row onto the library `FlowTrace` schema (zero app joins there). */
function runTrace(
  run: CvRunOut,
  t: (key: string, opts?: Record<string, unknown>) => string,
): FlowTrace {
  return {
    stages: (run.stages ?? []).map((stage) => ({
      label: t(`cvBuilder.runs.stage.${stage.node}`, { defaultValue: stage.node }),
      note: stage.note ?? null,
      at: stage.at ?? null,
    })),
    llmCalls: run.llm_calls.map((call) => ({
      id: call.id,
      task: call.task,
      label: t(`cvBuilder.runs.task.${call.task}`, { defaultValue: call.task }),
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
        label: t(`cvBuilder.ops.${op.op}`, { defaultValue: op.op }),
        ok: Boolean(op.ok),
        detail: op.detail ?? null,
      })),
    ),
    outcome: run.outcome ?? null,
    outcomeLabel: run.outcome
      ? t(`cvGenerate.polishOutcome.${run.outcome}`, { defaultValue: run.outcome })
      : null,
    simulated:
      run.llm_calls.length > 0 &&
      run.llm_calls.every((call) => call.provider === "mock"),
  };
}
