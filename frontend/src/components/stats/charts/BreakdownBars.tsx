import { useTranslation } from "react-i18next";

import type { BreakdownRow, PostingStatsBreakdown } from "@/api/stats";
import { DeltaBadge } from "./DeltaBadge";

/** The market-structure bars (§D): grouped counts with share + Δ per
 * dimension. Rows carrying a filter mapping are buttons (drill-down law
 * H1 — the chip's count must equal the list it opens); non-mappable
 * dimensions render plain. Bar scale = share of the dimension total. */
export function BreakdownBars({
  breakdown,
  resolveLabel,
  onSelect,
  testKey = "stats-breakdown-row",
}: {
  breakdown: PostingStatsBreakdown;
  resolveLabel: (key: string) => string;
  /** When given, clickable rows apply their filter mapping. */
  onSelect?: (row: BreakdownRow) => void;
  testKey?: string;
}) {
  const { t } = useTranslation();
  if (breakdown.rows.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[var(--as-muted-fg)]">
        {t("marketStats.noData")}
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {breakdown.rows.map((row) => {
        const percent = Math.round(row.share * 100);
        const label = resolveLabel(row.key);
        const rowProps = {
          "data-testid": `${testKey}-${row.key}`,
          className:
            "rounded-lg border border-transparent px-1.5 py-1 text-xs transition-colors hover:bg-[var(--as-muted)]",
        };
        return (
          <li key={`${breakdown.dimension}-${row.key}`}>
            {onSelect ? (
              <button
                type="button"
                {...rowProps}
                className={`block w-full text-left ${rowProps.className}`}
                onClick={() => onSelect(row)}
                title={t("marketStats.browse", { label })}
              >
                <RowLine row={row} label={label} percent={percent} />
              </button>
            ) : (
              <div {...rowProps}>
                <RowLine row={row} label={label} percent={percent} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function RowLine({
  row,
  label,
  percent,
}: {
  row: BreakdownRow;
  label: string;
  percent: number;
}) {
  const { t } = useTranslation();
  return (
    <>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate font-medium text-[var(--as-fg)]">{label}</span>
        <span className="flex items-baseline gap-2 tabular-nums text-[var(--as-muted-fg)]">
          <span>{row.count.toLocaleString()}</span>
          <span className="text-[10px]">{t("marketStats.share", { pct: percent })}</span>
          <DeltaBadge delta={{ count: row.count, prev: row.prev, delta_pct: row.delta_pct, trend: row.trend }} />
        </span>
      </div>
      <div
        role="presentation"
        className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--as-muted)]"
      >
        <div
          className="h-full rounded-full bg-[var(--as-accent,var(--chart-1,#6172f3))]"
          style={{ width: `${percent}%` }}
        />
      </div>
    </>
  );
}
