import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Copy, Download } from "lucide-react";
import { isAxiosError } from "axios";
import {
  EmptyState,
  RangeBar,
  SearchableDropdown,
  SegmentedTabs,
  type SegmentedTabsItem,
} from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import { ChartExport } from "@/components/stats/charts/ChartExport";
import { ChartCard } from "@/components/stats/charts/chartKit";
import { downloadStatsCsv, type CsvRows } from "@/components/stats/statsExport";
import { DeltaBadge } from "@/components/stats/charts/DeltaBadge";
import { InsightsStrip } from "@/components/stats/charts/InsightsStrip";
import { TimeSeriesChart, TimeSeriesLegend, seriesRows } from "@/components/stats/charts/TimeSeriesChart";
import { BreakdownBars } from "@/components/stats/charts/BreakdownBars";
import { SkillTrendList } from "@/components/stats/charts/SkillTrendList";
import { ScatterQuadrant } from "@/components/stats/charts/ScatterQuadrant";
import { ClockworkCard } from "@/components/stats/charts/ClockworkCard";
import { DonutChart } from "@/components/stats/charts/DonutChart";
import {
  fetchCompanyStatsOverview,
  fetchCompanyStatsSummary,
  fetchPostingStatsBreakdown,
  fetchPostingStatsClockwork,
  fetchPostingStatsOverview,
  fetchPostingStatsSalary,
  fetchPostingStatsSkills,
  fetchPostingStatsSummary,
  fetchPostingStatsTimeseries,
  type CompanyStatsOverview,
  type CompanyStatsSummary,
  type MarketDimension,
  type PostingStatsBreakdown,
  type PostingStatsClockwork,
  type PostingStatsOverview,
  type PostingStatsSalary,
  type PostingStatsSkills,
  type PostingStatsSummary,
  type PostingStatsTimeseries,
  type SalaryCurrency,
  type SkillStat,
  type TimeseriesSplit,
} from "@/api/stats";
import {
  MARKET_DIMENSIONS,
  MARKET_WINDOWS,
  addIsoDays,
  compareRange,
  parseView,
  rangeQuery,
  spanDays,
  toSearchParams,
  type MarketStatsView,
} from "./marketStatsParams";
import { copyText } from "@/lib/clipboard";

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
  const location = useLocation();
  const [summary, setSummary] = useState<PostingStatsSummary | null>(null);
  const [overview, setOverview] = useState<PostingStatsOverview | null>(null);
  const [series, setSeries] = useState<PostingStatsTimeseries | null>(null);
  const [skills, setSkills] = useState<PostingStatsSkills | null>(null);
  const [breakdown, setBreakdown] = useState<PostingStatsBreakdown | null>(null);
  const [salary, setSalary] = useState<PostingStatsSalary | null>(null);
  const [clockwork, setClockwork] = useState<PostingStatsClockwork | null>(null);
  const [companySummary, setCompanySummary] = useState<CompanyStatsSummary | null>(null);
  const [companyOverview, setCompanyOverview] = useState<CompanyStatsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [compareSeries, setCompareSeries] = useState<PostingStatsTimeseries | null>(null);
  const [compareError, setCompareError] = useState<unknown>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const copyReset = useRef(0);
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
    const id = ++requestId.current;
    setLoading(true);
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
      fetchPostingStatsClockwork(market),
    ]);
    if (id !== requestId.current) return;
    const [rSummary, rOverview, rSeries, rSkills, rBreakdown, rSalary, rCompany, rCompanies, rClockwork] =
      results;
    setSummary(rSummary.status === "fulfilled" ? rSummary.value : null);
    setOverview(rOverview.status === "fulfilled" ? rOverview.value : null);
    setSeries(rSeries.status === "fulfilled" ? rSeries.value : null);
    setSkills(rSkills.status === "fulfilled" ? rSkills.value : null);
    setBreakdown(rBreakdown.status === "fulfilled" ? rBreakdown.value : null);
    setSalary(rSalary.status === "fulfilled" ? rSalary.value : null);
    setCompanySummary(rCompany.status === "fulfilled" ? rCompany.value : null);
    setCompanyOverview(rCompanies.status === "fulfilled" ? rCompanies.value : null);
    setClockwork(rClockwork.status === "fulfilled" ? rClockwork.value : null);
    if (results.every((result) => result.status === "rejected")) {
      setError(true);
    }
    const series = rSeries.status === "fulfilled" ? rSeries.value : null;
    const bRange = rSeries.status === "fulfilled" ? compareRange(current) : null;
    // H9: the B fetch rides A's resolved bucket so the grids align; while
    // a split is on the overlay pauses (state preserved, no fetch, no
    // drop — compare applies in split=none only).
    if (current.compare !== "custom" || !bRange || current.split || !series) {
      if (id === requestId.current) {
        // Inapplicable compare — clear the stale overlay/tip so a paused
        // or absent comparison never renders beside its own hint.
        setCompareSeries(null);
        setCompareError(null);
      }
      setLoading(false);
      return;
    }
    try {
      const bFrom = `${bRange.from}T00:00:00`;
      const bTo = `${new Date(
        Date.parse(`${bRange.to}T00:00:00Z`) + 86_400_000,
      ).toISOString().slice(0, 10)}T00:00:00`;
      const b = await fetchPostingStatsTimeseries({
        from: bFrom,
        to: bTo,
        bucket: series.bucket,
        status_basis: current.basis,
      });
      if (id !== requestId.current) return;
      setCompareSeries(b);
      setCompareError(null);
    } catch (err) {
      if (id !== requestId.current) return;
      setCompareSeries(null);
      setCompareError(err);
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

  // A bare compare=custom pick seeds the B start to A's start minus A's
  // span — the exact length the previous-window ghost overlaid — so the
  // pair reveals itself usable; with no edge (window=all) nothing seeds
  // and the hint explains. Both dates pending never fetches.
  const patchCompare = useCallback(
    (mode: MarketStatsView["compare"], from?: string, to?: string) => {
      if (mode !== "custom") {
        patch({ compare: mode, compare_from: "", compare_to: "" });
        return;
      }
      if (from !== undefined) {
        patch({ compare: "custom", compare_from: from });
        return;
      }
      if (to !== undefined) {
        patch({ compare: "custom", compare_to: to });
        return;
      }
      const span = spanDays(viewRef.current);
      if (span === null || viewRef.current.compare_from) {
        patch({ compare: "custom" });
        return;
      }
      const today = new Date().toISOString().slice(0, 10);
      patch({ compare: "custom", compare_from: addIsoDays(today, -(2 * span - 1)) });
    },
    [patch]
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

  // The H8 table payloads reuse the card CSV builders — table ≡ export by
  // construction (one number in exactly one shape vocabulary).
  const volumeRows = series ? volumeCsv(series) : [];
  const breakdownRows = breakdown ? breakdownCsv(breakdown) : [];

  const bRange = compareRange(view);
  const compareOverlay = useMemo(() => {
    if (view.compare !== "custom" || view.split || !bRange || !series || !compareSeries) {
      return null;
    }
    // Alignment is by bucket ORDER (offset), not by key: B is a different
    // date range, so "same bucket" means nothing — both grids are
    // cropped to the shorter one and the shorter side is zero-padded by
    // the hint when lengths differ.
    const length = Math.min(series.points.length, compareSeries.points.length);
    const points = seriesRows(series.points)
      .slice(0, length)
      .map((row, index) => ({ ...row, compare: compareSeries.points[index]?.count ?? 0 }));
    return {
      points,
      cropped: Math.max(0, compareSeries.points.length - length),
      padded: Math.max(0, series.points.length - length),
    };
  }, [series, compareSeries, view.compare, view.split, bRange]);

  const copyLink = useCallback(async () => {
    // The deep link the app is really showing (router location, so any
    // router context is honest), against the live origin.
    const ok = await copyText(
      `${window.location.origin}${location.pathname}${location.search}`,
    );
    setCopyState(ok ? "copied" : "failed");
    window.clearTimeout(copyReset.current);
    copyReset.current = window.setTimeout(() => setCopyState("idle"), 1600);
  }, [location.pathname, location.search]);

  let compareHint: string | null = null;
  let compareHintStatus: string | null = null;
  if (view.compare === "custom") {
    if (compareError !== null) {
      // Degrade path: the B window hit the API's bucket bound (HTTP 400,
      // the DomainError mapping) — hint inline, keep the page functional.
      compareHintStatus = isAxiosError(compareError)
        ? String(compareError.response?.status ?? "")
        : null;
      compareHint = t("marketStats.compare.error");
    } else if (view.split) {
      compareHint = t("marketStats.compare.paused");
    } else if (!bRange) {
      compareHint = view.window === "all"
        ? t("marketStats.compare.hintAll")
        : t("marketStats.compare.hintDates");
    } else if (compareOverlay) {
      compareHint =
        compareOverlay.cropped > 0
          ? t("marketStats.compare.hintCrop", { count: compareOverlay.cropped })
          : compareOverlay.padded > 0
            ? t("marketStats.compare.hintPad", { count: compareOverlay.padded })
            : null;
    }
  }

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
            onClick={copyLink}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--as-border)] px-3 py-1 text-xs font-medium text-[var(--as-muted-fg)]"
            data-testid="stats-copy-link"
            title={
              copyState === "failed"
                ? t("marketStats.copy.failed")
                : t("marketStats.copy.link")
            }
          >
            <Copy className="size-3" aria-hidden />
            {copyState === "copied"
              ? t("marketStats.copy.copied")
              : copyState === "failed"
                ? t("marketStats.copy.failed")
                : t("marketStats.copy.link")}
          </button>
          <span aria-live="polite" className="sr-only">
            {copyState === "copied" ? t("marketStats.copy.copied") : ""}
          </span>
          <button
            type="button"
            onClick={() => downloadStatsCsv(view.window, allExportRows(summary, series, skills, breakdown, salary, companySummary, companyOverview))}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--as-border)] px-3 py-1 text-xs font-medium text-[var(--as-muted-fg)]"
            data-testid="stats-export"
            title={t("marketStats.exportAll")}
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
        <div
          className="flex items-center gap-1 rounded-[var(--as-radius)] border border-[var(--as-border)] p-0.5"
          role="group"
          aria-label={t("marketStats.compare.groupAria")}
          data-testid="market-stats-compare"
        >
          {(["off", "previous", "custom"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={view.compare === mode}
              onClick={() => patchCompare(mode)}
              className={`rounded-[calc(var(--as-radius,0.75rem)-0.2rem)] px-2 py-0.5 text-xs ${
                view.compare === mode
                  ? "bg-[var(--as-surface-raised)] font-medium text-[var(--as-fg)]"
                  : "text-[var(--as-muted-fg)]"
              }`}
              data-testid={`market-stats-compare-${mode}`}
            >
              {t(`marketStats.compare.${mode}`)}
            </button>
          ))}
        </div>
        {view.compare === "custom" ? (
          <span className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1.5 text-sm text-[var(--as-fg)]"
              value={view.compare_from}
              max={view.compare_to || undefined}
              onChange={(event) => patchCompare("custom", event.target.value)}
              aria-label={t("marketStats.compare.fromLabel")}
              data-testid="market-stats-compare-from"
            />
            <span aria-hidden className="text-xs text-[var(--as-muted-fg)]">→</span>
            <input
              type="date"
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1.5 text-sm text-[var(--as-fg)]"
              value={view.compare_to}
              min={view.compare_from || undefined}
              onChange={(event) => patchCompare("custom", undefined, event.target.value)}
              aria-label={t("marketStats.compare.toLabel")}
              data-testid="market-stats-compare-to"
            />
          </span>
        ) : null}
      </div>

      {compareHint ? (
        <p
          className="text-xs text-[var(--as-warning)]"
          data-testid="compare-hint"
          title={
            compareHintStatus ? `${compareHintStatus}` : undefined
          }
        >
          {compareHint}
        </p>
      ) : null}

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
              table={
                series
                  ? {
                      caption: t("marketStats.table.volume"),
                      head: CSV_HEADER_VOLUME,
                      rows: volumeRows.slice(1),
                    }
                  : undefined
              }
              actions={
                <>
                  <SegmentedTabs
                    items={splitItems}
                    value={view.split}
                    onValueChange={(next) => patch({ split: next as TimeseriesSplit | "" })}
                    ariaLabel={t("marketStats.split.title")}
                  />
                  {series ? (
                    <ChartExport
                      name={`volume-${view.window}`}
                      rows={volumeRows}
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
                    points={compareOverlay?.points ?? seriesRows(series.points)}
                    ghost={view.compare !== "off"}
                    height={220}
                    compareLabel={compareOverlay ? t("marketStats.compare.legendB") : undefined}
                    labels={{
                      current: compareOverlay ? t("marketStats.compare.legendCurrent") : undefined,
                      prev:
                        compareOverlay
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
                  {compareOverlay ? (
                    <TimeSeriesLegend
                      current={t("marketStats.compare.legendCurrent")}
                      prev={t("marketStats.compare.legendPrev")}
                      compare={t("marketStats.compare.legendB")}
                    />
                  ) : null}
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

          {clockwork ? (
            <ClockworkCard clock={clockwork} />
          ) : null}

          <ChartCard
            title={t("marketStats.cards.skills")}
            subtitle={t("marketStats.cards.skillsHint")}
            testId="skills"
            actions={skills ? (
              <ChartExport
                name={`skills-${view.window}`}
                rows={skillsCsv(skills)}
                title={t("marketStats.export")}
                testId="stats-export-skills"
              />
            ) : null}
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
                <span className="sr-only">{t("marketStats.table.skillsCaption")}</span>
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
                    <span className="sr-only">{t("marketStats.table.quadrantCaption")}</span>
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
            table={
              breakdownRows.length > 0
                ? {
                    caption: t("marketStats.table.dimensions"),
                    head: breakdownRows[0].map(String),
                    rows: breakdownRows.slice(1),
                  }
                : undefined
            }
            actions={
              <>
                <div className="w-56">
                  <SearchableDropdown
                    options={dimensionOptions}
                    value={view.dimension}
                    onChange={(value) => patch({ dimension: value as MarketDimension })}
                    label={t("marketStats.dimension.title")}
                    hideLabel
                  />
                </div>
                {breakdown ? (
                  <ChartExport
                    name={`breakdown-${view.dimension}-${view.window}`}
                    rows={breakdownRows}
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


const CSV_HEADER_VOLUME = ["bucket", "count", "prev", "ingestion"];

function volumeCsv(series: PostingStatsTimeseries): CsvRows {
  return [
    CSV_HEADER_VOLUME,
    ...series.points.map((point) => [point.bucket, point.count, point.prev, point.ingestion]),
  ];
}

function skillRowsCsv(label: string, rows: SkillStat[]): CsvRows {
  return [
    [label, "count", "share", "delta_pct", "trend"],
    ...rows.map((row) => [row.key, row.label, row.count, row.share, row.delta_pct ?? "", row.trend]),
  ];
}

function skillsCsv(skills: PostingStatsSkills): CsvRows {
  return [
    ...skillRowsCsv("top", skills.top),
    ...skillRowsCsv("rising", skills.rising),
    ...skillRowsCsv("falling", skills.falling),
  ];
}

function breakdownCsv(breakdown: PostingStatsBreakdown): CsvRows {
  return [
    ["key", "count", "share", "prev", "delta_pct", "trend"],
    ...breakdown.rows.map((row) => [
      row.key,
      row.count,
      row.share,
      row.prev,
      row.delta_pct ?? "",
      row.trend,
    ]),
  ];
}

function salaryCsv(salary: PostingStatsSalary): CsvRows {
  const rows: CsvRows = [["currency", "disclosed", "coverage", "thin_sample", "p25", "p50", "p75"]];
  for (const currency of salary.currencies) {
    rows.push([
      currency.currency,
      currency.disclosed,
      currency.coverage,
      currency.thin_sample,
      currency.p25 ?? "",
      currency.p50 ?? "",
      currency.p75 ?? "",
    ]);
    for (const seniority of currency.by_seniority) {
      rows.push([`  ${seniority.seniority}`, seniority.count, seniority.median ?? ""]);
    }
  }
  return rows;
}

function companiesCsv(overview: CompanyStatsOverview): CsvRows {
  return [
    ["company", "open_postings", "new_in_range", "delta_pct", "trend"],
    ...overview.top_hiring.map((row) => [
      row.name,
      row.open_postings,
      row.new_in_range.count,
      row.new_in_range.delta_pct ?? "",
      row.new_in_range.trend,
    ]),
  ];
}

function allExportRows(
  summary: PostingStatsSummary | null,
  series: PostingStatsTimeseries | null,
  skills: PostingStatsSkills | null,
  breakdown: PostingStatsBreakdown | null,
  salary: PostingStatsSalary | null,
  companySummary: CompanyStatsSummary | null,
  companyOverview: CompanyStatsOverview | null,
): CsvRows {
  const rows: CsvRows = [];
  if (summary) {
    rows.push(
      ["pulse", "count", "prev", "delta_pct", "trend"],
      ["new_24h", summary.new_24h.count, summary.new_24h.prev, summary.new_24h.delta_pct ?? "", summary.new_24h.trend],
      ["new_7d", summary.new_7d.count, summary.new_7d.prev, summary.new_7d.delta_pct ?? "", summary.new_7d.trend],
      ["new_30d", summary.new_30d.count, summary.new_30d.prev, summary.new_30d.delta_pct ?? "", summary.new_30d.trend],
      ["open_total", summary.open_total],
    );
  }
  if (series) {
    rows.push([], ["volume"], ...volumeCsv(series));
  }
  if (skills) {
    rows.push([], ["skills"], ...skillRowsCsv("top", skills.top));
  }
  if (breakdown) {
    rows.push([], [`breakdown:${breakdown.dimension}`], ...breakdownCsv(breakdown));
  }
  if (salary) {
    rows.push([], ["salary"], ...salaryCsv(salary));
  }
  if (companySummary) {
    rows.push([], ["companies"], ["companies_hiring", companySummary.companies_hiring], ["new_companies", companySummary.new_companies.count, companySummary.new_companies.prev, companySummary.new_companies.delta_pct ?? "", companySummary.new_companies.trend]);
  }
  if (companyOverview) {
    rows.push([], ["top_hiring"], ...companiesCsv(companyOverview));
  }
  return rows.length > 0 ? rows : [["market-stats", "no data"]];
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
  const salaryRows = currencies.length > 0 ? salaryCsv(salary as PostingStatsSalary) : [];
  return (
    <ChartCard
      title={t("marketStats.cards.salary")}
      subtitle={t("marketStats.cards.salaryHint")}
      testId="salary"
      table={
        salaryRows.length > 0
          ? {
              caption: t("marketStats.table.salary"),
              head: salaryRows[0].map(String),
              rows: salaryRows.slice(1),
            }
          : undefined
      }
      actions={currencies.length > 0 ? (
        <ChartExport
          name={`salary-${salary?.window ?? ""}`}
          rows={salaryRows}
          title={t("marketStats.export")}
          testId="stats-export-salary"
        />
      ) : null}
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
  const companiesRows =
    overview && overview.top_hiring.length > 0 ? companiesCsv(overview) : [];
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
      <ChartCard
        title={t("marketStats.companies.topHiring")}
        testId="companies-top"
        table={
          companiesRows.length > 0
            ? {
                caption: t("marketStats.table.companies"),
                head: companiesRows[0].map(String),
                rows: companiesRows.slice(1),
              }
            : undefined
        }
        actions={overview && overview.top_hiring.length > 0 ? (
          <ChartExport
            name={`companies-${overview.window}`}
            rows={companiesRows}
            title={t("marketStats.export")}
            testId="stats-export-companies"
          />
        ) : null}
      >
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
