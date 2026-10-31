import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimeseriesPoint } from "@/api/stats";
import { ChartFrame, SERIES_COLORS } from "./chartKit";

/** The volume-over-time chart (§B and chart-suite workhorse): current
 * buckets as bars (stacked when split), the equal-length previous period
 * as a ghost series and ingestion counts as a second slot. Fixed height;
 * cssvar fills only. Zero-height bars stay (honest zero gaps). */
export function TimeSeriesChart({
  points,
  ghost = false,
  labels,
  height = 200,
}: {
  points: { name: string; count: number; prev: number; series?: Record<string, number> }[];
  /** Show the previous-period ghost bars. */
  ghost?: boolean;
  /** Legend labels: [current, previous, ...split keys]. */
  labels?: { current?: string; prev?: string; series?: { key: string; label: string }[] };
  height?: number;
}) {
  return (
    <ChartFrame height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={points} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--as-border)" />
          <XAxis dataKey="name" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 10 }} allowDecimals={false} width={40} />
          <Tooltip cursor={{ fill: "rgba(0,0,0,0.04)" }} />
          {labels?.series?.length
            ? labels.series.map((entry, index) => (
                <Bar
                  key={entry.key}
                  dataKey={(row: { series?: Record<string, number> }) =>
                    row.series?.[entry.key] ?? 0
                  }
                  name={entry.label}
                  stackId="v"
                  fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                  radius={index === labels.series!.length - 1 ? [3, 3, 0, 0] : undefined}
                  maxBarSize={24}
                />
              ))
            : (
              <>
                {ghost ? (
                  <Bar
                    dataKey="prev"
                    name={labels?.prev}
                    fill="var(--as-muted-fg)"
                    opacity="0.25"
                    radius={[3, 3, 0, 0]}
                    maxBarSize={24}
                  />
                ) : null}
                <Bar
                  dataKey="count"
                  name={labels?.current}
                  fill="var(--as-accent, var(--chart-1, #6172f3))"
                  radius={[3, 3, 0, 0]}
                  maxBarSize={28}
                />
              </>
            )}
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/** Formatting helper the page uses to build chart input rows. */
export function seriesRows(points: TimeseriesPoint[]): {
  name: string;
  count: number;
  prev: number;
  series: Record<string, number>;
}[] {
  return points.map((point) => ({
    name: point.bucket,
    count: point.count,
    prev: point.prev,
    series: point.series,
  }));
}
