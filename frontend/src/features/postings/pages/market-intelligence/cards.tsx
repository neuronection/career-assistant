import { useTranslation } from "react-i18next";
import { EmptyState, RangeBar, SearchableDropdown, SegmentedTabs } from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import { ChartExport } from "@/components/stats/charts/ChartExport";
import { ChartCard } from "@/components/stats/charts/chartKit";
import { DeltaBadge } from "@/components/stats/charts/DeltaBadge";
import {
  TimeSeriesChart,
  TimeSeriesLegend,
  seriesRows,
} from "@/components/stats/charts/TimeSeriesChart";
import { BreakdownBars } from "@/components/stats/charts/BreakdownBars";
import { SkillTrendList } from "@/components/stats/charts/SkillTrendList";
import { ScatterQuadrant } from "@/components/stats/charts/ScatterQuadrant";
import { DonutChart } from "@/components/stats/charts/DonutChart";
import type { CsvRows } from "@/components/stats/statsExport";
import {
  CSV_HEADER_VOLUME,
  breakdownCsv,
  companiesCsv,
  salaryCsv,
  skillsCsv,
  volumeCsv,
} from "./exportRows";
import { formatCurrency, formatDateTime, formatNumber } from "@/lib/format";
import type {
  CompanyStatsOverview,
  CompanyStatsSummary,
  MarketCardError,
  MarketDimension,
  PostingStatsBreakdown,
  PostingStatsOverview,
  PostingStatsSalary,
  PostingStatsSkills,
  PostingStatsSummary,
  PostingStatsTimeseries,
  SalaryCurrency,
  TimeseriesSplit,
} from "@/api/stats";
import { MARKET_DIMENSIONS, type MarketStatsView } from "../marketStatsParams";

const QUADRANT_MAX = 30;

export const DRILLABLE: Partial<Record<MarketDimension, boolean>> = {
  seniority: true,
  work_mode: true,
  source: true,
  org: true,
  contract: true,
  education: true,
};

function percent(share: number): number {
  return Math.round(share * 100);
}

export function NoData() {
  const { t } = useTranslation();
  return <EmptyState compact title={t("marketStats.noData")} />;
}

export function StatusMix({ overview }: { overview: PostingStatsOverview }) {
  const { t } = useTranslation();
  const entries = Object.entries(overview.status_mix).filter(([, count]) => count > 0);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (entries.length === 0) {
    return <p className="mt-2 text-xs text-[var(--as-muted-fg)]">{t("marketStats.noData")}</p>;
  }
  return (
    <div
      className="mt-3 flex h-2 overflow-hidden rounded-full bg-[var(--as-muted)]"
      role="presentation"
      data-testid="market-stats-status-mix"
    >
      {entries.map(([status, count]) => (
        <div
          key={status}
          style={{
            width: `${total > 0 ? (count / total) * 100 : 0}%`,
            background: STATUS_COLORS[status] ?? "var(--chart-3, #f97316)",
          }}
          title={t(`marketStats.value.${status}`, { defaultValue: status })}
        />
      ))}
    </div>
  );
}

const STATUS_COLORS: Record<string, string> = {
  mapped: "var(--as-accent, var(--chart-1, #6172f3))",
  created: "var(--chart-2, #22c55e)",
  unmapped: "var(--chart-4, #f59e0b)",
  expired: "var(--as-muted-fg)",
  hidden: "var(--chart-5, #ef4444)",
};

export function Freshness({ summary }: { summary: PostingStatsSummary }) {
  const { t } = useTranslation();
  return (
    <>
      <span data-testid="stats-freshness-asof">
        {t("marketStats.freshness.asOf", {
          date: formatDateTime(summary.freshness.as_of),
        })}
      </span>
      {summary.freshness.stale_sources.length > 0 ? (
        <span className="text-[var(--as-warning)]" data-testid="stats-freshness-stale">
          {t("marketStats.freshness.stale", {
            sources: summary.freshness.stale_sources
              .map((source) => source.source_key)
              .join(", "),
          })}
        </span>
      ) : null}
    </>
  );
}

export function PulseTiles({
  summary,
  loading,
  error,
  onRetry,
  onDrill,
  onDrillOpen,
}: {
  summary: PostingStatsSummary | null;
  loading: boolean;
  error: MarketCardError | null;
  onRetry?: () => void;
  onDrill: (params: string) => void;
  onDrillOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <ChartCard
      title={t("marketStats.tiles.title")}
      testId="pulse"
      loading={loading}
      error={error}
      onRetry={onRetry}
    >
      {summary ? (
        <StatTiles
          tiles={[
            {
              label: t("marketStats.tiles.new24h"),
              value: formatNumber(summary.new_24h.count),
              hint: <DeltaBadge delta={summary.new_24h} />,
              onClick: () => onDrill("posted_within=24h"),
            },
            {
              label: t("marketStats.tiles.new7d"),
              value: formatNumber(summary.new_7d.count),
              hint: <DeltaBadge delta={summary.new_7d} />,
              onClick: () => onDrill("posted_within=7d"),
            },
            {
              label: t("marketStats.tiles.new30d"),
              value: formatNumber(summary.new_30d.count),
              hint: <DeltaBadge delta={summary.new_30d} />,
              sparkline: summary.sparkline,
              onClick: () => onDrill("posted_within=30d"),
            },
            {
              label: t("marketStats.tiles.openTotal"),
              value: formatNumber(summary.open_total),
              onClick: onDrillOpen,
            },
          ]}
          testId="market-stats-kpis"
          layout="auto"
          columns={4}
        />
      ) : (
        <NoData />
      )}
    </ChartCard>
  );
}

export function OverviewCard({
  overview,
  loading,
  error,
  onRetry,
  onDrill,
}: {
  overview: PostingStatsOverview | null;
  loading: boolean;
  error: MarketCardError | null;
  onRetry?: () => void;
  onDrill: (params: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <ChartCard
      title={t("marketStats.cards.overview")}
      testId="overview"
      loading={loading}
      error={error}
      onRetry={onRetry}
    >
      {overview ? (
        <>
          <StatTiles
            layout="auto"
            columns={2}
            testId="market-stats-overview"
            tiles={[
              {
                label: t("marketStats.tiles.newInRange"),
                value: formatNumber(overview.new_in_range.count),
                hint: <DeltaBadge delta={overview.new_in_range} />,
                onClick: () => onDrill(""),
              },
              {
                label: t("marketStats.tiles.openTotal"),
                value: formatNumber(overview.open_total),
              },
            ]}
          />
          <StatusMix overview={overview} />
        </>
      ) : (
        <NoData />
      )}
    </ChartCard>
  );
}

export interface ComparePoint {
  name: string;
  count: number;
  prev: number;
  series: Record<string, number>;
  compare?: number;
}

export interface CompareOverlay {
  points: ComparePoint[];
  cropped: number;
  padded: number;
}

export function VolumeCard({
  series,
  view,
  overlay,
  hint,
  loading,
  error,
  onRetry,
  onSplit,
  compact,
}: {
  series: PostingStatsTimeseries | null;
  view: MarketStatsView;
  overlay: CompareOverlay | null;
  hint: string | null;
  loading: boolean;
  error: MarketCardError | null;
  onRetry?: () => void;
  onSplit: (split: TimeseriesSplit | "") => void;
  compact: boolean;
}) {
  const { t } = useTranslation();
  const rows: CsvRows = series ? volumeCsv(series) : [];
  const splitItems = [
    { value: "", label: t("marketStats.split.none") },
    ...(["status", "source", "work_mode", "seniority", "employment"] as TimeseriesSplit[]).map(
      (value) => ({ value, label: t(`marketStats.split.${value}`) }),
    ),
  ];
  return (
    <ChartCard
      title={t("marketStats.cards.volume")}
      subtitle={t("marketStats.cards.volumeHint")}
      testId="volume"
      loading={loading}
      error={error}
      onRetry={onRetry}
      compact={compact}
      asOf={series ? formatDateTime(series.as_of) : undefined}
      table={
        series
          ? {
              caption: t("marketStats.table.volume"),
              head: CSV_HEADER_VOLUME,
              rows: rows.slice(1),
            }
          : undefined
      }
      actions={
        <>
          <div className="min-w-0 max-w-full overflow-x-auto">
            <SegmentedTabs
              className="min-w-max whitespace-nowrap"
              items={splitItems}
              value={view.split}
              onValueChange={(next) => onSplit(next as TimeseriesSplit | "")}
              ariaLabel={t("marketStats.split.title")}
            />
          </div>
          {series ? (
            <ChartExport
              name={`volume-${view.window}`}
              rows={rows}
              title={t("marketStats.export")}
              testId="stats-export-volume"
            />
          ) : null}
        </>
      }
    >
      {series && series.points.length > 0 ? (
        <>
          <TimeSeriesChart
            points={overlay?.points ?? seriesRows(series.points)}
            ghost={view.compare !== "off"}
            height={compact ? 180 : 220}
            ariaLabel={t("marketStats.cards.volume")}
            compareLabel={overlay ? t("marketStats.compare.legendB") : undefined}
            labels={{
              current: overlay ? t("marketStats.compare.legendCurrent") : undefined,
              prev: overlay
                ? t("marketStats.compare.legendPrev")
                : t("marketStats.series.prev"),
              series: view.split
                ? Object.keys(series.points[0]?.series ?? {}).map((key) => ({
                    key,
                    label: t(`marketStats.value.${key}`, {
                      defaultValue: key.replace(/_/g, " "),
                    }),
                  }))
                : undefined,
            }}
          />
          {overlay ? (
            <TimeSeriesLegend
              current={t("marketStats.compare.legendCurrent")}
              prev={t("marketStats.compare.legendPrev")}
              compare={t("marketStats.compare.legendB")}
            />
          ) : null}
          <p className="mt-2 text-[11px] text-[var(--as-muted-fg)]">
            {t("marketStats.bucketLabel", { bucket: series.bucket })}
          </p>
          {hint ? (
            <p className="mt-1 text-xs text-[var(--as-warning)]" data-testid="compare-hint">
              {hint}
            </p>
          ) : null}
        </>
      ) : (
        <NoData />
      )}
    </ChartCard>
  );
}

export function SkillsCard({
  skills,
  loading,
  error,
  onRetry,
  onSkill,
  compact,
  windowName,
}: {
  skills: PostingStatsSkills | null;
  loading: boolean;
  error: MarketCardError | null;
  onRetry?: () => void;
  onSkill: (key: string) => void;
  compact: boolean;
  windowName: string;
}) {
  const { t } = useTranslation();
  return (
    <ChartCard
      title={t("marketStats.cards.skills")}
      subtitle={t("marketStats.cards.skillsHint")}
      testId="skills"
      loading={loading}
      error={error}
      onRetry={onRetry}
      compact={compact}
      actions={
        skills ? (
          <ChartExport
            name={`skills-${windowName}`}
            rows={skillsCsv(skills)}
            title={t("marketStats.export")}
            testId="stats-export-skills"
          />
        ) : null
      }
    >
      {skills && skills.top.length > 0 ? (
        <>
          <p className="mb-2 flex flex-wrap gap-3 text-[11px] text-[var(--as-muted-fg)]">
            <span>
              {t("marketStats.skills.perPosting")}:{" "}
              {formatNumber(skills.avg_skills_per_posting, { maximumFractionDigits: 1 })}
            </span>
            {skills.avg_level != null ? (
              <span>
                {t("marketStats.skills.avgLevel")}: {Math.round(skills.avg_level)}
              </span>
            ) : null}
          </p>
          <span className="sr-only">{t("marketStats.table.skillsCaption")}</span>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("marketStats.skills.top")}
              </h3>
              <SkillTrendList rows={skills.top} onSelect={(row) => onSkill(row.key)} />
              <h3 className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("marketStats.skills.rising")}
              </h3>
              <SkillTrendList rows={skills.rising} max={5} testKey="stats-skill-rising" />
              <h3 className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("marketStats.skills.falling")}
              </h3>
              <SkillTrendList rows={skills.falling} max={5} testKey="stats-skill-falling" />
            </div>
            <div>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("marketStats.quadrant.title")}
              </h3>
              <span className="sr-only">{t("marketStats.table.quadrantCaption")}</span>
              <ScatterQuadrant
                rows={[...skills.top, ...skills.rising, ...skills.falling]
                  .filter((row, index, all) => all.findIndex((r) => r.key === row.key) === index)
                  .slice(0, QUADRANT_MAX)}
                onSelect={(row) => onSkill(row.key)}
              />
              <h3 className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("marketStats.skills.categoryMix")}
              </h3>
              <div className="grid gap-2 md:grid-cols-2">
                <DonutChart
                  slices={skills.categories.slice(0, 8).map((category) => ({
                    key: category.key,
                    label: t(`marketStats.value.${category.key}`, {
                      defaultValue: category.key,
                    }),
                    count: category.count,
                  }))}
                />
                <ul className="space-y-1 self-center text-xs">
                  {skills.categories.slice(0, 8).map((category) => (
                    <li
                      key={category.key}
                      className="flex justify-between gap-2 tabular-nums text-[var(--as-muted-fg)]"
                      data-testid="stats-category-row"
                    >
                      <span className="min-w-0 truncate text-[var(--as-fg)]">
                        {t(`marketStats.value.${category.key}`, { defaultValue: category.key })}
                      </span>
                      <span>
                        {formatNumber(category.count)} · {percent(category.share)}%
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div>
                  <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    {t("marketStats.skills.levelHistogram")}
                  </h3>
                  <BreakdownBars
                    breakdown={breakdownFromRows(
                      skills.levels.map((level) => ({
                        key: String(level.level),
                        count: level.count,
                      })),
                      skills.levels.reduce((sum, level) => sum + level.count, 0),
                    )}
                    resolveLabel={(key) => `L${key}`}
                    testKey="stats-skill-level"
                  />
                  <h3 className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    {t("marketStats.skills.priority")}
                  </h3>
                  <div className="grid grid-cols-3 gap-2 text-center text-xs">
                    {["must_have", "nice_to_have", "bonus"].map((priority) => (
                      <div
                        key={priority}
                        className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2"
                        data-testid="stats-priority-cell"
                      >
                        <p className="text-lg font-semibold tabular-nums text-[var(--as-fg)]">
                          {formatNumber(skills.priority[priority] ?? 0)}
                        </p>
                        <p className="text-[11px] text-[var(--as-muted-fg)]">
                          {t(`marketStats.value.${priority}`, {
                            defaultValue: priority.replace(/_/g, " "),
                          })}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      ) : (
        <NoData />
      )}
    </ChartCard>
  );
}

export function DimensionsCard({
  breakdown,
  view,
  loading,
  error,
  onRetry,
  onDimension,
  onDrill,
  compact,
}: {
  breakdown: PostingStatsBreakdown | null;
  view: MarketStatsView;
  loading: boolean;
  error: MarketCardError | null;
  onRetry?: () => void;
  onDimension: (dimension: MarketDimension) => void;
  onDrill: (dimension: MarketDimension, key: string) => void;
  compact: boolean;
}) {
  const { t } = useTranslation();
  const rows: CsvRows = breakdown ? breakdownCsv(breakdown) : [];
  const dimensionOptions = MARKET_DIMENSIONS.map((value) => ({
    value,
    label: t(`marketStats.dimension.${value}`),
  }));
  return (
    <ChartCard
      title={t("marketStats.cards.dimensions")}
      subtitle={t("marketStats.cards.dimensionsHint")}
      testId="dimensions"
      loading={loading}
      error={error}
      onRetry={onRetry}
      compact={compact}
      table={
        rows.length > 0
          ? {
              caption: t("marketStats.table.dimensions"),
              head: rows[0].map(String),
              rows: rows.slice(1),
            }
          : undefined
      }
      actions={
        <>
          <div className="w-48">
            <SearchableDropdown
              options={dimensionOptions}
              value={view.dimension}
              onChange={(value) => onDimension(value as MarketDimension)}
              label={t("marketStats.dimension.title")}
              hideLabel
            />
          </div>
          {breakdown ? (
            <ChartExport
              name={`breakdown-${view.dimension}-${view.window}`}
              rows={rows}
              title={t("marketStats.export")}
              testId="stats-export-dimensions"
            />
          ) : null}
        </>
      }
    >
      {breakdown ? (
        <BreakdownBars
          breakdown={breakdown}
          resolveLabel={(key) =>
            t(`marketStats.value.${key}`, { defaultValue: key.replace(/_/g, " ") })
          }
          onSelect={
            DRILLABLE[view.dimension] ? (row) => onDrill(view.dimension, row.key) : undefined
          }
        />
      ) : (
        <NoData />
      )}
    </ChartCard>
  );
}

export function SalaryCard({
  salary,
  loading,
  error,
  onRetry,
  onBucket,
  compact,
  windowName,
}: {
  salary: PostingStatsSalary | null;
  loading: boolean;
  error: MarketCardError | null;
  onRetry?: () => void;
  onBucket: (floor: number) => void;
  compact: boolean;
  windowName: string;
}) {
  const { t } = useTranslation();
  const currencies = salary?.currencies ?? [];
  const rows = currencies.length > 0 ? salaryCsv(salary as PostingStatsSalary) : [];
  return (
    <ChartCard
      title={t("marketStats.cards.salary")}
      subtitle={t("marketStats.cards.salaryHint")}
      testId="salary"
      loading={loading}
      error={error}
      onRetry={onRetry}
      compact={compact}
      table={
        rows.length > 0
          ? {
              caption: t("marketStats.table.salary"),
              head: rows[0].map(String),
              rows: rows.slice(1),
            }
          : undefined
      }
      actions={
        currencies.length > 0 ? (
          <ChartExport
            name={`salary-${windowName}`}
            rows={rows}
            title={t("marketStats.export")}
            testId="stats-export-salary"
          />
        ) : null
      }
    >
      {currencies.length > 0 ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {currencies.slice(0, 4).map((entry) => (
            <CurrencySalary
              key={entry.currency}
              entry={entry}
              asOf={salary?.as_of ?? ""}
              onBucket={onBucket}
            />
          ))}
        </div>
      ) : (
        <NoData />
      )}
    </ChartCard>
  );
}

function CurrencySalary({
  entry,
  asOf,
  onBucket,
}: {
  entry: SalaryCurrency;
  asOf: string;
  onBucket: (floor: number) => void;
}) {
  const { t } = useTranslation();
  if (entry.histogram.length === 0) return null;
  return (
    <div
      className="rounded-[var(--as-radius)] border border-[var(--as-border)] p-3"
      data-testid="stats-salary-currency"
    >
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-[var(--as-fg)]">{entry.currency}</h3>
        <span className="text-xs tabular-nums text-[var(--as-muted-fg)]">
          {t("marketStats.salary.coverage", { pct: percent(entry.coverage) })} ·{" "}
          {formatNumber(entry.disclosed)}
        </span>
      </div>
      {entry.thin_sample || entry.p25 == null || entry.p75 == null ? (
        <p className="py-1 text-xs text-[var(--as-muted-fg)]">{t("marketStats.salary.thin")}</p>
      ) : (
        <RangeBar
          low={entry.p25}
          high={entry.p75}
          min={entry.histogram[0].floor}
          max={entry.histogram[entry.histogram.length - 1].ceiling}
          unit={entry.currency}
        />
      )}
      <div className="mt-2">
        <BreakdownBars
          breakdown={{
            as_of: asOf,
            window: "",
            status_basis: "all",
            start: null,
            end: "",
            dimension: "family",
            total: entry.disclosed,
            rows: entry.histogram.map((bucket) => ({
              key: `${bucket.floor}-${bucket.ceiling}`,
              count: bucket.count,
              share: entry.disclosed > 0 ? bucket.count / entry.disclosed : 0,
              prev: 0,
              delta_pct: null,
              trend: "flat",
            })),
          }}
          resolveLabel={(key) => {
            const [floor, ceiling] = key.split("-").map(Number);
            return `${fmtMoney(floor, entry.currency)} – ${fmtMoney(ceiling, entry.currency)}`;
          }}
          onSelect={(row) => onBucket(Number(row.key.split("-")[0]))}
          testKey="stats-salary-bucket"
        />
      </div>
      {entry.by_seniority.length > 0 ? (
        <ul className="mt-2 space-y-1 text-xs tabular-nums text-[var(--as-muted-fg)]">
          {entry.by_seniority.slice(0, 6).map((row) => (
            <li key={row.seniority} className="flex justify-between gap-2">
              <span className="text-[var(--as-fg)]">
                {t(`marketStats.value.${row.seniority}`, {
                  defaultValue: row.seniority.replace(/_/g, " "),
                })}
              </span>
              <span>
                {row.median != null ? fmtMoney(row.median, entry.currency) : "—"} ·{" "}
                {formatNumber(row.count)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-2 flex flex-wrap gap-2 text-[11px] text-[var(--as-muted-fg)]">
        {Object.entries(entry.period_basis).map(([basis, count]) => (
          <span key={basis}>
            {t(`marketStats.value.${basis}`, { defaultValue: basis.replace(/_/g, " ") })}:{" "}
            {formatNumber(count)}
          </span>
        ))}
      </p>
    </div>
  );
}

function fmtMoney(value: number, currency: string): string {
  try {
    return formatCurrency(value, currency);
  } catch {
    return `${formatNumber(value)} ${currency}`;
  }
}

export function CompaniesCard({
  summary,
  overview,
  loading,
  summaryError,
  overviewError,
  onRetry,
  onNewCompanies,
  onIndustry,
  onCompany,
  windowName,
}: {
  summary: CompanyStatsSummary | null;
  overview: CompanyStatsOverview | null;
  loading: boolean;
  summaryError: MarketCardError | null;
  overviewError: MarketCardError | null;
  onRetry?: () => void;
  onNewCompanies: () => void;
  onIndustry: (industry: string) => void;
  onCompany: (key: string) => void;
  windowName: string;
}) {
  const { t } = useTranslation();
  const companyRows = overview && overview.top_hiring.length > 0 ? companiesCsv(overview) : [];
  const tiles: StatTile[] = [];
  if (summary) {
    tiles.push({
      label: t("marketStats.companies.hiring"),
      value: formatNumber(summary.companies_hiring),
    });
    tiles.push({
      label: t("marketStats.companies.newCompanies"),
      value: formatNumber(summary.new_companies.count),
      hint: <DeltaBadge delta={summary.new_companies} />,
      onClick: onNewCompanies,
    });
  }
  return (
    <div className="ca-mi-cards">
      <ChartCard
        title={t("marketStats.cards.companies")}
        testId="companies-tiles"
        loading={loading}
        error={summaryError}
        onRetry={onRetry}
      >
        <StatTiles layout="auto" columns={2} testId="market-stats-companies" tiles={tiles} />
      </ChartCard>
      <ChartCard
        title={t("marketStats.companies.topHiring")}
        testId="companies-top"
        loading={loading}
        error={overviewError}
        onRetry={onRetry}
        table={
          companyRows.length > 0
            ? {
                caption: t("marketStats.table.companies"),
                head: companyRows[0].map(String),
                rows: companyRows.slice(1),
              }
            : undefined
        }
        actions={
          overview && overview.top_hiring.length > 0 ? (
            <ChartExport
              name={`companies-${windowName}`}
              rows={companyRows}
              title={t("marketStats.export")}
              testId="stats-export-companies"
            />
          ) : null
        }
      >
        {overview && overview.top_hiring.length > 0 ? (
          <ul className="space-y-1.5">
            {overview.top_hiring.map((company, index) => (
              <li key={company.key}>
                <button
                  type="button"
                  onClick={() => onCompany(company.key)}
                  data-testid={`stats-company-${company.key}`}
                  className="flex min-h-[44px] w-full items-baseline gap-2 rounded-lg px-1.5 py-1 text-xs transition-colors hover:bg-[var(--as-muted)]"
                  title={t("marketStats.companies.open", { count: company.open_postings })}
                >
                  <span className="w-4 shrink-0 text-right tabular-nums text-[10px] text-[var(--as-muted-fg)]">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-left font-medium text-[var(--as-fg)]">
                    {company.name}
                  </span>
                  <span className="tabular-nums text-[var(--as-muted-fg)]">
                    {formatNumber(company.open_postings)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <NoData />
        )}
      </ChartCard>
      <ChartCard
        title={t("marketStats.companies.industryMix")}
        testId="companies-industries"
        loading={loading}
        error={overviewError}
        onRetry={onRetry}
      >
        {overview && overview.industry_mix.length > 0 ? (
          <BreakdownBars
            breakdown={{
              as_of: overview.as_of,
              window: "",
              status_basis: "all",
              start: null,
              end: "",
              dimension: "family",
              total: overview.industry_mix.reduce((sum, row) => sum + row.count, 0),
              rows: overview.industry_mix.map((row) => ({
                key: row.key,
                count: row.count,
                share: row.share,
                prev: 0,
                delta_pct: null,
                trend: "flat",
              })),
            }}
            resolveLabel={(key) =>
              t(`marketStats.value.${key}`, { defaultValue: key.replace(/_/g, " ") })
            }
            onSelect={(row) => onIndustry(row.key)}
            testKey="stats-industry"
          />
        ) : (
          <NoData />
        )}
      </ChartCard>
      <ChartCard
        title={t("marketStats.companies.openings")}
        testId="companies-openings"
        loading={loading}
        error={overviewError}
        onRetry={onRetry}
      >
        {overview && overview.openings_histogram.length > 0 ? (
          <BreakdownBars
            breakdown={breakdownFromRows(
              overview.openings_histogram.map((bucket) => ({
                key: bucket.bucket,
                count: bucket.count,
              })),
              overview.openings_histogram.reduce((sum, bucket) => sum + bucket.count, 0),
            )}
            resolveLabel={(key) => key}
            testKey="stats-openings"
          />
        ) : (
          <NoData />
        )}
      </ChartCard>
    </div>
  );
}

export function breakdownFromRows(
  rows: { key: string; count: number }[],
  total: number,
): PostingStatsBreakdown {
  return {
    as_of: "",
    window: "",
    status_basis: "all",
    start: null,
    end: "",
    dimension: "source",
    total,
    rows: rows.map(({ key, count }) => ({
      key,
      count,
      share: total > 0 ? count / total : 0,
      prev: 0,
      delta_pct: null,
      trend: "flat",
    })),
  };
}
