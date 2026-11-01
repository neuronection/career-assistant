/**
 * The shared run-detail body (plan 175 S3): the trace, graph strip,
 * AI calls, findings and timeline that both the quick-peek modal and the
 * `/autopilot/runs/:runId` page render. Extracted from plan 168's modal.
 */

import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { Link } from "react-router-dom";
import { ExternalLink, RotateCcw, Search, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";

import { Button } from "@/components/ui";
import type {
  AutopilotFinding,
  AutopilotRunDetail,
  AutopilotTraceStep,
} from "@/api/autopilot";
import { useAuthStore } from "@/stores/authStore";

export const RUN_STATUS_STYLE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700",
  budget_aborted: "bg-amber-50 text-amber-700",
  failed: "bg-red-50 text-red-700",
  cancelled: "bg-slate-100 text-slate-500",
  running: "bg-sky-50 text-sky-700",
};

export const RUN_STATUS_KEYS: Record<string, string> = {
  completed: "autopilot.runStatus.completed",
  budget_aborted: "autopilot.runStatus.budget_aborted",
  failed: "autopilot.runStatus.failed",
  cancelled: "autopilot.runStatus.cancelled",
  running: "autopilot.runStatus.running",
};

function scoreStyle(score: number): string {
  if (score >= 7) return "bg-emerald-50 text-emerald-700";
  if (score >= 5) return "bg-amber-50 text-amber-700";
  return "bg-slate-100 text-slate-600";
}

function scoreBorder(score: number): string {
  if (score >= 7) return "border-emerald-200";
  if (score >= 5) return "border-amber-200";
  return "border-slate-200";
}

export function FindingCard({
  finding,
  onFeedback,
}: {
  finding: AutopilotFinding;
  onFeedback?: (id: string, kind: "more_like_this" | "hide_like_this") => void;
}) {
  const dismissed = finding.dismissed_at != null;
  const { t } = useTranslation();
  return (
    <div
      className={`rounded-xl border bg-[var(--as-surface)] p-4 ${scoreBorder(finding.score)} ${
        dismissed ? "opacity-55" : ""
      }`}
      data-testid={`finding-${finding.id}`}
    >
      <div className="flex items-start gap-3">
        <div className="flex shrink-0 flex-col items-start gap-1">
          <span
            className={`rounded-lg px-2 py-1 text-sm font-semibold tabular-nums ${scoreStyle(finding.score)}`}
            title={t("autopilot.fitScore")}
          >
            {finding.score.toFixed(1)}
          </span>
          {finding.evidence?.must_coverage && finding.evidence.must_coverage.total > 0 && (
            <span
              className="rounded-lg bg-[var(--as-muted)] px-2 py-0.5 text-xs font-medium tabular-nums text-[var(--as-muted-fg)]"
              data-testid={`coverage-${finding.id}`}
            >
              {t("autopilot.mustHaves", {
                hits: finding.evidence.must_coverage.hits,
                total: finding.evidence.must_coverage.total,
              })}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            {finding.url ? (
              <a
                href={finding.url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-slate-900 hover:text-primary-700"
              >
                {finding.title}
                <ExternalLink className="ml-1 inline h-3 w-3 text-[var(--as-muted-fg)]" />
              </a>
            ) : (
              <span className="font-medium text-slate-900">{finding.title}</span>
            )}
            {finding.org && (
              <span className="text-xs text-[var(--as-muted-fg)]">{finding.org}</span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-700">{finding.why}</p>
          {(finding.evidence?.quotes ?? []).map((quote, index) => (
            <blockquote
              key={index}
              className="mt-2 border-l-2 border-[var(--as-accent)] pl-2 text-xs italic text-slate-500"
            >
              “{quote}”
            </blockquote>
          ))}
        </div>
        {onFeedback ? (
          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant={finding.feedback === "more_like_this" ? "default" : "ghost"}
              size="icon"
              aria-label={t("autopilot.moreLikeThis")}
              title={t("autopilot.moreLikeThis")}
              disabled={dismissed}
              onClick={() => onFeedback(finding.id, "more_like_this")}
              data-testid={`feedback-more-${finding.id}`}
            >
              <ThumbsUp className="h-4 w-4" />
            </Button>
            <Button
              variant={finding.feedback === "hide_like_this" ? "destructive" : "ghost"}
              size="icon"
              aria-label={t("autopilot.hideLikeThis")}
              title={t("autopilot.hideLikeThis")}
              onClick={() => onFeedback(finding.id, "hide_like_this")}
              data-testid={`feedback-hide-${finding.id}`}
            >
              <ThumbsDown className="h-4 w-4" />
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function Timeline({
  runId,
  entries,
}: {
  runId: string;
  entries: AutopilotRunDetail["timeline"];
}) {
  const { t } = useTranslation();
  return (
    <div
      className="mt-3 space-y-2 rounded-lg bg-[var(--as-muted)] p-3 text-xs text-slate-600"
      data-testid={`run-timeline-${runId}`}
    >
      <p className="font-medium text-[var(--as-muted-fg)]">
        {t("autopilot.timeline.title")}
      </p>
      {entries.map((entry, index) => {
        if (entry.step === "search") {
          return (
            <div key={index} className="flex items-start gap-2">
              <Search className="mt-0.5 h-3 w-3 shrink-0 text-[var(--as-muted-fg)]" />
              <span>
                <span className="font-medium">
                  {entry.query
                    ? `“${entry.query}”`
                    : t("autopilot.timeline.everythingOpen")}
                </span>
                {entry.rationale ? ` — ${entry.rationale}` : ""}
                {entry.found != null
                  ? ` · ${t("autopilot.timeline.found", { count: entry.found })}`
                  : ""}
                {entry.examined != null
                  ? ` · ${t("autopilot.timeline.examined", { count: entry.examined })}`
                  : ""}
                {entry.error
                  ? ` · ${t("autopilot.timeline.skipped", { error: entry.error })}`
                  : ""}
              </span>
            </div>
          );
        }
        if (entry.step === "replan") {
          return (
            <div key={index} className="flex items-start gap-2">
              <RotateCcw className="mt-0.5 h-3 w-3 shrink-0 text-[var(--as-muted-fg)]" />
              <span>
                <span className="font-medium">{t("autopilot.timeline.replanned")}</span>
                {entry.queries && entry.queries.length
                  ? ` — ${entry.queries.map((query) => `“${query}”`).join(", ")}`
                  : ""}
                {entry.error
                  ? ` · ${t("autopilot.timeline.skipped", { error: entry.error })}`
                  : ""}
              </span>
            </div>
          );
        }
        return (
          <div key={index} className="flex items-start gap-2">
            <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-[var(--as-muted-fg)]" />
            <span>
              {t("autopilot.timeline.kept", { count: entry.kept ?? 0 })}
              {entry.seen ? ` · ${t("autopilot.timeline.seen", { count: entry.seen })}` : ""}
              {entry.never ? ` · ${t("autopilot.timeline.neverTerms", { count: entry.never })}` : ""}
              {entry.cooldown ? ` · ${t("autopilot.timeline.cooldown", { count: entry.cooldown })}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

type NodeState = "done" | "aborted" | "skipped";

function nodeState(node: string, steps: AutopilotTraceStep[]): NodeState {
  const entries = steps.filter((entry) => entry.step === node);
  if (entries.length === 0) return "skipped";
  const last = entries[entries.length - 1];
  return last.abort ? "aborted" : "done";
}

function stepLabel(node: string): string {
  return i18next.t(`autopilot.runDetail.step.${node}`, { defaultValue: node });
}

function stepSummary(entry: AutopilotTraceStep): string {
  const t = i18next.t;
  const count = (value: unknown): number =>
    Array.isArray(value) ? value.length : Number(value ?? 0);
  const output = entry.output ?? {};
  switch (entry.step) {
    case "plan":
      return t("autopilot.runDetail.summary.plan", { count: count(output.variants) });
    case "search":
      return t("autopilot.runDetail.summary.search", {
        probes: count(output.searches),
        pool: count(output.pool),
      });
    case "filter":
      return t("autopilot.runDetail.summary.filter", {
        kept: Number(output.kept ?? 0),
        pool: count(output.pool),
      });
    case "evaluate":
      return t("autopilot.runDetail.summary.evaluate", { pool: count(output.pool) });
    case "replan":
      return t("autopilot.runDetail.summary.replan", { count: count(output.queries) });
    case "graph_sweep":
      return t("autopilot.runDetail.summary.graphSweep", {
        found: Number(output.found ?? 0),
        examined: Number(output.examined ?? 0),
      });
    case "budget_guard":
      return output.abort
        ? t("autopilot.runDetail.summary.guardAbort", { reason: String(output.abort) })
        : t("autopilot.runDetail.summary.guardTokens", {
            tokens: Number(output.tokens_used ?? 0),
          });
    case "curate":
      return t("autopilot.runDetail.summary.curate", { count: count(output.picked) });
    case "deliver":
      return t("autopilot.runDetail.summary.deliver", {
        count: count(output.findings),
        status: String(output.status ?? ""),
      });
    default:
      return "";
  }
}

export function durationLabel(run: {
  started_at: string | null;
  finished_at: string | null;
}): string {
  if (!run.started_at || !run.finished_at) return "";
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "";
  return i18next.t("autopilot.runDetail.duration", { seconds: Math.round(ms / 1000) });
}

export function dateLabel(value: string | null): string {
  if (!value) return "";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function RunDetail({
  detail,
  findingsFeedHref,
}: {
  detail: AutopilotRunDetail;
  /** When set, the findings section links into the feed filtered by run. */
  findingsFeedHref?: string;
}) {
  const { t } = useTranslation();
  const isAdmin = useAuthStore((state) => state.user?.is_admin ?? false);

  const planArgs = detail.steps.find((entry) => entry.step === "plan")?.args ?? null;

  return (
    <div className="space-y-5" data-testid="run-detail-body">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            RUN_STATUS_STYLE[detail.run.status] ?? "bg-slate-100 text-slate-600"
          }`}
        >
          {RUN_STATUS_KEYS[detail.run.status]
            ? t(RUN_STATUS_KEYS[detail.run.status])
            : detail.run.status}
        </span>
        <span className="text-xs text-[var(--as-muted-fg)]">
          {dateLabel(detail.run.created_at)}
          {detail.run.tokens_used
            ? ` · ${t("autopilot.tokens", { count: detail.run.tokens_used })}`
            : ""}
          {durationLabel(detail.run) ? ` · ${durationLabel(detail.run)}` : ""}
        </span>
        <p className="min-w-full text-sm font-medium text-slate-900">
          {detail.run.goal_text}
        </p>
        {detail.run.error && (
          <p className="min-w-full rounded-lg bg-rose-50 p-2 text-xs text-rose-700">
            {detail.run.error}
          </p>
        )}
      </div>

      {!detail.trace_available ? (
        <div data-testid="run-detail-fallback" className="space-y-3">
          <p className="rounded-lg bg-[var(--as-muted)] p-3 text-xs text-[var(--as-muted-fg)]">
            {t("autopilot.runDetail.unavailable")}
          </p>
          <Timeline runId={detail.run.id} entries={detail.timeline} />
        </div>
      ) : (
        <>
          <section className="space-y-1" data-testid="run-detail-inputs">
            <h3 className="text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("autopilot.runDetail.inputs")}
            </h3>
            {planArgs && (
              <div className="flex flex-wrap items-center gap-1 rounded-lg bg-[var(--as-muted)] p-2 text-xs text-[var(--as-muted-fg)]">
                {(Array.isArray(planArgs.constraints) ? planArgs.constraints : []).map(
                  (key) => (
                    <span
                      key={key}
                      className="rounded-full bg-[var(--as-surface)] px-2 py-0.5"
                    >
                      {key}
                    </span>
                  ),
                )}
                {(Array.isArray(planArgs.budget) ? planArgs.budget : []).map((key) => (
                  <span
                    key={key}
                    className="rounded-full bg-[var(--as-surface)] px-2 py-0.5"
                  >
                    {t("autopilot.runDetail.budgetKey", { key })}
                  </span>
                ))}
              </div>
            )}
            {planArgs && typeof planArgs.profile === "object" && planArgs.profile !== null && (
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("autopilot.runDetail.profile", {
                  parts: [
                    t("autopilot.runDetail.profileSkills", {
                      skills: Number((planArgs.profile as { skills?: number }).skills ?? 0),
                    }),
                    (planArgs.profile as { languages?: number }).languages != null
                      ? t("autopilot.runDetail.profileLanguages", {
                          count: Number(
                            (planArgs.profile as { languages?: number }).languages,
                          ),
                        })
                      : null,
                    (planArgs.profile as { stage?: string }).stage
                      ? t("autopilot.runDetail.profileStage", {
                          stage: (planArgs.profile as { stage?: string }).stage,
                        })
                      : null,
                  ]
                    .filter(Boolean)
                    .join(" · "),
                })}
              </p>
            )}
          </section>

          <section className="space-y-1" data-testid="run-detail-graph">
            <h3 className="text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("autopilot.runDetail.graph")}
            </h3>
            <div className="flex flex-wrap gap-1">
              {detail.nodes.map((node) => {
                const state = nodeState(node, detail.steps);
                return (
                  <span
                    key={node}
                    data-testid={`run-detail-node-${node}`}
                    data-state={state}
                    className={`rounded-full px-2 py-0.5 text-xs ${
                      state === "done"
                        ? "bg-emerald-50 text-emerald-700"
                        : state === "aborted"
                          ? "bg-amber-50 text-amber-700"
                          : "bg-slate-100 text-slate-400"
                    }`}
                  >
                    {stepLabel(node)}
                  </span>
                );
              })}
            </div>
          </section>

          <section className="space-y-1" data-testid="run-detail-steps">
            <h3 className="text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("autopilot.runDetail.steps")}
            </h3>
            <div className="space-y-1">
              {detail.steps.map((entry, index) => (
                <div key={`${entry.step}-${index}`}>
                  {entry.iteration > 1 &&
                    (index === 0 || detail.steps[index - 1].iteration < entry.iteration) && (
                      <div
                        className="mt-2 flex items-center gap-1 text-xs font-medium text-[var(--as-accent)]"
                        data-testid="run-detail-branch"
                      >
                        <RotateCcw className="h-3 w-3" />
                        {t("autopilot.runDetail.branch", { iteration: entry.iteration })}
                      </div>
                    )}
                  <div
                    className="rounded-lg border border-[var(--as-border)] px-3 py-1.5"
                    data-testid={`run-detail-step-${index}`}
                    data-step={entry.step}
                  >
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-medium text-slate-900">
                        {stepLabel(entry.step)}
                      </span>
                      <span className="tabular-nums text-[var(--as-muted-fg)]">
                        {t("autopilot.runDetail.ms", { ms: entry.duration_ms })}
                      </span>
                      <span className="text-slate-700">{stepSummary(entry)}</span>
                      {entry.abort && (
                        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">
                          {t("autopilot.runDetail.abortedAs", { reason: entry.abort })}
                        </span>
                      )}
                      {entry.error && (
                        <span className="text-rose-600">{entry.error}</span>
                      )}
                    </div>
                    <details className="mt-1" data-testid={`run-detail-step-detail-${index}`}>
                      <summary className="cursor-pointer text-[11px] text-[var(--as-muted-fg)]">
                        {t("autopilot.runDetail.args")}
                      </summary>
                      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md bg-[var(--as-muted)] p-2 font-mono text-[11px]">
                        {JSON.stringify(entry.args, null, 2)}
                      </pre>
                      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md bg-[var(--as-muted)] p-2 font-mono text-[11px]">
                        {JSON.stringify(entry.output, null, 2)}
                      </pre>
                    </details>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </>
      )}

      {detail.ai_calls.length > 0 && (
        <section className="space-y-1" data-testid="run-detail-calls">
          <h3 className="text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("autopilot.runDetail.calls")}
          </h3>
          <div className="space-y-1">
            {detail.ai_calls.map((call) => (
              <div
                key={call.id}
                className="flex flex-wrap items-center gap-2 rounded-lg bg-[var(--as-muted)] px-3 py-1.5 text-xs"
                data-testid={`run-detail-call-${call.id}`}
              >
                <span className="font-medium text-slate-900">
                  {call.run_stage ?? call.task_type}
                </span>
                <span className="text-[var(--as-muted-fg)]">
                  {call.provider}/{call.model}
                </span>
                <span className={call.status === "ok" ? "text-emerald-600" : "text-rose-600"}>
                  {call.status}
                </span>
                <span className="tabular-nums text-[var(--as-muted-fg)]">
                  {t("autopilot.tokens", { count: (call.tokens_in ?? 0) + (call.tokens_out ?? 0) })}
                </span>
                {call.latency_ms != null && (
                  <span className="tabular-nums text-[var(--as-muted-fg)]">
                    {t("autopilot.runDetail.ms", { ms: Math.round(call.latency_ms) })}
                  </span>
                )}
                {isAdmin && (
                  <a
                    href={`/settings/audit?tab=ai&detail=${call.id}`}
                    className="ml-auto text-[var(--as-accent)] hover:underline"
                    data-testid={`run-detail-call-link-${call.id}`}
                  >
                    {t("autopilot.runDetail.viewCall")}
                  </a>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="space-y-2" data-testid="run-detail-findings">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("autopilot.findings")}
          </h3>
          {findingsFeedHref && detail.findings.length > 0 ? (
            <Link
              to={findingsFeedHref}
              className="text-xs text-[var(--as-accent)] hover:underline"
              data-testid="run-findings-feed-link"
            >
              {t("autopilot.runDetail.viewInFeed")}
            </Link>
          ) : null}
        </div>
        {detail.findings.length === 0 ? (
          <p className="text-sm text-[var(--as-muted-fg)]">
            {t("autopilot.noSurvivors")}
          </p>
        ) : (
          detail.findings.map((finding) => (
            <FindingCard key={finding.id} finding={finding} />
          ))
        )}
      </section>
    </div>
  );
}
