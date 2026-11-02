import { useTranslation } from "react-i18next";

import type { SkillStat } from "@/api/stats";

/** Skill trend rows (§C + rail top skills): rank, count, share and a
 * trend arrow per skill. Rows with a filter mapping navigate (H1); the
 * lists without one render plain. */
export function SkillTrendList({
  rows,
  onSelect,
  max = 10,
  testKey = "stats-skill-trend",
}: {
  rows: SkillStat[];
  onSelect?: (row: SkillStat) => void;
  max?: number;
  testKey?: string;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-[var(--as-muted-fg)]">
        {t("marketStats.noData")}
      </p>
    );
  }
  return (
    <ul className="space-y-1.5">
      {rows.slice(0, max).map((row, index) => {
        const motion = riseMark(row.delta_pct);
        return (
          <li key={row.key}>
            {onSelect ? (
              <button
                type="button"
                onClick={() => onSelect(row)}
                data-testid={`${testKey}-${row.key}`}
                className="w-full rounded-lg px-1.5 py-1 text-xs transition-colors hover:bg-[var(--as-muted)]"
                title={t("marketStats.browseSkill", { skill: row.label })}
              >
                <RowContent row={row} index={index} motion={motion} />
              </button>
            ) : (
              <div
                data-testid={`${testKey}-${row.key}`}
                className="rounded-lg px-1.5 py-1 text-xs"
              >
                <RowContent row={row} index={index} motion={motion} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function RowContent({
  row,
  index,
  motion,
}: {
  row: SkillStat;
  index: number;
  motion: { glyph: string; color: string } | null;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="w-4 shrink-0 text-right tabular-nums text-[10px] text-[var(--as-muted-fg)]">
        {index + 1}
      </span>
      <span className="min-w-0 flex-1 truncate font-medium text-[var(--as-fg)]">
        {row.label}
      </span>
      {motion ? (
        <span
          className={`shrink-0 text-[11px] ${motion.color}`}
          aria-label={t("marketStats.skills.trendAria", { pct: Math.abs(Math.round(row.delta_pct ?? 0)) })}
        >
          {motion.glyph}
        </span>
      ) : null}
      <span className="shrink-0 tabular-nums text-[var(--as-muted-fg)]">
        {row.count.toLocaleString()}
      </span>
      <span className="w-10 shrink-0 text-right tabular-nums text-[10px] text-[var(--as-muted-fg)]">
        {Math.round(row.share * 100)}%
      </span>
    </div>
  );
}

function riseMark(deltaPct: number | null): { glyph: string; color: string } | null {
  if (deltaPct == null) return null;
  if (deltaPct > 2)
    return { glyph: "↑", color: "text-[var(--as-success,var(--chart-2,#22c55e))]" };
  if (deltaPct < -2)
    return { glyph: "↓", color: "text-[var(--as-danger,var(--chart-5,#ef4444))]" };
  return { glyph: "→", color: "text-[var(--as-muted-fg)]" };
}
