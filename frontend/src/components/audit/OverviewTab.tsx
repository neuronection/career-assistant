import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  fetchAuditBreakdown,
  fetchAuditOverview,
  fetchAuditTimeseries,
  type AuditBreakdownRow,
  type AuditOverview,
  type AuditRangeQuery,
  type AuditSeries,
} from "@/api/audit";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import {
  categoryRollup,
  formatBucketLabel,
  formatDelta,
  formatLatency,
  formatTokens,
  formatTokensExact,
} from "@/config/auditVocab";

const AUTO_REFRESH_MS = 30_000;

const CHART_COLORS = {
  calls: "var(--as-accent, #6172f3)",
  errors: "var(--as-danger, #e11d48)",
} as const;

function KpiTiles({ overview }: { overview: AuditOverview }) {
  const { t } = useTranslation();
  const tiles: StatTile[] = [
    {
      label: t("audit.kpi.calls"),
      value: overview.ai.calls.toLocaleString(),
      hint: t("audit.kpi.vsPrev", {
        delta: formatDelta(overview.ai.calls, overview.ai.prev_calls),
      }),
    },
    {
      label: t("audit.kpi.errorRate"),
      value: `${(overview.ai.error_rate * 100).toFixed(1)}%`,
      hint: t("audit.kpi.errorCount", { count: overview.ai.errors }),
    },
    {
      label: t("audit.kpi.tokens"),
      value: `${formatTokens(overview.ai.tokens_in)} → ${formatTokens(overview.ai.tokens_out)}`,
      hint: t("audit.kpi.tokensHint"),
      title: `${formatTokensExact(overview.ai.tokens_in)} → ${formatTokensExact(overview.ai.tokens_out)}`,
    },
    {
      label: t("audit.kpi.latency"),
      value: formatLatency(overview.ai.avg_latency_ms),
      hint: t("audit.kpi.latencyMax", {
        max: formatLatency(overview.ai.max_latency_ms),
      }),
    },
    {
      label: t("audit.kpi.failedJobs"),
      value: overview.jobs.failed.toLocaleString(),
      hint:
        overview.schedules.failing > 0
          ? t("audit.kpi.schedulesFailing", { count: overview.schedules.failing })
          : t("audit.kpi.schedulesOk"),
    },
    {
      label: t("audit.kpi.authDenied"),
      value: overview.auth.denied.toLocaleString(),
      hint: t("audit.kpi.authEvents", { count: overview.auth.events }),
    },
  ];
  return <StatTiles tiles={tiles} layout="auto" testId="audit-kpis" />;
}

function VolumeChart({ series }: { series: AuditSeries }) {
  const { t } = useTranslation();
  const data = series.points.map((point) => ({
    name: formatBucketLabel(point.bucket, series.bucket),
    calls: point.calls - point.errors,
    errors: point.errors,
  }));
  return (
    <div
      data-testid="audit-volume-chart"
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-[var(--as-fg)]">
          {t("audit.chart.volume")}
        </h3>
        <div className="flex gap-3 text-xs text-[var(--as-muted-fg)]">
          <span className="flex items-center gap-1">
            <span
              aria-hidden
              className="inline-block size-2 rounded-sm"
              style={{ background: CHART_COLORS.calls }}
            />
            {t("audit.chart.ok")}
          </span>
          <span className="flex items-center gap-1">
            <span
              aria-hidden
              className="inline-block size-2 rounded-sm"
              style={{ background: CHART_COLORS.errors }}
            />
            {t("audit.chart.errors")}
          </span>
        </div>
      </div>
      {data.length === 0 ? (
        <p className="py-10 text-center text-sm text-[var(--as-muted-fg)]">
          {t("audit.chart.empty")}
        </p>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--as-border)" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} width={44} />
              <Tooltip cursor={{ fill: "rgba(0,0,0,0.04)" }} />
              <Bar
                dataKey="calls"
                stackId="v"
                name={t("audit.chart.ok")}
                fill={CHART_COLORS.calls}
                radius={[3, 3, 0, 0]}
              />
              <Bar
                dataKey="errors"
                stackId="v"
                name={t("audit.chart.errors")}
                fill={CHART_COLORS.errors}
                radius={[3, 3, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function CategoryBreakdown({ rows }: { rows: AuditBreakdownRow[] }) {
  const { t } = useTranslation();
  const rollup = categoryRollup(rows);
  const max = Math.max(1, ...rollup.map((row) => row.calls));
  return (
    <div
      data-testid="audit-categories"
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
    >
      <h3 className="mb-3 text-sm font-semibold text-[var(--as-fg)]">
        {t("audit.chart.byCategory")}
      </h3>
      {rollup.length === 0 ? (
        <p className="py-8 text-center text-sm text-[var(--as-muted-fg)]">
          {t("audit.chart.empty")}
        </p>
      ) : (
        <ul className="space-y-2">
          {rollup.map((row) => (
            <li key={row.category} className="text-xs" data-testid="audit-category-row">
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="font-medium text-[var(--as-fg)]">
                  {t(`audit.category.${row.category}`)}
                </span>
                <span className="tabular-nums text-[var(--as-muted-fg)]">
                  {row.calls.toLocaleString()}
                  {row.errors > 0 && (
                    <span className="ml-1 text-rose-600">· {row.errors}</span>
                  )}
                </span>
              </div>
              <div
                role="presentation"
                className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--as-muted)]"
              >
                <div
                  className="h-full rounded-full bg-[var(--as-accent,var(--chart-1,#6172f3))]"
                  style={{ width: `${(row.calls / max) * 100}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RecentFailures({ overview }: { overview: AuditOverview }) {
  const { t } = useTranslation();
  return (
    <div
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
      data-testid="audit-failures"
    >
      <h3 className="mb-2 text-sm font-semibold text-[var(--as-fg)]">
        {t("audit.failures.title")}
      </h3>
      {overview.recent_failures.length === 0 ? (
        <p className="py-6 text-center text-sm text-[var(--as-muted-fg)]">
          {t("audit.failures.none")}
        </p>
      ) : (
        <ul className="divide-y divide-[var(--as-border)]">
          {overview.recent_failures.map((failure, index) => (
            <li
              key={`${failure.stream}-${index}`}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 text-sm"
              data-testid="audit-failure-row"
            >
              <span className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[11px] font-semibold text-[var(--as-muted-fg)]">
                {t(`audit.stream.${failure.stream}`)}
              </span>
              <span className="font-medium text-[var(--as-fg)]">{failure.title}</span>
              {failure.detail && (
                <span className="min-w-0 flex-1 truncate text-xs text-rose-600">
                  {failure.detail}
                </span>
              )}
              <span className="ml-auto whitespace-nowrap text-xs text-[var(--as-muted-fg)]">
                {new Date(failure.occurred_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The audit Overview tab: KPI tiles, volume/errors chart, category
 * breakdown and the recent-failure feed — all server-aggregated. The
 * time range is the page-level control (preset or custom). */
export function OverviewTab({
  range,
  refreshMs = AUTO_REFRESH_MS,
}: {
  range: AuditRangeQuery;
  /** Injectable for tests (repo poll-injection pattern). */
  refreshMs?: number;
}) {
  const { t } = useTranslation();
  const [overview, setOverview] = useState<AuditOverview | null>(null);
  const [series, setSeries] = useState<AuditSeries | null>(null);
  const [taskRows, setTaskRows] = useState<AuditBreakdownRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const [overviewData, seriesData, taskBreakdown] = await Promise.all([
        fetchAuditOverview(range),
        fetchAuditTimeseries(range),
        fetchAuditBreakdown("task", range),
      ]);
      if (id !== requestId.current) return;
      setOverview(overviewData);
      setSeries(seriesData);
      setTaskRows(taskBreakdown.rows);
    } catch (err) {
      if (id === requestId.current) setError(apiDetail(err));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(() => {
      void load();
    }, refreshMs);
    return () => clearInterval(timer);
  }, [autoRefresh, load, refreshMs]);

  if (loading && !overview) {
    return (
      <div className="flex w-full flex-col items-center justify-center py-24">
        <Spinner size="lg" />
        <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
      </div>
    );
  }
  if (error && !overview) {
    return <p className="text-sm text-rose-600">{error}</p>;
  }
  if (!overview || !series) return <EmptyState title={t("audit.empty")} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <button
          type="button"
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
            autoRefresh
              ? "border-[var(--as-accent,var(--chart-1,#6172f3))] text-[var(--as-accent,var(--chart-1,#6172f3))]"
              : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-muted-fg)]"
          }`}
          aria-pressed={autoRefresh}
          onClick={() => setAutoRefresh((value) => !value)}
          data-testid="audit-auto-refresh"
        >
          <RefreshCw className="size-3" aria-hidden />
          {t("audit.autoRefresh")}
        </button>
      </div>
      <KpiTiles overview={overview} />
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <VolumeChart series={series} />
        <CategoryBreakdown rows={taskRows} />
      </div>
      <RecentFailures overview={overview} />
    </div>
  );
}
