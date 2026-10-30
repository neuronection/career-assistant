import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  fetchAuditBreakdown,
  fetchAuditProduction,
  fetchAuditTimeseries,
  type AuditProduction,
  type AuditRangeQuery,
  type AuditSeries,
} from "@/api/audit";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import {
  formatBucketLabel,
  formatLatency,
  formatTokens,
  formatTokensExact,
} from "@/config/auditVocab";

function ModelUsageCard({
  rows,
}: {
  rows: { key: string; calls: number; errors: number; tokens_in: number; tokens_out: number; avg_latency_ms?: number | null }[];
}) {
  const { t } = useTranslation();
  const max = Math.max(1, ...rows.map((row) => row.calls));
  return (
    <div
      data-testid="audit-model-usage"
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
    >
      <h3 className="mb-3 text-sm font-semibold text-[var(--as-fg)]">
        {t("audit.usage.models")}
      </h3>
      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-[var(--as-muted-fg)]">
          {t("audit.chart.empty")}
        </p>
      ) : (
        <ul className="space-y-3">
          {rows.map((row) => (
            <li key={row.key} className="text-xs" data-testid="audit-model-row">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="font-medium text-[var(--as-fg)]">{row.key}</span>
                <span
                  className="tabular-nums text-[var(--as-muted-fg)]"
                  title={`${formatTokensExact(row.tokens_in)} → ${formatTokensExact(row.tokens_out)} tokens`}
                >
                  {row.calls.toLocaleString()} ·{" "}
                  {t("audit.usage.tokensShort", {
                    tin: formatTokens(row.tokens_in),
                    tout: formatTokens(row.tokens_out),
                  })}{" "}
                  · {formatLatency(row.avg_latency_ms ?? null)}
                  {row.errors > 0 && (
                    <span className="ml-1 text-rose-600">
                      · {t("audit.usage.errors", { count: row.errors })}
                    </span>
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

function TokenTrendCard({ series }: { series: AuditSeries }) {
  const { t } = useTranslation();
  const data = series.points.map((point) => ({
    name: formatBucketLabel(point.bucket, series.bucket),
    tin: point.tokens_in,
    tout: point.tokens_out,
  }));
  const empty = data.every((point) => point.tin === 0 && point.tout === 0);
  return (
    <div
      data-testid="audit-token-trend"
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
    >
      <h3 className="mb-2 text-sm font-semibold text-[var(--as-fg)]">
        {t("audit.usage.tokenTrend")}
      </h3>
      {empty ? (
        <p className="py-10 text-center text-sm text-[var(--as-muted-fg)]">
          {t("audit.chart.empty")}
        </p>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--as-border)" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} width={48} />
              <Tooltip cursor={{ fill: "rgba(0,0,0,0.04)" }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar
                dataKey="tin"
                name={t("audit.usage.tokensIn")}
                fill="var(--as-accent,var(--chart-1,#6172f3))"
                radius={[3, 3, 0, 0]}
              />
              <Bar
                dataKey="tout"
                name={t("audit.usage.tokensOut")}
                fill="var(--as-success,var(--chart-2,#22a06b))"
                radius={[3, 3, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function ThroughputCards({ production }: { production: AuditProduction }) {
  const { t } = useTranslation();
  const tiles: StatTile[] = [
    {
      label: t("audit.usage.postingsIngested"),
      value: production.postings.ingested.toLocaleString(),
      hint: t("audit.usage.itemsSynced", {
        count: production.postings.ingested_items.toLocaleString(),
      }),
    },
    {
      label: t("audit.usage.skillsCreated"),
      value: (production.skills.created ?? 0).toLocaleString(),
      hint: t("audit.usage.skillsPromoted", {
        count:
          (production.skills.promoted ?? 0) + (production.skills.auto_promoted ?? 0),
      }),
    },
    {
      label: t("audit.usage.companiesCreated"),
      value: production.companies.created.toLocaleString(),
      hint: "",
    },
    {
      label: t("audit.usage.jobsPublished"),
      value: (production.catalog_jobs.by_status.published ?? 0).toLocaleString(),
      hint: t("audit.usage.jobsCreated", {
        count: production.catalog_jobs.created.toLocaleString(),
      }),
    },
  ];
  return (
    <div className="space-y-3">
      <StatTiles tiles={tiles} layout="auto" testId="audit-throughput-tiles" />
      <div className="grid gap-4 lg:grid-cols-2">
        <div
          className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
          data-testid="audit-posting-activity"
        >
          <h3 className="mb-3 text-sm font-semibold text-[var(--as-fg)]">
            {t("audit.usage.postingActivity")}
          </h3>
          <ActivityRows
            entries={Object.entries(production.postings.activity)}
            labelPrefix="audit.changes.actor"
          />
        </div>
        <div
          className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
          data-testid="audit-skill-events"
        >
          <h3 className="mb-3 text-sm font-semibold text-[var(--as-fg)]">
            {t("audit.usage.skillEvents")}
          </h3>
          <ActivityRows
            entries={Object.entries(production.skills)}
            labelPrefix="audit.changes.result"
          />
        </div>
      </div>
    </div>
  );
}

function ActivityRows({
  entries,
  labelPrefix,
}: {
  entries: [string, number][];
  labelPrefix: string;
}) {
  const { t } = useTranslation();
  const max = Math.max(1, ...entries.map(([, count]) => count));
  if (entries.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-[var(--as-muted-fg)]">
        {t("audit.usage.noActivity")}
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {entries.map(([key, count]) => (
        <li key={key} className="flex items-center gap-3 text-xs">
          <span className="w-28 flex-none text-[var(--as-fg)]">
            {t(`${labelPrefix}.${key}`, { defaultValue: key.replace(/_/g, " ") })}
          </span>
          <span
            role="presentation"
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--as-muted)]"
          >
            <span
              className="block h-full rounded-full bg-[var(--as-accent,var(--chart-1,#6172f3))]"
              style={{ width: `${(count / max) * 100}%` }}
            />
          </span>
          <span className="w-10 flex-none text-right tabular-nums text-[var(--as-muted-fg)]">
            {count.toLocaleString()}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The usage & throughput tab (plan 153): per-model AI usage, token
 * trends and content-production metrics — postings, skills, companies
 * and catalog jobs created or processed in the range. */
export function UsageTab({ range }: { range: AuditRangeQuery }) {
  const { t } = useTranslation();
  const [models, setModels] = useState<
    { key: string; calls: number; errors: number; tokens_in: number; tokens_out: number; avg_latency_ms?: number | null }[]
  >([]);
  const [series, setSeries] = useState<AuditSeries | null>(null);
  const [production, setProduction] = useState<AuditProduction | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const [modelBreakdown, seriesData, productionData] = await Promise.all([
        fetchAuditBreakdown("model", { ...range, limit: 60 }),
        fetchAuditTimeseries(range),
        fetchAuditProduction(range),
      ]);
      if (id !== requestId.current) return;
      setModels(modelBreakdown.rows);
      setSeries(seriesData);
      setProduction(productionData);
    } catch (err) {
      if (id === requestId.current) setError(apiDetail(err));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex w-full flex-col items-center justify-center py-24">
        <Spinner size="lg" />
        <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
      </div>
    );
  }
  if (error) return <p className="text-sm text-rose-600">{error}</p>;
  if (!production || !series) return <EmptyState title={t("audit.empty")} />;

  return (
    <div className="space-y-4" data-testid="audit-usage-tab">
      <ThroughputCards production={production} />
      <TokenTrendCard series={series} />
      <ModelUsageCard rows={models} />
    </div>
  );
}
