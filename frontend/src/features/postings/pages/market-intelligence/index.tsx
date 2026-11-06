import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Copy, Download, RotateCw } from "lucide-react";

import { downloadStatsCsv } from "@/components/stats/statsExport";
import { EmptyState } from "@/components/ui";
import { copyText } from "@/lib/clipboard";
import { formatDateTime } from "@/lib/format";
import {
  MARKET_TABS,
  parseView,
  toSearchParams,
  type MarketTab,
  type MarketStatsView,
} from "../marketStatsParams";
import { buildListUrl, buildOpenTotalUrl, isExactDrillWindow } from "./buildListUrl";
import { StatsFilterBar } from "./StatsFilterBar";
import { allExportRows } from "./exportRows";
import { useContainerBand, type ContainerBand } from "@/hooks/useContainerBand";
import { useDashboardQuery } from "./useDashboardQuery";
import type { TabProps } from "./tabs/shared";

const OverviewTab = lazy(() =>
  import("./tabs/OverviewTab").then((module) => ({ default: module.OverviewTab })),
);
const DemandTab = lazy(() =>
  import("./tabs/DemandTab").then((module) => ({ default: module.DemandTab })),
);
const SkillsTab = lazy(() =>
  import("./tabs/SkillsTab").then((module) => ({ default: module.SkillsTab })),
);
const PayTab = lazy(() =>
  import("./tabs/PayTab").then((module) => ({ default: module.PayTab })),
);
const CompaniesTab = lazy(() =>
  import("./tabs/CompaniesTab").then((module) => ({ default: module.CompaniesTab })),
);

const TAB_LABELS: Record<MarketTab, string> = {
  overview: "marketStats.tabs.overview",
  demand: "marketStats.tabs.demand",
  skills: "marketStats.tabs.skills",
  pay: "marketStats.tabs.pay",
  companies: "marketStats.tabs.companies",
};

function withExtra(url: string, extra: string): string {
  const target = new URL(url, "http://placeholder");
  if (extra) {
    for (const [key, value] of new URLSearchParams(extra)) {
      target.searchParams.set(key, value);
    }
  }
  return `${target.pathname}${target.search}`;
}

export function MarketIntelligence({ band: bandOverride }: { band?: ContainerBand } = {}) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { ref, band } = useContainerBand(bandOverride);
  const view = useMemo(() => parseView(searchParams), [searchParams]);
  const viewRef = useRef(view);
  viewRef.current = view;
  const { data, loading, failed, errorMessage, refresh } = useDashboardQuery(view);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const copyReset = useRef(0);

  useEffect(() => {
    const canonical = toSearchParams(parseView(searchParams)).toString();
    if (canonical !== searchParams.toString()) {
      setSearchParams(new URLSearchParams(canonical), { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = useCallback(
    (update: Partial<MarketStatsView>) => {
      setSearchParams(toSearchParams({ ...viewRef.current, ...update }), { replace: true });
    },
    [setSearchParams]
  );

  const onDrill = useCallback(
    (extra: string) => navigate(withExtra(buildListUrl(viewRef.current), extra)),
    [navigate]
  );

  const onDrillOpen = useCallback(
    () => navigate(buildOpenTotalUrl(viewRef.current)),
    [navigate]
  );

  const copyLink = useCallback(async () => {
    const ok = await copyText(`${window.location.origin}${location.pathname}${location.search}`);
    setCopyState(ok ? "copied" : "failed");
    window.clearTimeout(copyReset.current);
    copyReset.current = window.setTimeout(() => setCopyState("idle"), 1600);
  }, [location.pathname, location.search]);

  const initialLoading = loading && !data;
  const tabProps: TabProps | null = data
    ? {
        data,
        view,
        loading: initialLoading,
        compact: band === "compact",
        refresh,
        onPatch: patch,
        onDrill,
        onDrillOpen,
      }
    : null;

  return (
    <div
      ref={ref}
      className="ca-workspace ca-mi space-y-4"
      data-testid="market-stats"
      data-band={band}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-[var(--as-fg)]">{t("marketStats.title")}</h1>
          <p className="text-sm text-[var(--as-muted-fg)]">{t("marketStats.subtitle")}</p>
          {data ? (
            <p className="text-[11px] text-[var(--as-muted-fg)]" data-testid="market-stats-asof">
              {t("marketStats.freshness.asOf", { date: formatDateTime(data.as_of) })}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void copyLink()}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-full border border-[var(--as-border)] px-3 text-xs font-medium text-[var(--as-muted-fg)]"
            data-testid="stats-copy-link"
            title={copyState === "failed" ? t("marketStats.copy.failed") : t("marketStats.copy.link")}
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
            onClick={() =>
              data &&
              downloadStatsCsv(
                view.window,
                allExportRows({
                  summary: data.summary,
                  series: data.timeseries,
                  skills: data.skills,
                  breakdown: data.breakdown,
                  salary: data.salary,
                  companySummary: data.companies_summary,
                  companyOverview: data.companies_overview,
                }),
              )
            }
            disabled={!data || loading}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-full border border-[var(--as-border)] px-3 text-xs font-medium text-[var(--as-muted-fg)]"
            data-testid="stats-export"
            title={t("marketStats.exportAll")}
          >
            <Download className="size-3" aria-hidden />
            {t("marketStats.export")}
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-full border border-[var(--as-border)] px-3 text-xs font-medium text-[var(--as-muted-fg)]"
            data-testid="market-stats-refresh-header"
            title={t("marketStats.filters.refresh")}
          >
            <RotateCw className={`size-3 ${loading ? "animate-spin" : ""}`} aria-hidden />
          </button>
        </div>
      </div>

      <StatsFilterBar
        view={view}
        band={band}
        loading={loading}
        onPatch={patch}
        onRefresh={refresh}
      />
      {!isExactDrillWindow(view) ? (
        <p className="text-xs text-[var(--as-warning)]" data-testid="market-stats-drill-hint">
          {t("marketStats.drill.nearestPreset")}
        </p>
      ) : null}

      <div
        role="tablist"
        aria-label={t("marketStats.tabs.aria")}
        className="ca-mi-tabs flex gap-1 overflow-x-auto"
      >
        {MARKET_TABS.map((tab, index) => {
          const selected = view.tab === tab;
          return (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              onClick={() => patch({ tab })}
              onKeyDown={(event) => {
                if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
                event.preventDefault();
                const next = MARKET_TABS[(index + (event.key === "ArrowRight" ? 1 : -1) + MARKET_TABS.length) % MARKET_TABS.length];
                patch({ tab: next });
              }}
              className={`ca-mi-tab min-h-[44px] whitespace-nowrap rounded-full px-3 text-xs font-medium ${
                selected
                  ? "bg-[var(--as-surface-raised)] text-[var(--as-fg)]"
                  : "text-[var(--as-muted-fg)]"
              }`}
              data-testid={`market-stats-tab-${tab}`}
            >
              {t(TAB_LABELS[tab])}
            </button>
          );
        })}
      </div>

      {failed && !data ? (
        <div className="space-y-2" data-testid="market-stats-error">
          <p className="text-sm text-[var(--as-danger)]">{t("marketStats.error")}</p>
          <p className="text-xs text-[var(--as-muted-fg)]">{errorMessage}</p>
          <button
            type="button"
            onClick={refresh}
            className="min-h-[44px] rounded-lg border border-[var(--as-border)] px-3 text-sm text-[var(--as-fg)]"
            data-testid="market-stats-retry"
          >
            {t("marketStats.card.retry")}
          </button>
        </div>
      ) : initialLoading && !tabProps ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="market-stats-skeleton">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="cv-shimmer h-56 rounded-[var(--as-radius-lg)]" />
          ))}
        </div>
      ) : tabProps ? (
        <div className="space-y-4" data-testid={`market-stats-tabpanel-${view.tab}`}>
          <Suspense
            fallback={
              <div
                className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
                data-testid="market-stats-tab-loading"
              >
                {Array.from({ length: 3 }, (_, index) => (
                  <div key={index} className="cv-shimmer h-56 rounded-[var(--as-radius-lg)]" />
                ))}
              </div>
            }
          >
            {view.tab === "overview" ? <OverviewTab {...tabProps} /> : null}
            {view.tab === "demand" ? <DemandTab {...tabProps} /> : null}
            {view.tab === "skills" ? <SkillsTab {...tabProps} /> : null}
            {view.tab === "pay" ? <PayTab {...tabProps} /> : null}
            {view.tab === "companies" ? <CompaniesTab {...tabProps} /> : null}
          </Suspense>
        </div>
      ) : (
        <EmptyState compact title={t("marketStats.noData")} />
      )}

      <footer
        className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] px-4 py-3 text-xs text-[var(--as-muted-fg)]"
        data-testid="market-stats-footer"
      >
        {data?.overview ? (
          <>
            <span>{t("marketStats.coverage.salary", { pct: percent(data.overview.coverage.salary) })}</span>
            <span>{t("marketStats.coverage.location", { pct: percent(data.overview.coverage.location) })}</span>
            <span>{t("marketStats.coverage.orgLinked", { pct: percent(data.overview.coverage.org_linked) })}</span>
            <span>{t("marketStats.coverage.skillTagged", { pct: percent(data.overview.coverage.skill_tagged) })}</span>
          </>
        ) : null}
        {data?.summary ? (
          <span data-testid="stats-freshness-asof-footer">
            {t("marketStats.freshness.asOf", { date: formatDateTime(data.summary.freshness.as_of) })}
          </span>
        ) : null}
        {data?.summary && data.summary.freshness.stale_sources.length > 0 ? (
          <span className="text-[var(--as-warning)]" data-testid="stats-freshness-stale">
            {t("marketStats.freshness.stale", {
              sources: data.summary.freshness.stale_sources.map((source) => source.source_key).join(", "),
            })}
          </span>
        ) : null}
      </footer>
    </div>
  );
}

function percent(share: number): number {
  return Math.round(share * 100);
}
