import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { useTranslation } from "react-i18next";

import { ChartFrame, SERIES_COLORS } from "./chartKit";

/** The category-mix donut (§C): slices share of postings — token hues
 * only; legal labels resolve client-side. */
export function DonutChart({
  slices,
  height = 180,
  outerRadius = 70,
  innerRadius = 44,
}: {
  slices: { key: string; label: string; count: number }[];
  height?: number;
  outerRadius?: number;
  innerRadius?: number;
}) {
  const { t } = useTranslation();
  if (slices.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-[var(--as-muted-fg)]">
        {t("marketStats.noData")}
      </p>
    );
  }
  return (
    <ChartFrame height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={slices}
            dataKey="count"
            nameKey="label"
            innerRadius={innerRadius}
            outerRadius={outerRadius}
            paddingAngle={1}
            stroke="var(--as-surface)"
          >
            {slices.map((slice, index) => (
              <Cell key={slice.key} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value: number | string, name: string) => [
              `${Number(value).toLocaleString()}`,
              name,
            ]}
          />
        </PieChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
