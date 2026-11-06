import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimeseriesPoint } from "@/api/stats";
import { ChartFrame, CHART_COLORS, SERIES_COLORS } from "./chartKit";

/** The volume-over-time chart (§B and chart-suite workhorse): current
 * buckets as bars (stacked when split), the enabled comparison as
 * ghost bars, and — in custom-compare mode (plan 171 H9) — the B window
 * as a dashed token-colored line over the same offset grid, with a
 * localized legend (Selected window / Previous / Comparison). Fixed
 * height; cssvar fills only. Zero-height bars stay (honest zero gaps). */
export function TimeSeriesChart({
  points,
  ghost = false,
  labels,
  compareLabel,
  height = 200,
  ariaLabel,
}: {
  points: { name: string; count: number; prev: number; series?: Record<string, number>; compare?: number }[];
  /** Show the previous-period ghost bars. */
  ghost?: boolean;
  /** Legend labels: [current, previous, ...split keys]. */
  labels?: { current?: string; prev?: string; series?: { key: string; label: string }[] };
  /** When set (custom compare), the merged B series rides as a line and
   * the three-name legend renders. */
  compareLabel?: string;
  height?: number;
  ariaLabel?: string;
}) {
  return (
    <ChartFrame height={height} ariaLabel={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
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
                {compareLabel ? (
                  <Line
                    type="monotone"
                    dataKey="compare"
                    name={compareLabel}
                    stroke={CHART_COLORS.chart4}
                    strokeDasharray="6 3"
                    strokeWidth={2}
                    dot={false}
                  />
                ) : null}
              </>
            )}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/** The localized compare legend under the chart (H10 design rule 1's
 * naming: selected window / previous ghost / custom comparison). */
export function TimeSeriesLegend({
  current,
  prev,
  compare,
}: {
  current: string;
  prev: string;
  compare: string;
}) {
  return (
    <ul className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--as-muted-fg)]">
      <li className="flex items-center gap-1" data-testid="stats-legend-current">
        <span
          className="inline-block h-2.5 w-3 rounded-sm"
          style={{ background: "var(--as-accent, var(--chart-1, #6172f3))" }}
          aria-hidden
        />
        {current}
      </li>
      <li className="flex items-center gap-1" data-testid="stats-legend-prev">
        <span
          className="inline-block h-2.5 w-3 rounded-sm"
          style={{ background: "color-mix(in srgb, var(--as-muted-fg) 25%, transparent)" }}
          aria-hidden
        />
        {prev}
      </li>
      <li className="flex items-center gap-1" data-testid="stats-legend-compare">
        <span
          className="inline-block h-0 w-4 border-t-2 border-dashed"
          style={{ borderColor: CHART_COLORS.chart4 }}
          aria-hidden
        />
        {compare}
      </li>
    </ul>
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
