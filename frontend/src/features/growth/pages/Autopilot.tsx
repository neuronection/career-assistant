import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { useSearchParams } from "react-router-dom";
import {
  Bot,
  CirclePause,
  CirclePlay,
  ExternalLink,
  Pencil,
  RotateCcw,
  Search,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from "lucide-react";
import {
  Button,
  ChipInput,
  ConfirmationModal,
  EmptyState,
  Modal,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
  PanelModal,
  Spinner,
} from "@/components/ui";
import { AiSetupPrompt } from "@/components/ai/AiSetupPrompt";
import {
  ChipTogglesRow,
  NumberField,
  SegmentedRow,
  StepperRow,
  TextareaField,
  ToggleRow,
} from "@/features/cv/components/cv/formPrimitives";
import {
  createGoal,
  deleteGoal,
  fetchFindingsByRun,
  fetchGoals,
  fetchRunDetail,
  patchGoal,
  runGoal,
  sendFindingFeedback,
} from "@/api/autopilot";
import { apiDetail } from "@/api/client";
import type {
  AutopilotConstraints,
  AutopilotFinding,
  AutopilotGoal,
  AutopilotRunDetail,
  AutopilotRunWithFindings,
  AutopilotTraceStep,
} from "@/api/autopilot";
import { useAuthStore } from "@/stores/authStore";

const SENIORITY_OPTIONS = [
  { value: "intern", labelKey: "autopilot.seniority.intern" },
  { value: "junior", labelKey: "autopilot.seniority.junior" },
  { value: "mid", labelKey: "autopilot.seniority.mid" },
  { value: "senior", labelKey: "autopilot.seniority.senior" },
];

const RUN_STATUS_STYLE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700",
  budget_aborted: "bg-amber-50 text-amber-700",
  failed: "bg-red-50 text-red-700",
  cancelled: "bg-slate-100 text-slate-500",
  running: "bg-sky-50 text-sky-700",
};

const RUN_STATUS_KEYS: Record<string, string> = {
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

function constraintChips(goal: AutopilotGoal): string[] {
  const t = i18next.t;
  const c = goal.constraints;
  const chips: string[] = [];
  for (const term of c.must_terms ?? [])
    chips.push(t("autopilot.chip.must", { term }));
  for (const term of c.never_terms ?? [])
    chips.push(t("autopilot.chip.never", { term }));
  if (c.remote) chips.push(t("autopilot.chip.remote"));
  if (c.salary_min)
    chips.push(t("autopilot.chip.salaryMin", { salary: c.salary_min.toLocaleString() }));
  for (const s of c.seniority ?? [])
    chips.push(t(`autopilot.seniority.${s}`, { defaultValue: s }));
  return chips;
}

function cadenceLabel(goal: AutopilotGoal): string {
  const t = i18next.t;
  const cadence = goal.cadence;
  if (!cadence) return t("autopilot.cadence.manual");
  if (cadence.type === "daily_at")
    return t("autopilot.cadence.dailyAt", { time: cadence.params.time ?? "" });
  if (cadence.type === "weekly") return t("autopilot.cadence.weekly");
  if (cadence.type === "interval")
    return t("autopilot.cadence.interval", {
      hours: Math.round(Number(cadence.params.every_minutes ?? 0) / 60),
    });
  return cadence.type;
}

function dateLabel(value: string | null): string {
  if (!value) return "";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface GoalDraft {
  goal_text: string;
  must_terms: string[];
  never_terms: string[];
  remote: boolean;
  salary_min: number | null;
  seniority: string[];
  cooldown_days: number;
  top_n: number;
  cadence: string;
}

function draftFromGoal(goal: AutopilotGoal | null): GoalDraft {
  const c: AutopilotConstraints = goal?.constraints ?? {
    must_terms: [],
    never_terms: [],
    family_keys: [],
    source_keys: [],
    remote: false,
    salary_min: null,
    seniority: [],
    exclude_seen: true,
    cooldown_days: 7,
    top_n: 5,
  };
  const cadence = goal?.cadence?.type ?? "manual";
  return {
    goal_text: goal?.goal_text ?? "",
    must_terms: [...(c.must_terms ?? [])],
    never_terms: [...(c.never_terms ?? [])],
    remote: c.remote ?? false,
    salary_min: c.salary_min ?? null,
    seniority: [...(c.seniority ?? [])],
    cooldown_days: c.cooldown_days ?? 7,
    top_n: c.top_n ?? 5,
    cadence: cadence === "daily_at" ? "daily" : cadence === "weekly" ? "weekly" : "manual",
  };
}

function GoalModal({
  open,
  goal,
  onClose,
  onSaved,
}: {
  open: boolean;
  goal: AutopilotGoal | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<GoalDraft>(() => draftFromGoal(goal));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const { t } = useTranslation();

  useEffect(() => {
    if (open) {
      setDraft(draftFromGoal(goal));
      setError(null);
    }
  }, [open, goal]);

  const save = async () => {
    if (draft.goal_text.trim().length < 3) {
      setError(t("autopilot.validation.goal"));
      return;
    }
    setSaving(true);
    setError(null);
    const cadence =
      draft.cadence === "daily"
        ? { type: "daily_at", params: { time: "08:00", timezone: "UTC" } }
        : draft.cadence === "weekly"
          ? { type: "weekly", params: { weekday: 0, time: "08:00", timezone: "UTC" } }
          : undefined;
    const constraints = {
      must_terms: draft.must_terms,
      never_terms: draft.never_terms,
      remote: draft.remote || null,
      salary_min: draft.salary_min,
      seniority: draft.seniority,
      cooldown_days: draft.cooldown_days,
      top_n: draft.top_n,
    };
    try {
      if (goal) {
        await patchGoal(goal.id, {
          goal_text: draft.goal_text.trim(),
          constraints,
          ...(cadence ? { cadence } : {}),
          ...(draft.cadence === "manual" && goal.cadence ? { remove_cadence: true } : {}),
        });
      } else {
        await createGoal({
          goal_text: draft.goal_text.trim(),
          constraints,
          cadence: cadence ?? null,
        });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <ModalContent size="md" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>
            {goal ? t("autopilot.modal.editTitle") : t("autopilot.modal.newTitle")}
          </ModalTitle>
        </ModalHeader>
        <div className="space-y-4 px-6 pb-2">
          <TextareaField
            label={t("autopilot.goalLabel")}
            value={draft.goal_text}
            onChange={(value) => setDraft({ ...draft, goal_text: value })}
            rows={3}
            maxLength={2000}
            counter
            placeholder={t("autopilot.goalPlaceholder")}
            testId="goal-text"
          />
          <div>
            <p className="mb-1 text-xs text-[var(--as-muted-fg)]">
              {t("autopilot.mustTerms")}
            </p>
            <ChipInput
              value={draft.must_terms}
              onChange={(value) => setDraft({ ...draft, must_terms: value })}
              placeholder={t("autopilot.chipPlaceholder")}
              inputLabel={t("autopilot.addMustTerm")}
              addLabel={t("common.add")}
              data-testid="goal-must-terms"
            />
          </div>
          <div>
            <p className="mb-1 text-xs text-[var(--as-muted-fg)]">
              {t("autopilot.neverTerms")}
            </p>
            <ChipInput
              value={draft.never_terms}
              onChange={(value) => setDraft({ ...draft, never_terms: value })}
              placeholder={t("autopilot.chipPlaceholder")}
              inputLabel={t("autopilot.addNeverTerm")}
              addLabel={t("common.add")}
              data-testid="goal-never-terms"
            />
          </div>
          <ChipTogglesRow
            label={t("autopilot.seniorityLabel")}
            values={draft.seniority}
            options={SENIORITY_OPTIONS.map((o) => ({
              value: o.value,
              label: t(o.labelKey),
            }))}
            onChange={(values) => setDraft({ ...draft, seniority: values })}
          />
          <div className="grid grid-cols-2 gap-3">
            <NumberField
              label={t("autopilot.minSalary")}
              value={draft.salary_min}
              onChange={(value) => setDraft({ ...draft, salary_min: value })}
              min={0}
              testId="goal-salary"
            />
            <StepperRow
              label={t("autopilot.shortlist")}
              value={draft.top_n}
              min={1}
              max={10}
              onChange={(value) => setDraft({ ...draft, top_n: value })}
            />
          </div>
          <ToggleRow
            label={t("autopilot.remoteOnly")}
            checked={draft.remote}
            onChange={(checked) => setDraft({ ...draft, remote: checked })}
          />
          <StepperRow
            label={t("autopilot.cooldown")}
            value={draft.cooldown_days}
            min={0}
            max={90}
            suffix={t("autopilot.cooldownSuffix")}
            onChange={(value) => setDraft({ ...draft, cooldown_days: value })}
          />
          <SegmentedRow
            label={t("autopilot.cadenceLabel")}
            value={draft.cadence}
            options={[
              { value: "manual", label: t("autopilot.cadenceOpt.manual") },
              { value: "daily", label: t("autopilot.cadenceOpt.daily") },
              { value: "weekly", label: t("autopilot.cadenceOpt.weekly") },
            ]}
            onChange={(value) => setDraft({ ...draft, cadence: value })}
          />
          {error && (
            <p className="text-xs text-red-600" role="alert" data-testid="goal-error">
              {error}
            </p>
          )}
        </div>
        <ModalFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={saving} data-testid="goal-save">
            {saving
              ? t("common.saving")
              : goal
                ? t("autopilot.saveChanges")
                : t("autopilot.createGoal")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

function FindingCard({
  finding,
  onFeedback,
}: {
  finding: AutopilotFinding;
  onFeedback: (id: string, kind: "more_like_this" | "hide_like_this") => void;
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
      </div>
    </div>
  );
}

function Timeline({ runId, entries }: { runId: string; entries: AutopilotRunWithFindings["searches_executed"] }) {
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

function durationLabel(run: { started_at: string | null; finished_at: string | null }): string {
  if (!run.started_at || !run.finished_at) return "";
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "";
  return i18next.t("autopilot.runDetail.duration", { seconds: Math.round(ms / 1000) });
}

function RunDetailModal({
  runId,
  onClose,
}: {
  runId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const isAdmin = useAuthStore((state) => state.user?.is_admin ?? false);
  const [detail, setDetail] = useState<AutopilotRunDetail | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    setDetail(null);
    setMissing(false);
    fetchRunDetail(runId)
      .then((result) => {
        if (live) setDetail(result);
      })
      .catch(() => {
        if (live) setMissing(true);
      });
    return () => {
      live = false;
    };
  }, [runId]);

  const planArgs =
    detail?.steps.find((entry) => entry.step === "plan")?.args ?? null;

  return (
    <PanelModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={<span className="truncate">{t("autopilot.runDetail.title")}</span>}
      size="xl"
      data-testid="run-detail-modal"
    >
      {missing ? (
        <p className="text-sm text-[var(--as-muted-fg)]" data-testid="run-detail-missing">
          {t("autopilot.runDetail.missing")}
        </p>
      ) : detail === null ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
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
                      skills: Number(
                        (planArgs.profile as { skills?: number }).skills ?? 0,
                      ),
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
                    <span
                      className={call.status === "ok" ? "text-emerald-600" : "text-rose-600"}
                    >
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
            <h3 className="text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("autopilot.findings")}
            </h3>
            {detail.findings.length === 0 ? (
              <p className="text-sm text-[var(--as-muted-fg)]">
                {t("autopilot.noSurvivors")}
              </p>
            ) : (
              detail.findings.map((finding) => (
                <FindingCard key={finding.id} finding={finding} onFeedback={() => undefined} />
              ))
            )}
          </section>
        </div>
      )}
    </PanelModal>
  );
}

export function Autopilot() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [goals, setGoals] = useState<AutopilotGoal[] | null>(null);
  const [runs, setRuns] = useState<AutopilotRunWithFindings[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AutopilotGoal | null>(null);
  const [deleting, setDeleting] = useState<AutopilotGoal | null>(null);
  const [busyGoal, setBusyGoal] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [openTimelines, setOpenTimelines] = useState<Set<string>>(new Set());
  const runParam = searchParams.get("run");

  const closeRun = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete("run");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const openRun = useCallback(
    (runId: string) => {
      const next = new URLSearchParams(searchParams);
      next.set("run", runId);
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  const load = useCallback(() => {
    void fetchGoals().then(setGoals).catch(() => setGoals([]));
    void fetchFindingsByRun().then(setRuns).catch(() => setRuns([]));
  }, []);

  useEffect(load, [load]);

  const runNow = async (goal: AutopilotGoal) => {
    setBusyGoal(goal.id);
    setNotice(null);
    try {
      const result = await runGoal(goal.id);
      setNotice(
        result.findings.length
          ? t("autopilot.notice.found", { count: result.findings.length })
          : t("autopilot.notice.quiet")
      );
      load();
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusyGoal(null);
    }
  };

  const togglePause = async (goal: AutopilotGoal) => {
    await patchGoal(goal.id, { status: goal.status === "active" ? "paused" : "active" }).catch(
      (err) => setNotice(apiDetail(err))
    );
    load();
  };

  const feedback = async (
    findingId: string,
    kind: "more_like_this" | "hide_like_this"
  ) => {
    try {
      const result = await sendFindingFeedback(findingId, kind);
      setNotice(
        result.goal_paused
          ? t("autopilot.notice.goalPaused")
          : result.learned_terms.length
            ? t("autopilot.notice.learned", { terms: result.learned_terms.join(", ") })
            : null
      );
      load();
    } catch (err) {
      setNotice(apiDetail(err));
    }
  };

  const toggleTimeline = (runId: string) => {
    setOpenTimelines((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  };

  const goalById = useMemo(() => {
    const map = new Map<string, AutopilotGoal>();
    for (const goal of goals ?? []) map.set(goal.id, goal);
    return map;
  }, [goals]);

  return (
    <div className="mx-auto max-w-4xl space-y-6" data-testid="autopilot-page">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <Bot className="h-6 w-6 text-primary-600" /> {t("autopilot.title")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {t("autopilot.subtitle")}
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
          data-testid="new-goal"
        >
          <Sparkles className="mr-1 h-4 w-4" /> {t("autopilot.newGoal")}
        </Button>
      </div>

      <AiSetupPrompt variant="banner" />

      {notice && (
        <div
          className="rounded-xl border border-[var(--as-border)] bg-[var(--as-muted)] px-4 py-2 text-sm text-slate-700"
          data-testid="autopilot-notice"
        >
          {notice}
        </div>
      )}

      {goals === null || runs === null ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : (
        <>
          {goals.length === 0 ? (
            <EmptyState
              title={t("autopilot.emptyTitle")}
              description={t("autopilot.emptyBody")}
              action={
                <Button
                  size="sm"
                  onClick={() => {
                    setEditing(null);
                    setModalOpen(true);
                  }}
                >
                  {t("autopilot.emptyAction")}
                </Button>
              }
            />
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {goals.map((goal) => (
                <div
                  key={goal.id}
                  className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
                  data-testid={`goal-card-${goal.id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="min-w-0 flex-1 text-sm font-medium text-slate-900">
                      {goal.goal_text}
                    </p>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
                        goal.status === "active"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-amber-50 text-amber-700"
                      }`}
                    >
                      {t(`autopilot.status.${goal.status}`, {
                        defaultValue: goal.status,
                      })}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {constraintChips(goal).map((chip) => (
                      <span
                        key={chip}
                        className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-xs text-[var(--as-muted-fg)]"
                      >
                        {chip}
                      </span>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-[var(--as-muted-fg)]">
                    {cadenceLabel(goal)}
                    {goal.last_run
                      ? ` · ${t("autopilot.lastRun", {
                          date: dateLabel(goal.last_run.created_at),
                        })}`
                      : ""}
                    {goal.open_findings
                      ? ` · ${t("autopilot.openCount", { count: goal.open_findings })}`
                      : ""}
                  </p>
                  <div className="mt-3 flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busyGoal === goal.id || goal.status !== "active"}
                      onClick={() => void runNow(goal)}
                      data-testid={`run-now-${goal.id}`}
                    >
                      {busyGoal === goal.id ? t("autopilot.searching") : t("autopilot.runNow")}
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={
                        goal.status === "active"
                          ? t("autopilot.pauseGoal")
                          : t("autopilot.resumeGoal")
                      }
                      title={
                        goal.status === "active"
                          ? t("autopilot.pauseGoal")
                          : t("autopilot.resumeGoal")
                      }
                      onClick={() => void togglePause(goal)}
                      data-testid={`pause-goal-${goal.id}`}
                    >
                      {goal.status === "active" ? (
                        <CirclePause className="h-4 w-4" />
                      ) : (
                        <CirclePlay className="h-4 w-4" />
                      )}
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={t("autopilot.editGoal")}
                      title={t("autopilot.editGoal")}
                      onClick={() => {
                        setEditing(goal);
                        setModalOpen(true);
                      }}
                      data-testid={`edit-goal-${goal.id}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={t("autopilot.deleteGoal")}
                      title={t("autopilot.deleteGoal")}
                      onClick={() => setDeleting(goal)}
                      data-testid={`delete-goal-${goal.id}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <section className="space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("autopilot.findings")}
            </h2>
            {(runs ?? []).length === 0 ? (
              <EmptyState
                title={t("autopilot.noRunsTitle")}
                description={t("autopilot.noRunsBody")}
              />
            ) : (
              (runs ?? []).map((run) => (
                <div
                  key={run.id}
                  className="rounded-2xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
                  data-testid={`run-${run.id}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${RUN_STATUS_STYLE[run.status] ?? "bg-slate-100 text-slate-600"}`}
                    >
                      {RUN_STATUS_KEYS[run.status]
                        ? t(RUN_STATUS_KEYS[run.status])
                        : run.status}
                    </span>
                    <span className="text-xs text-[var(--as-muted-fg)]">
                      {dateLabel(run.created_at)}
                      {run.goal_id && goalById.has(run.goal_id)
                        ? ` · ${goalById.get(run.goal_id)?.goal_text.slice(0, 48)}`
                        : ""}
                      {run.tokens_used ? ` · ${t("autopilot.tokens", { count: run.tokens_used })}` : ""}
                    </span>
                    <button
                      type="button"
                      className="ml-auto text-xs text-[var(--as-accent)] hover:underline"
                      onClick={() => toggleTimeline(run.id)}
                      data-testid={`timeline-toggle-${run.id}`}
                    >
                      {openTimelines.has(run.id)
                        ? t("autopilot.hideWork")
                        : t("autopilot.whatSearched")}
                    </button>
                    <button
                      type="button"
                      className="text-xs text-[var(--as-accent)] hover:underline"
                      onClick={() => openRun(run.id)}
                      data-testid={`run-details-${run.id}`}
                    >
                      {t("autopilot.runDetail.open")}
                    </button>
                  </div>
                  {openTimelines.has(run.id) && (
                    <Timeline runId={run.id} entries={run.searches_executed} />
                  )}
                  <div className="mt-3 space-y-2">
                    {run.findings.length === 0 ? (
                      <p className="text-sm text-[var(--as-muted-fg)]">
                        {t("autopilot.noSurvivors")}
                      </p>
                    ) : (
                      run.findings
                        .filter((finding) => finding.dismissed_at == null)
                        .map((finding) => (
                          <FindingCard
                            key={finding.id}
                            finding={finding}
                            onFeedback={(id, kind) => void feedback(id, kind)}
                          />
                        ))
                    )}
                  </div>
                </div>
              ))
            )}
          </section>
        </>
      )}

      <GoalModal
        open={modalOpen}
        goal={editing}
        onClose={() => setModalOpen(false)}
        onSaved={load}
      />

      {runParam && <RunDetailModal runId={runParam} onClose={closeRun} />}

      {deleting && (
        <ConfirmationModal
          open
          title={t("autopilot.deleteTitle")}
          description={t("autopilot.deleteBody")}
          confirmLabel={t("autopilot.delete")}
          onConfirm={() => {
            void deleteGoal(deleting.id).then(() => {
              setDeleting(null);
              load();
            });
          }}
          onOpenChange={(open) => (open ? undefined : setDeleting(null))}
        />
      )}
    </div>
  );
}
