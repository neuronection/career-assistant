import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  exportAuditCsv,
  fetchAuditJobFacets,
  fetchAuditJobs,
  fetchAuditSourceRuns,
  type AuditJobFacet,
  type AuditJobRow,
  type AuditSourceRunRow,
  type JobParams,
} from "@/api/audit";
import { fetchSystemSchedules } from "@/api/scheduler";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";
import { RangeFilter, rangeParams, type RangeValue } from "@/components/audit/RangeFilter";
import { downloadCsv } from "@/components/audit/download";

const PAGE_SIZE = 50;

const selectClass =
  "rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]";

const JOB_STATUSES = ["queued", "running", "succeeded", "failed", "cancelled"] as const;
const RUN_STATUSES = ["running", "ok", "degraded", "failed", "skipped"] as const;

function statusClass(status: string): string {
  if (status === "failed" || status === "cancelled") return "text-rose-600";
  if (status === "running") return "text-amber-600";
  return "text-emerald-600";
}

function JobDetail({ job }: { job: AuditJobRow }) {
  return (
    <div
      className="mx-2 mb-2 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)] p-3 text-xs"
      data-testid={`audit-job-detail-${job.id}`}
    >
      {job.error && <p className="mb-2 font-medium text-rose-600">{job.error}</p>}
      <p className="mb-2 text-[var(--as-muted-fg)]">
        {job.attempts}/{job.max_attempts} · {job.finished_at ? new Date(job.finished_at).toLocaleString() : "—"}
      </p>
      {job.payload && (
        <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-all rounded-[var(--as-radius)] bg-[var(--as-surface)] p-2 text-[11px]">
          {JSON.stringify(job.payload, null, 2)}
        </pre>
      )}
      {job.result && (
        <pre className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap break-all rounded-[var(--as-radius)] bg-[var(--as-surface)] p-2 text-[11px]">
          {JSON.stringify(job.result, null, 2)}
        </pre>
      )}
    </div>
  );
}

/** The jobs & runs tab (plan 152): admin-wide background jobs, the
 * cross-source ingestion ledger and a failing-schedules strip — read-only
 * by design, deep links to Automations and Sources for management. */
export function JobsTab() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("");
  const [jobType, setJobType] = useState("");
  const [range, setRange] = useState<RangeValue>({ window: "7d", from: "", to: "" });
  const [jobs, setJobs] = useState<AuditJobRow[]>([]);
  const [jobTotal, setJobTotal] = useState(0);
  const [jobPage, setJobPage] = useState(0);
  const [facets, setFacets] = useState<AuditJobFacet[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState("");
  const [runs, setRuns] = useState<AuditSourceRunRow[]>([]);
  const [runTotal, setRunTotal] = useState(0);
  const [failingSchedules, setFailingSchedules] = useState<
    { id: string; kind: string; consecutive_failures: number; error?: string | null }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const requestId = useRef(0);

  const load = useCallback(
    async (currentStatus: string, currentType: string, currentRange: RangeValue, page: number) => {
      const id = ++requestId.current;
      setLoading(true);
      setError("");
      try {
        const params: JobParams = {
          ...rangeParams(currentRange),
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        };
        if (currentStatus) params.status = currentStatus;
        if (currentType) params.job_type = currentType;
        const [jobsResult, facetsResult] = await Promise.all([
          fetchAuditJobs(params),
          fetchAuditJobFacets(rangeParams(currentRange)),
        ]);
        if (id !== requestId.current) return;
        setJobs(jobsResult.items);
        setJobTotal(jobsResult.total);
        setFacets(facetsResult.rows);
      } catch (err) {
        if (id === requestId.current) setError(apiDetail(err));
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(status, jobType, range, jobPage);
  }, [load, status, jobType, range, jobPage]);

  useEffect(() => {
    let live = true;
    const loadRuns = async () => {
      try {
        const params: { window: "7d"; status?: string; limit: number } = {
          window: "7d",
          limit: 25,
        };
        if (runStatus) params.status = runStatus;
        const result = await fetchAuditSourceRuns(params);
        if (!live) return;
        setRuns(result.items);
        setRunTotal(result.total);
      } catch {
        if (live) {
          setRuns([]);
          setRunTotal(0);
        }
      }
    };
    void loadRuns();
    return () => {
      live = false;
    };
  }, [runStatus]);

  useEffect(() => {
    let live = true;
    const loadSchedules = async () => {
      try {
        const schedules = await fetchSystemSchedules();
        if (!live) return;
        setFailingSchedules(
          schedules.filter((item) => item.enabled && item.consecutive_failures > 0),
        );
      } catch {
        if (live) setFailingSchedules([]);
      }
    };
    void loadSchedules();
    return () => {
      live = false;
    };
  }, []);

  const patch = (part: Partial<{ status: string; jobType: string; range: RangeValue }>) => {
    if ("status" in part) setStatus(part.status ?? "");
    if ("jobType" in part) setJobType(part.jobType ?? "");
    if ("range" in part) setRange(part.range ?? range);
    setJobPage(0);
    setExpanded(null);
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      downloadCsv(
        await exportAuditCsv("jobs", {
          ...rangeParams(range),
          status: status || undefined,
          job_type: jobType || undefined,
        }),
        "jobs",
      );
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setExporting(false);
    }
  };

  const pageCount = Math.max(1, Math.ceil(jobTotal / PAGE_SIZE));
  const from = jobTotal === 0 ? 0 : jobPage * PAGE_SIZE + 1;
  const to = Math.min(jobTotal, (jobPage + 1) * PAGE_SIZE);

  return (
    <div className="space-y-4" data-testid="audit-jobs-tab">
      {failingSchedules.length > 0 && (
        <div
          className="rounded-[var(--as-radius-lg)] border border-amber-300 bg-amber-50 p-3 text-sm"
          data-testid="audit-failing-schedules"
        >
          <p className="mb-1 font-semibold text-amber-900">
            {t("audit.jobs.schedulesFailing", { count: failingSchedules.length })}
          </p>
          <ul className="space-y-0.5 text-xs text-amber-800">
            {failingSchedules.map((schedule) => (
              <li key={schedule.id}>
                {schedule.kind} · {t("audit.jobs.failureStreak", { count: schedule.consecutive_failures })}
                {schedule.error ? ` · ${schedule.error}` : ""}
              </li>
            ))}
          </ul>
          <Link
            to="/settings/automations"
            className="mt-1 inline-block text-xs font-semibold text-amber-900 underline"
          >
            {t("audit.jobs.manageSchedules")} →
          </Link>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("audit.jobs.statusFilter")}
          className={selectClass}
          value={status}
          onChange={(e) => patch({ status: e.target.value })}
        >
          <option value="">{t("audit.jobs.allStatuses")}</option>
          {JOB_STATUSES.map((value) => (
            <option key={value} value={value}>
              {t(`audit.jobs.status.${value}`)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("audit.jobs.typeFilter")}
          className={selectClass}
          value={jobType}
          onChange={(e) => patch({ jobType: e.target.value })}
          data-testid="audit-jobs-type"
        >
          <option value="">{t("audit.jobs.allTypes")}</option>
          {facets.map((facet) => (
            <option key={facet.key} value={facet.key}>
              {facet.key.replace(/_/g, " ")} ({facet.count})
            </option>
          ))}
        </select>
        <RangeFilter value={range} onChange={(next) => patch({ range: next })} allowAllTime />
        <button
          type="button"
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm disabled:opacity-40"
          disabled={exporting}
          onClick={() => void exportCsv()}
          data-testid="audit-jobs-export"
        >
          {exporting ? t("audit.export.exporting") : t("audit.export.csv")}
        </button>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
        </div>
      ) : jobs.length === 0 ? (
        <EmptyState title={t("audit.jobs.empty")} />
      ) : (
        <div className="overflow-x-auto rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--as-border)] text-left text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                <th className="px-3 py-2">{t("audit.jobs.colStatus")}</th>
                <th className="px-3 py-2">{t("audit.jobs.colType")}</th>
                <th className="px-3 py-2">{t("audit.jobs.colUser")}</th>
                <th className="px-3 py-2">{t("audit.jobs.colAttempts")}</th>
                <th className="px-3 py-2">{t("audit.jobs.colWhen")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <Fragment key={job.id}>
                  <tr
                    className="cursor-pointer border-b border-[var(--as-border)] hover:bg-[var(--as-muted)] focus-visible:bg-[var(--as-muted)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--as-accent)]"
                    onClick={() => setExpanded(expanded === job.id ? null : job.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setExpanded(expanded === job.id ? null : job.id);
                      }
                    }}
                    tabIndex={0}
                    aria-expanded={expanded === job.id}
                    data-testid={`audit-job-row-${job.id}`}
                  >
                    <td className={`px-3 py-2 text-xs font-semibold ${statusClass(job.status)}`}>
                      {t(`audit.jobs.status.${job.status}`, { defaultValue: job.status })}
                      {expanded === job.id ? " ▾" : " ▸"}
                    </td>
                    <td className="px-3 py-2 font-medium text-[var(--as-fg)]">
                      {job.job_type.replace(/_/g, " ")}
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--as-muted-fg)]">
                      {job.user_email ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs tabular-nums text-[var(--as-muted-fg)]">
                      {job.attempts}/{job.max_attempts}
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--as-muted-fg)]">
                      {new Date(job.created_at).toLocaleString()}
                    </td>
                  </tr>
                  {expanded === job.id && (
                    <tr>
                      <td colSpan={5} className="p-0">
                        <JobDetail job={job} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
        <span data-testid="audit-jobs-range">
          {t("audit.ai.range", { from, to, total: jobTotal.toLocaleString() })}
        </span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
            disabled={jobPage === 0}
            onClick={() => setJobPage(jobPage - 1)}
          >
            ‹ {t("audit.prev")}
          </button>
          <span className="tabular-nums">
            {jobPage + 1} / {pageCount}
          </span>
          <button
            type="button"
            className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
            disabled={jobPage + 1 >= pageCount}
            onClick={() => setJobPage(jobPage + 1)}
          >
            {t("audit.next")} ›
          </button>
        </span>
      </div>

      <div className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-[var(--as-fg)]">
            {t("audit.jobs.sourceRuns")}
          </h3>
          <select
            aria-label={t("audit.jobs.runStatusFilter")}
            className={selectClass}
            value={runStatus}
            onChange={(e) => setRunStatus(e.target.value)}
          >
            <option value="">{t("audit.jobs.allStatuses")}</option>
            {RUN_STATUSES.map((value) => (
              <option key={value} value={value}>
                {t(`audit.jobs.runStatus.${value}`, { defaultValue: value })}
              </option>
            ))}
          </select>
        </div>
        {runs.length === 0 ? (
          <p className="py-6 text-center text-sm text-[var(--as-muted-fg)]">
            {t("audit.jobs.noRuns")}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--as-border)]" data-testid="audit-source-runs">
            <li className="pb-1 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("audit.jobs.runTotal", { total: runTotal.toLocaleString() })}
            </li>
            {runs.map((run) => (
              <li
                key={run.id}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 text-sm"
                data-testid="audit-source-run-row"
              >
                <span className={`text-xs font-semibold ${statusClass(run.status)}`}>
                  {t(`audit.jobs.runStatus.${run.status}`, { defaultValue: run.status })}
                </span>
                <Link
                  to={`/sources/${run.source_id}`}
                  className="font-medium text-[var(--as-fg)] underline-offset-2 hover:underline"
                >
                  {run.source_key ?? run.source_id.slice(0, 8)}
                </Link>
                <span className="text-xs text-[var(--as-muted-fg)]">
                  {t(`audit.jobs.trigger.${run.trigger}`)} · {run.items_synced} ·{" "}
                  {run.duration_ms ? `${Math.round(run.duration_ms / 100) / 10}s` : "—"}
                </span>
                {run.error && (
                  <span className="min-w-0 flex-1 truncate text-xs text-rose-600">{run.error}</span>
                )}
                <span className="ml-auto whitespace-nowrap text-xs text-[var(--as-muted-fg)]">
                  {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
