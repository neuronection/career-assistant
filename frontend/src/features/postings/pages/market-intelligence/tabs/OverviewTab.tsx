import { useTranslation } from "react-i18next";

import { ChartCard } from "@/components/stats/charts/chartKit";
import { InsightsStrip } from "@/components/stats/charts/InsightsStrip";
import { NoData, OverviewCard, PulseTiles } from "../cards";
import type { TabProps } from "./shared";

export function OverviewTab({ data, loading, refresh, onDrill, onDrillOpen }: TabProps) {
  const { t } = useTranslation();
  const error = data.errors.overview ?? null;
  return (
    <div className="space-y-4">
      <ChartCard
        title={t("marketStats.cards.insights")}
        testId="insights"
        loading={loading}
        error={error}
        onRetry={refresh}
      >
        {data.overview && data.overview.insights.length > 0 ? (
          <InsightsStrip insights={data.overview.insights} />
        ) : (
          <NoData />
        )}
      </ChartCard>
      <PulseTiles
        summary={data.summary}
        loading={loading}
        error={data.errors.summary ?? null}
        onRetry={refresh}
        onDrill={onDrill}
        onDrillOpen={onDrillOpen}
      />
      <OverviewCard
        overview={data.overview}
        loading={loading}
        error={error}
        onRetry={refresh}
        onDrill={onDrill}
      />
    </div>
  );
}
