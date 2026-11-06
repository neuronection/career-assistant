import { useTranslation } from "react-i18next";

import type { StatsDelta } from "@/api/stats";

/** The trend badge (§A): number-in % with an up/down/flat arrow — green
 * when rising, red when falling, neutral when steady, "new" when the
 * previous window counted zero (the wire sends `delta_pct: null`). */
export function DeltaBadge({
  delta,
  testId,
}: {
  delta: StatsDelta;
  testId?: string;
}) {
  const { t } = useTranslation();
  const rising = delta.trend === "up";
  const falling = delta.trend === "down";
  if (delta.prev === 0 && delta.count === 0) return null;
  const label =
    delta.delta_pct == null
      ? t("marketStats.delta.new")
      : t("marketStats.delta.vsPrev", {
          pct: Math.abs(Math.round(delta.delta_pct)),
        });
  const color = rising
    ? "text-[var(--as-success,var(--chart-2,#22c55e))]"
    : falling
      ? "text-[var(--as-danger,var(--chart-5,#ef4444))]"
      : "text-[var(--as-muted-fg)]";
  const arrow = rising ? "↑" : falling ? "↓" : delta.trend === "flat" ? "→" : "";
  return (
    <span
      data-testid={testId ?? "stats-delta"}
      className={`inline-flex items-center gap-0.5 whitespace-nowrap text-[11px] font-medium tabular-nums ${color}`}
    >
      {arrow && <span aria-hidden>{arrow}</span>}
      {label}
    </span>
  );
}
