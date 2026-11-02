import {
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { useTranslation } from "react-i18next";

import type { SkillStat } from "@/api/stats";
import { ChartFrame, CHART_COLORS } from "./chartKit";

export type QuadrantKey = "established" | "risingStars" | "fading" | "niche";

/** The skills demand quadrant (H3): x = share of postings asking (volume
 * axis), y = momentum vs the previous window, mark size = count — the
 * rising-stars / established / fading / niche read. Movable marks are
 * draggable only through the linked list; the chart itself stays a flat
 * read (drill-down law H1: hover names the skill, list rows navigate). */
export function ScatterQuadrant({
  rows,
  onSelect,
  height = 220,
}: {
  rows: SkillStat[];
  onSelect?: (row: SkillStat) => void;
  height?: number;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-[var(--as-muted-fg)]">
        {t("marketStats.noData")}
      </p>
    );
  }
  const data = rows.map((row) => ({
    row,
    x: Math.round(row.share * 1000) / 10,
    y: row.delta_pct == null ? 0 : Math.round(row.delta_pct * 10) / 10,
    z: Math.max(1, row.count),
  }));
  return (
    <ChartFrame height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--as-border)" />
          <XAxis
            dataKey="x"
            tick={{ fontSize: 10 }}
            unit="%"
            name={t("marketStats.quadrant.share")}
          />
          <YAxis
            dataKey="y"
            tick={{ fontSize: 10 }}
            width={44}
            unit="%"
            name={t("marketStats.quadrant.momentum")}
          />
          <ZAxis dataKey="z" range={[20, 300]} />
          <ReferenceLine y={0} stroke={CHART_COLORS.muted} strokeDasharray="4 4" />
          <Tooltip
            content={({ payload }) => {
              const row: SkillStat | undefined = payload?.[0]?.payload?.row;
              if (!row) return null;
              return (
                <div className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1 text-xs text-[var(--as-fg)] shadow-sm">
                  {row.label} · {row.count.toLocaleString()}
                  {row.delta_pct != null ? (
                    <span className="ml-1 text-[var(--as-muted-fg)]">
                      {row.delta_pct > 0 ? "+" : ""}
                      {Math.round(row.delta_pct)}%
                    </span>
                  ) : null}
                </div>
              );
            }}
          />
          <Scatter
            name={t("marketStats.quadrant.title")}
            data={data}
            onClick={(entry: { row: SkillStat }) => onSelect?.(entry.row)}
            cursor={onSelect ? "pointer" : "default"}
          >
            {data.map((entry) => (
              <Cell
                key={entry.row.key}
                fill={bubbleColor(entry.y)}
                stroke="var(--as-surface)"
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

function bubbleColor(momentum: number): string {
  if (momentum > 2) return CHART_COLORS.success;
  if (momentum < -2) return CHART_COLORS.danger;
  return CHART_COLORS.accent;
}
