import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CsvRows } from "@/components/stats/statsExport";
import { Table } from "@/components/ui";

/** The shared chart-card frame (plan 170): a titled card with an actions
 * slot and a fixed-height chart area — the `ChartCard` every market-stats
 * panel composes. Fixed heights keep recharts' ResponsiveContainer happy
 * in jsdom and the real layout. With a `table` payload a segmented
 * Chart⇄Data toggle joins the actions slot (default Chart, LOCAL state —
 * presentation is not URL state, plan 171 assumption 3); the Data view
 * renders the same `CsvRows` the card's export downloads, so the table
 * is the chart's textual twin by construction (rows ≡ export). */
export interface ChartTable {
  /** Screen-reader caption for the Data view (also its aria-label). */
  caption: string;
  head: string[];
  rows: CsvRows;
}

/** The Data provider for one card's toggle (plan 171 H8).
 *
 * Library-first decision recorded: the assistant-ui `Table` module
 * carries the compact-scroll case already — `[data-as=table]` wraps a
 * real `<table>` in `overflow-x-auto`, owns the header/divide/hover
 * styling and takes plain cell nodes — so no token-styled `<table>`
 * fallback was warranted and no two-app promotion note is filed. Two
 * app-side touches only: `tabular-nums` inherited through the wrapper
 * (`font-variant-numeric` cascades) and the caption surfaced as an
 * `sr-only` line plus the wrapper's `aria-label`, because the module has
 * no caption slot. */
export function StatsTable({ table }: { table: ChartTable }) {
  return (
    <div>
      <p className="sr-only">{table.caption}</p>
      <Table
        headers={table.head}
        aria-label={table.caption}
        className="tabular-nums"
        rows={table.rows.map((row) =>
          row.map((cell) => (cell == null ? "" : String(cell))),
        )}
      />
    </div>
  );
}

const COMPACT_TABLE_ROWS = 5;

/** Compact twin of a data table (plan 195 §3.6): the primary fields as
 * cards, with the full table one tap away. */
function CompactTable({ table }: { table: ChartTable }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  if (expanded) {
    return (
      <div>
        <StatsTable table={table} />
        <button
          type="button"
          className="mt-2 rounded-[var(--as-radius)] border border-[var(--as-border)] px-2.5 py-2 text-xs text-[var(--as-muted-fg)]"
          onClick={() => setExpanded(false)}
          data-testid="stats-table-show-less"
        >
          {t("marketStats.table.showLess")}
        </button>
      </div>
    );
  }
  const [head, ...rows] = [table.head, ...table.rows];
  return (
    <div>
      <p className="sr-only">{table.caption}</p>
      <ul className="space-y-2">
        {rows.slice(0, COMPACT_TABLE_ROWS).map((row, index) => (
          <li
            key={index}
            className="rounded-[var(--as-radius)] border border-[var(--as-border)] p-2 text-xs"
            data-testid="stats-table-card"
          >
            {row.map((cell, cellIndex) => (
              <span key={cellIndex} className="flex justify-between gap-2 py-0.5">
                <span className="text-[var(--as-muted-fg)]">{head[cellIndex] ?? ""}</span>
                <span className="tabular-nums text-[var(--as-fg)]">{cell == null ? "" : String(cell)}</span>
              </span>
            ))}
          </li>
        ))}
      </ul>
      {rows.length > COMPACT_TABLE_ROWS ? (
        <button
          type="button"
          className="mt-2 rounded-[var(--as-radius)] border border-[var(--as-border)] px-2.5 py-2 text-xs text-[var(--as-muted-fg)]"
          onClick={() => setExpanded(true)}
          data-testid="stats-table-view-all"
        >
          {t("marketStats.table.viewAll", { count: rows.length })}
        </button>
      ) : null}
    </div>
  );
}

export function ChartCard({
  title,
  subtitle,
  actions,
  table,
  children,
  testId,
  className = "",
  loading = false,
  error = null,
  onRetry,
  asOf,
  compact = false,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  table?: ChartTable | null;
  children: ReactNode;
  testId: string;
  className?: string;
  loading?: boolean;
  error?: { code: string; message: string } | null;
  onRetry?: () => void;
  asOf?: string;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const [tableMode, setTableMode] = useState<boolean | null>(null);
  const showTable = (tableMode ?? (compact && Boolean(table))) && table != null;
  const toggleClass = (mode: boolean): string =>
    `rounded-[calc(var(--as-radius,0.75rem)-0.2rem)] px-2 py-0.5 text-xs ${
      tableMode === mode
        ? "bg-[var(--as-surface-raised)] font-medium text-[var(--as-fg)]"
        : "text-[var(--as-muted-fg)]"
    }`;
  return (
    <section
      data-testid={`stats-card-${testId}`}
      className={`rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4 ${className}`}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[var(--as-fg)]">{title}</h2>
          {subtitle ? (
            <p className="text-xs text-[var(--as-muted-fg)]">{subtitle}</p>
          ) : null}
          {asOf ? (
            <p className="text-[11px] text-[var(--as-muted-fg)]" data-testid="stats-card-asof">
              {t("marketStats.card.asOf", { date: asOf })}
            </p>
          ) : null}
        </div>
        {error ? null : actions || table ? (
          <div className="flex flex-wrap items-center gap-2">
            {actions}
            {table ? (
              <div
                className="flex items-center gap-0.5 rounded-[var(--as-radius)] border border-[var(--as-border)] p-0.5"
                role="group"
                aria-label={t("marketStats.table.toggleAria")}
                data-testid="stats-table-toggle"
              >
                <button
                  type="button"
                  aria-pressed={(tableMode ?? false) === false}
                  onClick={() => setTableMode(false)}
                  data-testid="stats-table-toggle-chart"
                  className={toggleClass(false)}
                >
                  {t("marketStats.table.chart")}
                </button>
                <button
                  type="button"
                  aria-pressed={(tableMode ?? (compact && Boolean(table))) === true}
                  onClick={() => setTableMode(true)}
                  data-testid="stats-table-toggle-data"
                  className={toggleClass(true)}
                >
                  {t("marketStats.table.data")}
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {loading ? (
        <div
          className="cv-shimmer h-40 rounded-[var(--as-radius)]"
          data-testid="stats-card-loading"
        />
      ) : error ? (
        <div className="space-y-2 py-3" data-testid="stats-card-error">
          <p className="text-xs text-[var(--as-danger)]" role="alert">
            {error.code === "timeout"
              ? t("marketStats.card.timeout")
              : t("marketStats.card.error")}
          </p>
          {onRetry ? (
            <button
              type="button"
              className="rounded-[var(--as-radius)] border border-[var(--as-border)] px-2.5 py-2 text-xs text-[var(--as-fg)]"
              onClick={onRetry}
              data-testid="stats-card-retry"
            >
              {t("marketStats.card.retry")}
            </button>
          ) : null}
        </div>
      ) : showTable && table ? (
        compact ? (
          <CompactTable table={table} />
        ) : (
          <StatsTable table={table} />
        )
      ) : (
        children
      )}
    </section>
  );
}

/** Chart slot: recharts' ResponsiveContainer needs a sized parent. With
 * `ariaLabel` the frame is one labelled image — the card's Chart⇄Data
 * twin is the screen-reader data path. */
export function ChartFrame({
  height,
  children,
  ariaLabel,
}: {
  height: number;
  children: ReactNode;
  ariaLabel?: string;
}) {
  return (
    <div
      style={{ height, width: "100%" }}
      data-testid="stats-chart-frame"
      role={ariaLabel ? "img" : undefined}
      aria-label={ariaLabel}
    >
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
