import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { History } from "lucide-react";

import type { CvRunOut } from "@/types/cv";
import { fetchCvRuns, polishCv } from "@/api/cv";
import { cancelBackgroundJob } from "@/api/backgroundJobs";
import {
  Button,
  FlowTelemetryStrip,
  FlowTraceCard,
} from "@/components/ui";
import { CopilotActivityCard } from "@/components/cv/CopilotActivityCard";
import { useCvLiveTurn } from "@/stores/cvBuilderLinkStore";
import { openCvChat } from "@/components/chat/cvChatLink";
import { isRunningRun, traceFromRun } from "@/lib/cvBuildTrace";

const POLL_MS = 2500;

/**
 * The builder page's build-progress slot (plan 67.3): the live copilot
 * activity card (67.2) and the CV's running generate/polish job take
 * turns in one slot — copilot turns win the full card while they run;
 * the running job stays visible as its telemetry strip until the turn
 * ends. Run data comes only from the jobs mirror (`GET /cv/{id}/runs`,
 * 65.2/65.3, polled at 2.5 s): the card never invents stages from chat
 * state. On completion it flips to the final trace of the run it
 * watched (trace card + Runs & metrics entry); full history stays in
 * the popup. `poke()` re-arms the poll after a user action so a new
 * job is picked up without another mount.
 */
export function BuildProgressCard({
  cvId,
  onOpenRuns,
  onRunFinished,
}: {
  cvId: string;
  onOpenRuns: () => void;
  onRunFinished?: () => void;
}) {
  const [runs, setRuns] = useState<CvRunOut[] | null>(null);
  const [watched, setWatched] = useState<string | null>(null);
  const [finalRun, setFinalRun] = useState<CvRunOut | null>(null);
  const [poll, setPoll] = useState(0);
  const watchedRef = useRef<string | null>(null);
  watchedRef.current = watched;
  const onFinishedRef = useRef(onRunFinished);
  onFinishedRef.current = onRunFinished;

  const poke = useCallback(() => {
    setPoll((value) => value + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const tick = async () => {
      const data = (await fetchCvRuns(cvId).catch(() => null)) ?? [];
      if (cancelled) {
        return;
      }
      setRuns(data);
      const active = data.find(isRunningRun);
      if (active) {
        setWatched(active.job_id);
        timer = window.setTimeout(() => void tick(), POLL_MS);
      } else {
        const lastWatched = watchedRef.current;
        if (lastWatched !== null) {
          const finished = data.find((row) => row.job_id === lastWatched);
          if (finished) {
            setFinalRun(finished);
            onFinishedRef.current?.();
          }
          setWatched(null);
        }
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [cvId, poll]);

  return <BuildProgressBody cvId={cvId} runs={runs} finalRun={finalRun} onOpenRuns={onOpenRuns} onPoke={poke} />;
}

export function BuildProgressBody({
  cvId,
  runs,
  finalRun,
  onOpenRuns,
  onPoke,
}: {
  cvId: string;
  runs: CvRunOut[] | null;
  finalRun: CvRunOut | null;
  onOpenRuns: () => void;
  onPoke: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const liveTurn = useCvLiveTurn(cvId);
  const activeRun = runs?.find(isRunningRun) ?? null;
  const askAssistant = () => {
    void openCvChat(cvId, "docked");
  };

  if (activeRun === null && finalRun === null) {
    return <CopilotActivityCard cvId={cvId} />;
  }

  const runRow = activeRun ?? finalRun!;
  const trace = traceFromRun(runRow);
  const stripOnly = liveTurn !== null && activeRun !== null;

  const cancel = async () => {
    if (activeRun === null || freeToState(activeRun.status) === false) {
      return;
    }
    setBusy(true);
    try {
      await cancelBackgroundJob(activeRun.job_id);
    } finally {
      setBusy(false);
      onPoke();
    }
  };

  const resume = async () => {
    if (finalRun === null || finalRun.status !== "failed") {
      return;
    }
    setBusy(true);
    try {
      await polishCv(cvId, finalRun.job_id);
    } finally {
      setBusy(false);
      onPoke();
    }
  };

  const stripLabels = {
    calls: t("cvBuilder.runs.telemetry.calls", "call(s)"),
    tokensIn: t("cvBuilder.runs.telemetry.tokensIn", "tokens in"),
    tokensOut: t("cvBuilder.runs.telemetry.tokensOut", "tokens out"),
    edits: t("cvBuilder.runs.telemetry.edits", "edits"),
    simulated: t("cvBuilder.runs.telemetry.simulated", "Simulated"),
  };

  const headerRow = (row: CvRunOut, testId: string) => (
    <div className="flex items-center gap-2">
      <span className="min-w-0 flex-1 truncate text-xs font-medium" data-testid={testId}>
        {t(`cvBuilder.runs.type.${row.job_type}`, { defaultValue: row.job_type })}
      </span>
      {isRunningRun(row) ? (
        <span
          className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
          data-testid="cv-run-progress-status"
        >
          {t(`cvBuilder.runs.liveStatus.${row.status}`, { defaultValue: row.status })}
        </span>
      ) : (
        <span
          className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
          data-testid="cv-run-final-status"
        >
          {row.outcome
            ? t(`cvGenerate.polishOutcome.${row.outcome}`, { defaultValue: row.outcome })
            : row.status}
        </span>
      )}
    </div>
  );

  const telemetry = (row: CvRunOut | null) => {
    const calls = row?.llm_calls ?? [];
    if (calls.length === 0) {
      return null;
    }
    return (
      <FlowTelemetryStrip
        calls={calls.length}
        tokensIn={calls.reduce((sum, call) => sum + (call.tokens_in ?? 0), 0)}
        tokensOut={calls.reduce((sum, call) => sum + (call.tokens_out ?? 0), 0)}
        edits={(row?.iterations ?? []).reduce(
          (sum, iteration) => sum + (iteration.ops ?? []).filter((op) => op.ok).length,
          0,
        )}
        simulated={calls.every((call) => call.provider === "mock")}
        labels={stripLabels}
      />
    );
  };

  return (
    <div className="space-y-2" data-testid="cv-build-progress">
      <CopilotActivityCard cvId={cvId} />
      <div
        className="rounded-[var(--as-radius)] border border-[var(--as-border)] p-3"
        data-testid={activeRun !== null ? "cv-run-progress" : "cv-run-final"}
        data-run-type={runRow.job_type}
      >
        {headerRow(runRow, activeRun !== null ? "cv-run-progress-title" : "cv-run-final-title")}
        <div className="mt-2" data-testid="cv-run-telemetry">
          {telemetry(runRow)}
        </div>
      </div>
      {stripOnly ? null : (
        <>
          <FlowTraceCard
            trace={trace}
            labels={{
              title: t("cvBuilder.runs.traceTitle"),
              stages: t("cvBuilder.runs.stages"),
              calls: t("cvBuilder.runs.calls"),
              ops: t("cvBuilder.runs.ops"),
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            {finalRun?.status === "failed" ? (
              <Button variant="outline" size="sm" onClick={() => void resume()} disabled={busy} data-testid="cv-run-resume">
                {t("cvBuilder.runs.resume", "Resume run")}
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" onClick={askAssistant} data-testid="cv-build-ask-assistant">
              {t("cvBuilder.copilotActivity.askAssistant", "Ask the assistant")}
            </Button>
            <Button variant="ghost" size="sm" onClick={onOpenRuns} data-testid="cv-run-open-runs">
              <History className="size-3.5" aria-hidden />
              {t("cvBuilder.runs.openAll", "Open runs & metrics")}
            </Button>
          </div>
        </>
      )}
      {activeRun !== null ? (
        <Button variant="outline" size="sm" onClick={() => void cancel()} disabled={busy} data-testid="cv-run-cancel">
          {t("cvBuilder.runs.cancel", "Cancel run")}
        </Button>
      ) : null}
    </div>
  );
}

function freeToState(status: string): boolean {
  return status === "queued" || status === "running";
}
