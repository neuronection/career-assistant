import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Download, RefreshCw } from "lucide-react";
import {
  EmptyState,
  RangeBar,
  SearchableDropdown,
  SegmentedTabs,
  type SegmentedTabsItem,
} from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import { ChartCard } from "@/components/stats/charts/chartKit";
import { DeltaBadge } from "@/components/stats/charts/DeltaBadge";
import { InsightsStrip } from "@/components/stats/charts/InsightsStrip";
import { TimeSeriesChart, seriesRows } from "@/components/stats/charts/TimeSeriesChart";
import { BreakdownBars } from "@/components/stats/charts/BreakdownBars";
import { SkillTrendList } from "@/components/stats/charts/SkillTrendList";
import { ScatterQuadrant } from "@/components/stats/charts/ScatterQuadrant";
import { DonutChart } from "@/components/stats/charts/DonutChart";
import {
  fetchCompanyStatsOverview,
  fetchCompanyStatsSummary,
  fetchPostingStatsBreakdown,
  fetchPostingStatsOverview,
  fetchPostingStatsSalary,
  fetchPostingStatsSkills,
  fetchPostingStatsSummary,
  fetchPostingStatsTimeseries,
  type CompanyStatsOverview,
  type CompanyStatsSummary,
  type MarketDimension,
  type PostingStatsBreakdown,
  type PostingStatsOverview,
  type PostingStatsSalary,
  type PostingStatsSkills,
  type PostingStatsSummary,
  type PostingStatsTimeseries,
  type SalaryCurrency,
  type TimeseriesSplit,
} from "@/api/stats";
import {
  MARKET_DIMENSIONS,
  MARKET_WINDOWS,
  parseView,
  rangeQuery,
  toSearchParams,
  type MarketStatsView,
} from "./marketStatsParams";

const QUADRANT_MAX = 30;

/** Dimensions with an honest explore-filter mapping (drill-down law H1);
 * the rest render plain. */
const DRILLABLE: Partial<Record<MarketDimension, boolean>> = {
  seniority: true,
  work_mode: true,
  source: true,
  org: true,
  contract: true,
};

export function MarketStats() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [summary, setSummary] = useState<PostingStatsSummary | null>(null);
  const [overview, setOverview] = useState<PostingStatsOverview | null>(null);
  const [series, setSeries] = useState<PostingStatsTimeseries | null>(null);
  const [skills, setSkills] = useState<PostingStatsSkills | null>(null);
  const [breakdown, setBreakdown] = useState<PostingStatsBreakdown | null>(null);
  const [salary, setSalary] = useState<PostingStatsSalary | null>(null);
  const [companySummary, setCompanySummary] = useState<CompanyStatsSummary | null>(null);
  const [companyOverview, setCompanyOverview] = useState<CompanyStatsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [ghost, setGhost] = useState(true);
  const requestId = useRef(0);
  const view = useMemo(() => parseView(searchParams), [searchParams]);
  const viewRef = useRef(view);
  viewRef.current = view;
  const viewKey = toSearchParams(view).toString();

  useEffect(() => {
    const canonical = toSearchParams(parseView(searchParams)).toString();
    if (canonical !== searchParams.toString()) {
      setSearchParams(new URLSearchParams(canonical), { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async () => {
    const current = viewRef.current;
    const id = ++requestId.current;    setLoading(true);
    setError(false);
    const market = { ...rangeQuery(current), status_basis: current.basis };
    const results = await Promise.allSettled([
      fetchPostingStatsSummary({ status_basis: current.basis }),
      fetchPostingStatsOverview(market),
      fetchPostingStatsTimeseries({
        ...market,
        ...(current.split ? { split: current.split } : {}),
      }),
      fetchPostingStatsSkills(market),
      fetchPostingStatsBreakdown(current.dimension, market),
      fetchPostingStatsSalary(market),
      fetchCompanyStatsSummary(market),
      fetchCompanyStatsOverview(market),
    ]);
    if (id !== requestId.current) return;
    const [rSummary, rOverview, rSeries, rSkills, rBreakdown, rSalary, rCompany, rCompanies] =
      results;
    setSummary(rSummary.status === "fulfilled" ? rSummary.value : null);
    setOverview(rOverview.status === "fulfilled" ? rOverview.value : null);
    setSeries(rSeries.status === "fulfilled" ? rSeries.value : null);
    setSkills(rSkills.status === "fulfilled" ? rSkills.value : null);
    setBreakdown(rBreakdown.status === "fulfilled" ? rBreakdown.value : null);
    setSalary(rSalary.status === "fulfilled" ? rSalary.value : null);
    setCompanySummary(rCompany.status === "fulfilled" ? rCompany.value : null);
    setCompanyOverview(rCompanies.status === "fulfilled" ? rCompanies.value : null);
    if (results.every((result) => result.status === "rejected")) {
      setError(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, viewKey]);

  const patch = useCallback(
    (update: Partial<MarketStatsView>) => {
      setSearchParams(toSearchParams({ ...viewRef.current, ...update }), { replace: true });
    },
    [setSearchParams]
  );

  const splitItems: SegmentedTabsItem[] = [
    { value: "", label: t("marketStats.split.none") },
    ...(["status", "source", "work_mode", "seniority", "employment"] as TimeseriesSplit[]).map(
      (value) => ({ value, label: t(`marketStats.split.${value}`) }),
    ),
  ];
  const dimensionOptions = MARKET_DIMENSIONS.map((value) => ({
    value,
    label: t(`marketStats.dimension.${value}`),
  }));

  return (
    <div className="space-y-4" data-testid="market-stats">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-[var(--as-fg)]">{t("marketStats.title")}</h1>
          <p className="text-sm text-[var(--as-muted-fg)]">{t("marketStats.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            aria-pressed={ghost}
            onClick={() => setGhost((value) => !value)}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--as-border)] px-3 py-1 text-xs font-medium text-[var(--as-muted-fg)]"
            data-testid="market-stats-compare"
            title={t("marketStats.compare.title")}
          >
            <RefreshCw className="size-3" aria-hidden />
            {t("marketStats.compare.title")}
          </button>
          <button
            type="button"
            disabled
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--as-border)] px-3 py-1 text-xs font-medium text-[var(--as-muted-fg)] opacity-60"
            data-testid="stats-export"
            title={t("marketStats.exportComing")}
          >
            <Download className="size-3" aria-hidden />
            {t("marketStats.export")}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SegmentedTabs
          items={[...MARKET_WINDOWS, "custom"].map((value) => ({
            value,
            label: t(`marketStats.window.${value}`),
          }))}
          value={view.window}
          onValueChange={(next) => {
            if (next === "custom") {
              const today = new Date();
              const start = new Date(today);
              start.setDate(start.getDate() - 29);
              patch({
                window: "custom",
                from: start.toISOString().slice(0, 10),
                to: today.toISOString().slice(0, 10),
              });
            } else {
              patch({ window: next as MarketStatsView["window"] });
            }
          }}
          ariaLabel={t("marketStats.window.title")}
        />
        {view.window === "custom" ? (
          <span className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1.5 text-sm text-[var(--as-fg)]"
              value={view.from}
              max={view.to || undefined}
              onChange={(event) => patch({ from: event.target.value })}
              aria-label={t("marketStats.window.fromLabel")}
              data-testid="market-stats-from"
            />
            <span aria-hidden className="text-xs text-[var(--as-muted-fg)]">→</span>
            <input
              type="date"
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1.5 text-sm text-[var(--as-fg)]"
              value={view.to}
              min={view.from || undefined}
              onChange={(event) => patch({ to: event.target.value })}
              aria-label={t("marketStats.window.toLabel")}
              data-testid="market-stats-to"
            />
          </span>
        ) : null}
        <div
          className="flex items-center gap-1 rounded-[var(--as-radius)] border border-[var(--as-border)] p-0.5"
          role="group"
          aria-label={t("marketStats.basis.title")}
        >
          {(["open", "all"] as const).map((basis) => (
            <button
              key={basis}
              type="button"
              aria-pressed={view.basis === basis}
              onClick={() => patch({ basis })}
              className={`rounded-[calc(var(--as-radius,0.75rem)-0.2rem)] px-2 py-0.5 text-xs ${
                view.basis === basis
                  ? "bg-[var(--as-surface-raised)] font-medium text-[var(--as-fg)]"
                  : "text-[var(--as-muted-fg)]"
              }`}
              data-testid={`market-stats-basis-${basis}`}
              title={t("marketStats.basisHint")}
            >
              {t(`marketStats.basis.${basis}`)}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <p className="text-sm text-[var(--as-danger)]" data-testid="market-stats-error">
          {t("marketStats.error")}
        </p>
      ) : null}
      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="market-stats-skeleton">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="cv-shimmer h-56 rounded-[var(--as-radius-lg)]" />
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          <InsightsStrip insights={overview?.insights ?? []} />

          {summary ? (
            <StatTiles
              tiles={[
                {
                  label: t("marketStats.tiles.new24h"),
                  value: summary.new_24h.count.toLocaleString(),
                  hint: <DeltaBadge delta={summary.new_24h} />,
                  onClick: () => navigate("/postings?posted_within=24h"),
                },
                {
                  label: t("marketStats.tiles.new7d"),
                  value: summary.new_7d.count.toLocaleString(),
                  hint: <DeltaBadge delta={summary.new_7d} />,
                  onClick: () => navigate("/postings?posted_within=7d"),
                },
                {
                  label: t("marketStats.tiles.new30d"),
                  value: summary.new_30d.count.toLocaleString(),
                  hint: <DeltaBadge delta={summary.new_30d} />,
                  sparkline: summary.sparkline,
                  onClick: () => navigate("/postings?posted_within=30d"),
                },
                {
                  label: t("marketStats.tiles.openTotal"),
                  value: summary.open_total.toLocaleString(),
                  onClick: () => navigate("/postings"),
                },
              ]}
              testId="market-stats-kpis"
              layout="auto"
              columns={4}
            />
          ) : null}

          <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
            <ChartCard
              title={t("marketStats.cards.volume")}
              subtitle={t("marketStats.cards.volumeHint")}
              testId="volume"
              actions={
                <SegmentedTabs
                  items={splitItems}
                  value={view.split}
                  onValueChange={(next) => patch({ split: next as TimeseriesSplit | "" })}
                  ariaLabel={t("marketStats.split.title")}
                />
              }
            >
              {series && series.points.length > 0 ? (
                <>
                  <TimeSeriesChart
                    points={seriesRows(series.points)}
                    ghost={ghost}
                    height={220}
                    labels={{
                      prev: t("marketStats.series.prev"),
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
                  <p className="mt-2 text-[11px] text-[var(--as-muted-fg)]">
                    {t("marketStats.bucketLabel", { bucket: series.bucket })}
                  </p>
                </>
              ) : (
                <NoData />
              )}
            </ChartCard>

            <ChartCard title={t("marketStats.cards.overview")} testId="overview">
              {overview ? (
                <>
                  <StatTiles
                    layout="auto"
                    columns={2}
                    testId="market-stats-overview"
                    tiles={[
                      {
                        label: t("marketStats.tiles.newInRange"),
                        value: overview.new_in_range.count.toLocaleString(),
                        hint: <DeltaBadge delta={overview.new_in_range} />,
                      },
                      {
                        label: t("marketStats.tiles.openTotal"),
                        value: overview.open_total.toLocaleString(),
                      },
                    ]}
                  />
                  <StatusMix overview={overview} />
                </>
              ) : (
                <NoData />
              )}
            </ChartCard>
          </div>

          <ChartCard
            title={t("marketStats.cards.skills")}
            subtitle={t("marketStats.cards.skillsHint")}
            testId="skills"
          >
            {skills && skills.top.length > 0 ? (
              <>
                <p className="mb-2 flex flex-wrap gap-3 text-[11px] text-[var(--as-muted-fg)]">
                  <span>
                    {t("marketStats.skills.perPosting")}:{" "}
                    {skills.avg_skills_per_posting.toLocaleString(undefined, {
                      maximumFractionDigits: 1,
                    })}
                  </span>
                  {skills.avg_level != null ? (
                    <span>
                      {t("marketStats.skills.avgLevel")}: {Math.round(skills.avg_level)}
                    </span>
                  ) : null}
                </p>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                      {t("marketStats.skills.top")}
                    </h4>
                    <SkillTrendList
                      rows={skills.top}
                      onSelect={(row) => navigate(`/postings?skills=${encodeURIComponent(row.key)}`)}
                    />
                    <h4 className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                      {t("marketStats.skills.rising")}
                    </h4>
                    <SkillTrendList rows={skills.rising} max={5} testKey="stats-skill-rising" />
                    <h4 className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                      {t("marketStats.skills.falling")}
                    </h4>
                    <SkillTrendList rows={skills.falling} max={5} testKey="stats-skill-falling" />
                  </div>
                  <div>
                    <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                      {t("marketStats.quadrant.title")}
                    </h4>
                    <ScatterQuadrant
                      rows={[...skills.top, ...skills.rising, ...skills.falling]
                        .filter((row, index, all) => all.findIndex((r) => r.key === row.key) === index)
                        .slice(0, QUADRANT_MAX)}
                      onSelect={(row) => navigate(`/postings?skills=${encodeURIComponent(row.key)}`)}
                    />
                    <h4 className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                      {t("marketStats.skills.categoryMix")}
                    </h4>
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
                              {t(`marketStats.value.${category.key}`, {
                                defaultValue: category.key,
                              })}
                            </span>
                            <span>
                              {category.count.toLocaleString()} ·{" "}
                              {Math.round(category.share * 100)}%
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <div>
                        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                          {t("marketStats.skills.levelHistogram")}
                        </h4>
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
                        <h4 className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                          {t("marketStats.skills.priority")}
                        </h4>
                        <div className="grid grid-cols-3 gap-2 text-center text-xs">
                          {["must_have", "nice_to_have", "bonus"].map((priority) => (
                            <div
                              key={priority}
                              className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2"
                              data-testid="stats-priority-cell"
                            >
                              <p className="text-lg font-semibold tabular-nums text-[var(--as-fg)]">
                                {(skills.priority[priority] ?? 0).toLocaleString()}
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

          <ChartCard
            title={t("marketStats.cards.dimensions")}
            subtitle={t("marketStats.cards.dimensionsHint")}
            testId="dimensions"
            actions={
              <div className="w-56">
                <SearchableDropdown
                  options={dimensionOptions}
                  value={view.dimension}
                  onChange={(value) => patch({ dimension: value as MarketDimension })}
                  label={t("marketStats.dimension.title")}
                  hideLabel
                />
              </div>
            }
          >
            {breakdown ? (
              <BreakdownBars
                breakdown={breakdown}
                resolveLabel={(key) =>
                  t(`marketStats.value.${key}`, { defaultValue: key.replace(/_/g, " ") })
                }
                onSelect={
                  DRILLABLE[view.dimension]
                    ? (row) => navigate(drillUrl(view.dimension, row.key))
                    : undefined
                }
              />
            ) : (
              <NoData />
            )}
          </ChartCard>

          <SalaryCard
            salary={salary}
            onBucket={(floor) => navigate(`/postings?salary_min=${Math.round(floor)}`)}
          />

          <CompaniesCard
            summary={companySummary}
            overview={companyOverview}
            onNewCompanies={() => navigate("/companies?status=new")}
            onIndustry={(industry) =>
              navigate(`/companies?industry=${encodeURIComponent(industry)}`)
            }
            onCompany={(key) => navigate(`/companies/${key}`)}
          />

          <footer
            className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] px-4 py-3 text-xs text-[var(--as-muted-fg)]"
            data-testid="market-stats-footer"
          >
            {overview ? (
              <>
                <span>{t("marketStats.coverage.salary", { pct: pct(overview.coverage.salary) })}</span>
                <span>{t("marketStats.coverage.location", { pct: pct(overview.coverage.location) })}</span>
                <span>
                  {t("marketStats.coverage.orgLinked", { pct: pct(overview.coverage.org_linked) })}
                </span>
                <span>
                  {t("marketStats.coverage.skillTagged", { pct: pct(overview.coverage.skill_tagged) })}
                </span>
              </>
            ) : (
              <NoData />
            )}
            {summary ? <Freshness summary={summary} /> : null}
          </footer>
        </div>
      )}
    </div>
  );
}

function NoData() {
  const { t } = useTranslation();
  return <EmptyState compact title={t("marketStats.noData")} />;
}

function pct(share: number): number {
  return Math.round(share * 100);
}

function breakdownFromRows(
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

function StatusMix({ overview }: { overview: PostingStatsOverview }) {
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

function Freshness({ summary }: { summary: PostingStatsSummary }) {
  const { t } = useTranslation();
  return (
    <>
      <span data-testid="stats-freshness-asof">
        {t("marketStats.freshness.asOf", {
          date: new Date(summary.freshness.as_of).toLocaleString(),
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

function SalaryCard({
  salary,
  onBucket,
}: {
  salary: PostingStatsSalary | null;
  onBucket: (floor: number) => void;
}) {
  const { t } = useTranslation();
  const currencies = salary?.currencies ?? [];
  return (
    <ChartCard
      title={t("marketStats.cards.salary")}
      subtitle={t("marketStats.cards.salaryHint")}
      testId="salary"
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
  if (entry.histogram.length > 0) {
    return (
      <div
        className="rounded-[var(--as-radius)] border border-[var(--as-border)] p-3"
        data-testid="stats-salary-currency"
      >
        <div className="mb-2 flex items-baseline justify-between gap-2">
          <h4 className="text-sm font-semibold text-[var(--as-fg)]">{entry.currency}</h4>
          <span className="text-xs tabular-nums text-[var(--as-muted-fg)]">
            {t("marketStats.salary.coverage", { pct: pct(entry.coverage) })} ·{" "}
            {entry.disclosed.toLocaleString()}
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
                  {row.count.toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-2 flex flex-wrap gap-2 text-[11px] text-[var(--as-muted-fg)]">
          {Object.entries(entry.period_basis).map(([basis, count]) => (
            <span key={basis}>
              {t(`marketStats.value.${basis}`, { defaultValue: basis.replace(/_/g, " ") })}:{" "}
              {count.toLocaleString()}
            </span>
          ))}
        </p>
      </div>
    );
  }
  return null;
}

function fmtMoney(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value.toLocaleString()} ${currency}`;
  }
}

function CompaniesCard({
  summary,
  overview,
  onNewCompanies,
  onIndustry,
  onCompany,
}: {
  summary: CompanyStatsSummary | null;
  overview: CompanyStatsOverview | null;
  onNewCompanies: () => void;
  onIndustry: (industry: string) => void;
  onCompany: (key: string) => void;
}) {
  const { t } = useTranslation();
  if (!summary && !overview) return <NoData />;
  const tiles: StatTile[] = [];
  if (summary) {
    tiles.push({
      label: t("marketStats.companies.hiring"),
      value: summary.companies_hiring.toLocaleString(),
    });
    tiles.push({
      label: t("marketStats.companies.newCompanies"),
      value: summary.new_companies.count.toLocaleString(),
      hint: <DeltaBadge delta={summary.new_companies} />,
      onClick: onNewCompanies,
    });
  }
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <ChartCard title={t("marketStats.cards.companies")} testId="companies-tiles">
        <StatTiles layout="auto" columns={2} testId="market-stats-companies" tiles={tiles} />
      </ChartCard>
      <ChartCard title={t("marketStats.companies.topHiring")} testId="companies-top">
        {overview && overview.top_hiring.length > 0 ? (
          <ul className="space-y-1.5">
            {overview.top_hiring.map((company, index) => (
              <li key={company.key}>
                <button
                  type="button"
                  onClick={() => onCompany(company.key)}
                  data-testid={`stats-company-${company.key}`}
                  className="flex w-full items-baseline gap-2 rounded-lg px-1.5 py-1 text-xs transition-colors hover:bg-[var(--as-muted)]"
                  title={t("marketStats.companies.open", { count: company.open_postings })}
                >
                  <span className="w-4 shrink-0 text-right tabular-nums text-[10px] text-[var(--as-muted-fg)]">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-left font-medium text-[var(--as-fg)]">
                    {company.name}
                  </span>
                  <span className="tabular-nums text-[var(--as-muted-fg)]">
                    {company.open_postings.toLocaleString()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <NoData />
        )}
      </ChartCard>
      <ChartCard title={t("marketStats.companies.industryMix")} testId="companies-industries">
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
    </div>
  );
}

/** The explore-list deep link for one dimension row (H1). */
export function drillUrl(dimension: MarketDimension, key: string): string {
  switch (dimension) {
    case "seniority":
      return `/postings?seniority=${encodeURIComponent(key)}`;
    case "work_mode":
      return `/postings?remote_policy=${encodeURIComponent(key)}`;
    case "source":
      return `/postings?source=${encodeURIComponent(key)}`;
    case "org":
      return `/postings?org=${encodeURIComponent(key)}`;
    case "contract":
      return `/postings?contract=${encodeURIComponent(key)}`;
    default:
      return "/postings";
  }
}
