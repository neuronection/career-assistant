import type { ReactNode } from "react";

/** The shared chart-card frame (plan 170): a titled card with an actions
 * slot and a fixed-height chart area — the `ChartCard` every market-stats
 * panel composes. Fixed heights keep recharts' ResponsiveContainer happy
 * in jsdom and the real layout. */
export function ChartCard({
  title,
  subtitle,
  actions,
  children,
  testId,
  className = "",
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  testId: string;
  className?: string;
}) {
  return (
    <section
      data-testid={`stats-card-${testId}`}
      className={`rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4 ${className}`}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-[var(--as-fg)]">{title}</h3>
          {subtitle ? (
            <p className="text-xs text-[var(--as-muted-fg)]">{subtitle}</p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>
      {children}
    </section>
  );
}

/** Chart slot: recharts' ResponsiveContainer needs a sized parent. */
export function ChartFrame({
  height,
  children,
}: {
  height: number;
  children: ReactNode;
}) {
  return (
    <div style={{ height, width: "100%" }} data-testid="stats-chart-frame">
      {children}
    </div>
  );
}

export const ACCENT = "var(--as-accent, var(--chart-1, #6172f3))";

export const CHART_COLORS = {
  accent: ACCENT,
  success: "var(--as-success, var(--chart-2, #22c55e))",
  danger: "var(--as-danger, var(--chart-5, #ef4444))",
  warning: "var(--as-warning, var(--chart-4, #f59e0b))",
  muted: "var(--as-muted-fg)",
  chart3: "var(--chart-3, #f97316)",
  chart4: "var(--chart-4, #f59e0b)",
  chart5: "var(--chart-5, #ef4444)",
  chart6: "var(--chart-6, #14b8a6)",
} as const;

/** Series palette for split charts and donuts — token thumbs only. */
export const SERIES_COLORS = [
  ACCENT,
  "var(--chart-2, #22c55e)",
  "var(--chart-3, #f97316)",
  "var(--chart-4, #f59e0b)",
  "var(--chart-5, #ef4444)",
  "var(--chart-6, #14b8a6)",
] as const;
