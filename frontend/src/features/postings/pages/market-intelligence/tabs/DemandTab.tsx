import { useTranslation } from "react-i18next";

import { ClockworkCard } from "@/components/stats/charts/ClockworkCard";
import { DimensionsCard, VolumeCard, NoData } from "../cards";
import { compareRange, type MarketStatsView } from "../../marketStatsParams";
import { ChartCard } from "@/components/stats/charts/chartKit";
import { useCompareSeries, type TabProps } from "./shared";

function compareHint(
  view: MarketStatsView,
  failed: boolean,
  overlay: { cropped: number; padded: number } | null,
  range: boolean,
  t: (key: string, options?: Record<string, unknown>) => string,
): string | null {
  if (view.compare !== "custom") return null;
  if (failed) return t("marketStats.compare.error");
  if (view.split) return t("marketStats.compare.paused");
  if (!range) {
    return view.window === "all"
      ? t("marketStats.compare.hintAll")
      : t("marketStats.compare.hintDates");
  }
  if (!overlay) return null;
  if (overlay.cropped > 0) return t("marketStats.compare.hintCrop", { count: overlay.cropped });
  if (overlay.padded > 0) return t("marketStats.compare.hintPad", { count: overlay.padded });
  return null;
}

export function DemandTab({ data, view, loading, compact, refresh, onPatch, onDrill }: TabProps) {
  const { t } = useTranslation();
  const { overlay, error: compareFailed } = useCompareSeries(view, data.timeseries);
  const range = compareRange(view) !== null;
  const hint = compareHint(view, compareFailed, overlay, range, t);
  const clockworkError = data.errors.clockwork ?? null;
  return (
    <div className="space-y-4">
      <VolumeCard
        series={data.timeseries}
        view={view}
        overlay={overlay}
        hint={hint}
        loading={loading}
        error={data.errors.timeseries ?? null}
        onRetry={refresh}
        onSplit={(split) => onPatch({ split })}
        compact={compact}
      />
      {data.clockwork ? (
        <ClockworkCard
          clock={data.clockwork}
          compact={compact}
          loading={loading}
          error={clockworkError}
          onRetry={refresh}
        />
      ) : (
        <ChartCard
          title={t("marketStats.cards.rhythm")}
          testId="rhythm"
          loading={loading}
          error={clockworkError}
          onRetry={refresh}
        >
          <NoData />
        </ChartCard>
      )}
      <DimensionsCard
        breakdown={data.breakdown}
        view={view}
        loading={loading}
        error={data.errors.breakdown ?? null}
        onRetry={refresh}
        onDimension={(dimension) => onPatch({ dimension })}
        onDrill={(dimension, key) => onDrill(dimensionDrillParams(dimension, key))}
        compact={compact}
      />
    </div>
  );
}

export function dimensionDrillParams(dimension: string, key: string): string {
  const axis: Record<string, string> = {
    seniority: "seniority",
    work_mode: "remote_policy",
    source: "source",
    org: "org",
    contract: "contract",
    education: "education_min",
    family: "mapped_family",
    location: "country",
  };
  const name = axis[dimension];
  if (!name) return "";
  return `${name}=${encodeURIComponent(key)}`;
}
