import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import {
  fetchAuditFailures,
  fetchAuditJobs,
  requeueAuditJobs,
  type AuditFailuresPreview,
  type AuditFailureGroup,
  type AuditJobRow,
  type AuditRequeueOutcome,
  type FailureParams,
} from "@/api/audit";
import { apiDetail } from "@/api/client";
import { CopyButton, EmptyState, PanelModal, Spinner } from "@/components/ui";
import { rangeParams, type RangeValue } from "@/components/audit/RangeFilter";

const badgeClass =
  "rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-semibold text-rose-700";

export function parseFailureType(raw: string | null): string {
  return raw ?? "";
}

function requeueParams(range: RangeValue, jobType: string): FailureParams {
  const params: FailureParams = rangeParams(range);
  if (jobType) params.job_type = jobType;
  return params;
}

function GroupCard({
  group,
  expanded,
  jobs,
  jobsLoading,
  confirming,
  onToggle,
  onRequeue,
  onOpen,
}: {
  group: AuditFailureGroup;
  expanded: boolean;
  jobs: AuditJobRow[];
  jobsLoading: boolean;
  confirming: boolean;
  onToggle: () => void;
  onRequeue: () => void;
  onOpen: (job: AuditJobRow) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)]"
      data-testid={`audit-failure-group-${group.job_type}`}
    >
      <button
        type="button"
        className="flex w-full flex-wrap items-center gap-2 px-3 py-3 text-left"
        onClick={onToggle}
        aria-expanded={expanded}
        data-testid={`audit-failure-group-toggle-${group.job_type}`}
      >
        <span className="font-medium text-[var(--as-fg)]">
          {group.job_type.replace(/_/g, " ")}
        </span>
        <span className={badgeClass} data-testid="audit-failure-count">
          {t("audit.failures.count", { count: group.window_count })}
        </span>
        {group.full_rerun && (
          <span
            className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800"
            data-testid="audit-failure-full-rerun"
          >
            {t("audit.failures.fullRerun")}
          </span>
        )}
        {group.sweep && (
          <span
            className="rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-semibold text-sky-800"
            data-testid="audit-failure-sweep"
          >
            {t("audit.failures.sweep")}
          </span>
        )}
        <span className="ml-auto text-xs tabular-nums text-[var(--as-muted-fg)]">
          {expanded ? "▾" : "▸"}
        </span>
      </button>
      <p className="break-words px-3 pb-2 text-xs text-rose-600">{group.top_error}</p>
      {expanded && (
        <div className="border-t border-[var(--as-border)] px-3 py-2">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-[var(--as-muted-fg)]">
            <span data-testid={`audit-failure-est-${group.job_type}`}>
              {t("audit.failures.estJobs", { count: group.est_jobs })}
            </span>
            <button
              type="button"
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1 text-xs font-semibold text-[var(--as-fg)] disabled:opacity-40"
              disabled={confirming || group.est_jobs === 0}
              onClick={onRequeue}
              data-testid={`audit-failure-requeue-${group.job_type}`}
            >
              {t("audit.failures.requeueGroup")}
            </button>
          </div>
          {jobsLoading ? (
            <Spinner size="sm" />
          ) : jobs.length === 0 ? (
            <p className="py-2 text-xs text-[var(--as-muted-fg)]">{t("audit.jobs.empty")}</p>
          ) : (
            <ul className="divide-y divide-[var(--as-border)]">
              {jobs.map((job) => (
                <li key={job.id} className="py-1.5 text-xs" data-testid={`audit-failure-row-${job.id}`}>
                  <button
                    type="button"
                    className="w-full truncate text-left text-[var(--as-fg)] underline-offset-2 hover:underline"
                    onClick={() => onOpen(job)}
                    data-testid={`audit-failure-row-link-${job.id}`}
                  >
                    {new Date(job.created_at).toLocaleString()} · {job.attempts}/
                    {job.max_attempts}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export function FailuresJobDrawer({
  job,
  onClose,
  onRequeue,
  requeueBusy,
}: {
  job: AuditJobRow | null;
  onClose: () => void;
  onRequeue: (job: AuditJobRow) => void;
  requeueBusy: boolean;
}) {
  const { t } = useTranslation();
  return (
    <PanelModal
      open={job !== null}
      onOpenChange={(open) => !open && onClose()}
      title={job ? job.job_type.replace(/_/g, " ") : ""}
    >
      {job && (
        <div className="space-y-3 text-sm" data-testid="audit-failure-drawer">
          <div
            className="rounded-[var(--as-radius)] border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700"
            data-testid="audit-failure-drawer-error"
          >
            {job.error || "—"}
          </div>
          <dl className="space-y-1 text-xs" data-testid="audit-failure-drawer-meta">
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">{t("audit.jobs.colAttempts")}</dt>
              <dd className="tabular-nums">
                {job.attempts}/{job.max_attempts}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">{t("audit.jobs.colWhen")}</dt>
              <dd>{new Date(job.created_at).toLocaleString()}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">{t("audit.jobs.colUser")}</dt>
              <dd className="truncate">{job.user_email ?? "—"}</dd>
            </div>
          </dl>
          {job.payload && (
            <div>
              <div className="mb-1 flex items-center justify-between">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                  {t("audit.failures.payload")}
                </h4>
                <CopyButton value={JSON.stringify(job.payload, null, 2)} size={14} />
              </div>
              <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-all rounded-[var(--as-radius)] bg-[var(--as-muted)] p-2 text-[11px]">
                {JSON.stringify(job.payload, null, 2)}
              </pre>
            </div>
          )}
          <button
            type="button"
            className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm font-semibold text-[var(--as-fg)] disabled:opacity-40"
            disabled={requeueBusy}
            onClick={() => onRequeue(job)}
            data-testid="audit-failure-drawer-requeue"
          >
            {t("audit.failures.requeueRow")}
          </button>
        </div>
      )}
    </PanelModal>
  );
}

const EMPTY_GROUP_JOBS: AuditJobRow[] = [];

/** The Failures tab (plan 184): failed AI jobs grouped by type and error
 * family, with the confirmed bulk-requeue flow and per-row requeue. */
export function FailuresTab({ range }: { range: RangeValue }) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const jobType = parseFailureType(searchParams.get("job_type"));
  const [preview, setPreview] = useState<AuditFailuresPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState<
    { scope: "all" } | { scope: "group"; jobType: string } | null
  >(null);
  const [outcome, setOutcome] = useState<AuditRequeueOutcome | null>(null);
  const [acting, setActing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [groupJobs, setGroupJobs] = useState<AuditJobRow[]>(EMPTY_GROUP_JOBS);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [drawerJob, setDrawerJob] = useState<AuditJobRow | null>(null);
  const [rowMessage, setRowMessage] = useState("");
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const result = await fetchAuditFailures(requeueParams(range, jobType));
      if (id !== requestId.current) return;
      setPreview(result);
    } catch (err) {
      if (id === requestId.current) setError(apiDetail(err));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [range, jobType]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (
      !preview ||
      !jobType ||
      preview.groups.some((group) => group.job_type === jobType)
    )
      return;
    const next = new URLSearchParams(searchParams);
    next.delete("job_type");
    setSearchParams(next, { replace: true });
  }, [preview, jobType, searchParams, setSearchParams]);

  const loadGroupJobs = useCallback(
    async (type: string, currentRange: RangeValue) => {
      setJobsLoading(true);
      try {
        const result = await fetchAuditJobs({
          ...rangeParams(currentRange),
          status: "failed",
          job_type: type,
          limit: 20,
        });
        setGroupJobs(result.items);
      } catch {
        setGroupJobs(EMPTY_GROUP_JOBS);
      } finally {
        setJobsLoading(false);
      }
    },
    [],
  );

  const toggleGroup = (type: string) => {
    if (expanded === type) {
      setExpanded(null);
      return;
    }
    setExpanded(type);
    void loadGroupJobs(type, range);
  };

  const setType = (type: string) => {
    const next = new URLSearchParams(searchParams);
    if (type) next.set("job_type", type);
    else next.delete("job_type");
    setSearchParams(next, { replace: true });
    setExpanded(null);
    setOutcome(null);
  };

  const runRequeue = async (body: FailureParams & { job_ids?: string[] }) => {
    setActing(true);
    setError("");
    try {
      const result = await requeueAuditJobs({ ...body, confirm: true });
      if ("items" in result) setOutcome(result);
      setConfirming(null);
      setExpanded(null);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setActing(false);
    }
  };

  const requeueRow = async (job: AuditJobRow) => {
    setActing(true);
    setError("");
    try {
      const result = await requeueAuditJobs({
        job_ids: [job.id],
        confirm: true,
      });
      if ("items" in result) {
        const item = result.items.find((entry) => entry.job_id === job.id);
        setRowMessage(
          t(`audit.failures.outcome.${item?.outcome ?? "requeued"}`, {
            count: item?.outcome === "requeued" ? 1 : 0,
          }),
        );
        setDrawerJob(null);
        await load();
        if (expanded) await loadGroupJobs(expanded, range);
      }
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setActing(false);
    }
  };

  const totalEst = preview?.groups.reduce((sum, group) => sum + group.est_jobs, 0) ?? 0;

  return (
    <div className="space-y-4" data-testid="audit-failures-tab">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("audit.jobs.typeFilter")}
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]"
          value={jobType}
          onChange={(event) => setType(event.target.value)}
          data-testid="audit-failures-type"
        >
          <option value="">{t("audit.jobs.allTypes")}</option>
          {(preview?.groups ?? []).map((group) => (
            <option key={group.job_type} value={group.job_type}>
              {group.job_type.replace(/_/g, " ")} ({group.window_count})
            </option>
          ))}
        </select>
        <button
          type="button"
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm font-semibold disabled:opacity-40"
          disabled={loading || totalEst === 0}
          onClick={() => setConfirming({ scope: "all" })}
          data-testid="audit-failures-requeue-all"
        >
          {t("audit.failures.requeueAll", { count: totalEst })}
        </button>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}
      {rowMessage && (
        <p className="text-sm text-emerald-600" data-testid="audit-failures-row-outcome">
          {rowMessage}
        </p>
      )}

      {outcome && (
        <div
          className="rounded-[var(--as-radius-lg)] border border-emerald-300 bg-emerald-50 p-3 text-sm"
          data-testid="audit-failures-outcome"
        >
          <p className="font-semibold text-emerald-900">{t("audit.failures.outcomeTitle")}</p>
          <p className="text-xs text-emerald-800">
            {t("audit.failures.outcome.requeued", { count: outcome.requeued })} ·{" "}
            {t("audit.failures.outcome.skipped_dup", { count: outcome.skipped_dup })} ·{" "}
            {t("audit.failures.outcome.skipped_cap", { count: outcome.skipped_cap })}
            {outcome.collapsed > 0 &&
              ` · ${t("audit.failures.collapsed", { count: outcome.collapsed })}`}
          </p>
        </div>
      )}

      {confirming && preview && (
        <div
          className="rounded-[var(--as-radius-lg)] border border-amber-300 bg-amber-50 p-3 text-sm"
          data-testid="audit-failures-confirm"
        >
          <p className="mb-1 font-semibold text-amber-900">
            {t("audit.failures.confirmTitle")}
          </p>
          <p className="text-xs text-amber-800" data-testid="audit-failures-confirm-summary">
            {confirming.scope === "group"
              ? t("audit.failures.confirmGroup", {
                  count:
                    preview.groups.find((group) => group.job_type === confirming.jobType)
                      ?.est_jobs ?? 0,
                })
              : t("audit.failures.confirmAll", { count: totalEst })}
            {" · "}
            {t("audit.failures.confirmCap", { cap: preview.cap })}
            {preview.skipped_dup_preview > 0 &&
              ` · ${t("audit.failures.confirmDup", { count: preview.skipped_dup_preview })}`}
            {preview.truncated > 0 &&
              ` · ${t("audit.failures.confirmTruncated", { count: preview.truncated })}`}
          </p>
          <p className="mt-1 text-xs text-amber-800">
            {t("audit.failures.confirmFreshRows")}
          </p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
              disabled={acting}
              onClick={() =>
                confirming.scope === "group"
                  ? void runRequeue({
                      ...requeueParams(range, confirming.jobType),
                    })
                  : void runRequeue(requeueParams(range, ""))
              }
              data-testid="audit-failures-confirm-go"
            >
              {t("audit.failures.confirmGo")}
            </button>
            <button
              type="button"
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-1.5 text-xs"
              onClick={() => setConfirming(null)}
              data-testid="audit-failures-confirm-cancel"
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
        </div>
      ) : !preview || preview.groups.length === 0 ? (
        <EmptyState title={t("audit.failures.empty")} />
      ) : (
        <div className="space-y-2">
          {preview.groups.map((group) => (
            <GroupCard
              key={group.job_type}
              group={group}
              expanded={expanded === group.job_type}
              jobs={expanded === group.job_type ? groupJobs : EMPTY_GROUP_JOBS}
              jobsLoading={jobsLoading}
              confirming={acting}
              onToggle={() => toggleGroup(group.job_type)}
              onRequeue={() => setConfirming({ scope: "group", jobType: group.job_type })}
              onOpen={setDrawerJob}
            />
          ))}
          {preview.truncated > 0 && (
            <p className="text-xs text-[var(--as-muted-fg)]" data-testid="audit-failures-truncated">
              {t("audit.failures.truncated", { count: preview.truncated })}
            </p>
          )}
        </div>
      )}

      <FailuresJobDrawer
        job={drawerJob}
        onClose={() => setDrawerJob(null)}
        onRequeue={(job) => void requeueRow(job)}
        requeueBusy={acting}
      />

      <div
        className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
        data-testid="audit-failures-maintenance"
      >
        <h3 className="mb-2 text-sm font-semibold text-[var(--as-fg)]">
          {t("audit.failures.maintenance.title")}
        </h3>
        <ul className="space-y-1.5 text-xs text-[var(--as-muted-fg)]">
          <li>
            <Link
              to="/settings/ai"
              className="font-medium text-[var(--as-fg)] underline-offset-2 hover:underline"
            >
              {t("audit.failures.maintenance.embeddings")}
            </Link>{" "}
            — {t("audit.failures.maintenance.embeddingsHint")}
          </li>
          <li>
            <Link
              to="/settings/automations"
              className="font-medium text-[var(--as-fg)] underline-offset-2 hover:underline"
            >
              {t("audit.failures.maintenance.sweeps")}
            </Link>{" "}
            — {t("audit.failures.maintenance.sweepsHint")}
          </li>
        </ul>
      </div>
    </div>
  );
}
