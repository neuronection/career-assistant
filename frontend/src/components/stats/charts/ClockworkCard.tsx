import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import type { ClockCell, PostingStatsClockwork } from "@/api/stats";
import { ChartCard, type ChartTable } from "@/components/stats/charts/chartKit";
import type { CsvValue } from "@/components/stats/statsExport";

export const HOUR_TICKS = [0, 6, 12, 18, 23];

const HEAT_LEVELS = [8, 24, 40, 56, 72];
const HEAT_MAX_MIX = 72;

/** One ramp band per count: quantized steps of the `--ca-heat-hot` mix
 * (level 0 = zero → muted tone, top level = the full 72% hotness). */
export function heatLevel(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  return Math.min(
    HEAT_LEVELS.length,
    1 + Math.floor(((count - 1) / max) * HEAT_LEVELS.length),
  );
}

export function heatFill(level: number): string {
  if (level <= 0) return "var(--as-muted)";
  const mix = HEAT_LEVELS[level - 1] ?? HEAT_MAX_MIX;
  return `color-mix(in srgb, var(--ca-heat-hot) ${mix}%, transparent)`;
}

/* The condensed a11y twin of the matrix (H8): by_weekday (7 rows),
 * by_hour (24 rows) and the peak — never the 168 cells — lives in the
 * card's `table` payload below. */

function zeroPad(value: number): string {
  return String(value).padStart(2, "0");
}

/** The weekday x hour posting clock (plan 171 H7): a 7×24 CSS grid of
 * divs — no recharts, 168 plain nodes stay jsdom-cheap — quantized over
 * the `--ca-heat-hot` token ramp with `color-mix(... %, transparent)`
 * (never Tailwind opacity modifiers on tokens). Zero cells tone muted,
 * the deterministic peak cell ringed, the weekday axis Mon..Sun
 * localized, hour ticks at 0/6/12/18/23, and a condensable `sr-only`
 * summary for the whole matrix. The H8 table view condenses to
 * by_weekday + by_hour + peak rows, never the 168 cells. Times are UTC —
 * the wire says so and the caption repeats it. */
export function ClockworkCard({ clock }: { clock: PostingStatsClockwork }) {
  const { t } = useTranslation();
  const cellAt = new Map<string, ClockCell>(
    clock.cells.map((cell) => [`${cell.weekday}-${cell.hour}`, cell]),
  );
  const max = clock.cells.reduce((best, cell) => Math.max(best, cell.count), 0);
  const weekdayLabel = (weekday: number): string =>
    t(`marketStats.rhythm.weekday.${weekday}`);
  const hourLabel = (hour: number): string =>
    t("marketStats.rhythm.hour", { hour: zeroPad(hour) });
  const cellLabel = (weekday: number, hour: number): string =>
    `${weekdayLabel(weekday)} ${hourLabel(hour)}`;

  const byWeekday = clock.by_weekday
    .map((count, index) =>
      t("marketStats.rhythm.totalPair", { label: weekdayLabel(index + 1), count }),
    )
    .join(", ");
  const byHour = clock.by_hour
    .map((count, hour) =>
      t("marketStats.rhythm.totalPair", { label: hourLabel(hour), count }),
    )
    .join(", ");
  const summary = [
    clock.peak
      ? t("marketStats.rhythm.summaryPeak", {
          cell: cellLabel(clock.peak.weekday, clock.peak.hour),
        })
      : "",
    byWeekday || byHour ? t("marketStats.rhythm.summaryByWeekday", { totals: byWeekday }) : "",
    byHour ? t("marketStats.rhythm.summaryByHour", { totals: byHour }) : "",
  ]
    .filter(Boolean)
    .join(" ");

  const table: ChartTable = {
    caption: t("marketStats.table.rhythm"),
    head: ["when", "postings"],
    rows: [
      ...clock.by_weekday.map((count, index) => [weekdayLabel(index + 1), count]),
      ...clock.by_hour.map((count, hour) => [hourLabel(hour), count]),
      ...(clock.peak
        ? [
            [
              cellLabel(clock.peak.weekday, clock.peak.hour),
              clock.peak.count,
            ] as CsvValue[],
          ]
        : []),
    ],
  };

  return (
    <ChartCard
      title={t("marketStats.cards.rhythm")}
      subtitle={t("marketStats.cards.rhythmHint")}
      testId="rhythm"
      table={table}
    >
      <div
        className="overflow-x-auto"
        role="group"
        aria-label={t("marketStats.rhythm.gridAria")}
        data-testid="stats-rhythm-grid"
      >
        <div
          className="grid min-w-[560px] gap-px"
          style={{ gridTemplateColumns: "auto repeat(24, minmax(0, 1fr))" }}
        >
          <span />
          {Array.from({ length: 24 }, (_, hour) => (
            <span
              key={`tick-${hour}`}
              className="pb-1 text-center text-[9px] tabular-nums text-[var(--as-muted-fg)]"
            >
              {HOUR_TICKS.includes(hour) ? zeroPad(hour) : ""}
            </span>
          ))}
          {Array.from({ length: 7 }, (_, index) => index + 1).map((weekday) => (
            <Fragment key={`weekday-${weekday}`}>
              <span className="w-8 pr-1.5 text-right text-[9px] leading-3 text-[var(--as-muted-fg)]">
                {weekdayLabel(weekday)}
              </span>
              {Array.from({ length: 24 }, (_, hour) => {
                const count = cellAt.get(`${weekday}-${hour}`)?.count ?? 0;
                const level = heatLevel(count, max);
                const peaked =
                  clock.peak !== null &&
                  clock.peak.weekday === weekday &&
                  clock.peak.hour === hour &&
                  count > 0;
                return (
                  <div
                    key={`cell-${weekday}-${hour}`}
                    data-testid="stats-rhythm-cell"
                    data-w={weekday}
                    data-h={hour}
                    data-level={level}
                    title={t("marketStats.rhythm.cellTitle", {
                      cell: cellLabel(weekday, hour),
                      count,
                    })}
                    className="h-3 rounded-[3px]"
                    style={{
                      background: heatFill(level),
                      ...(peaked
                        ? { boxShadow: "0 0 0 2px var(--as-accent, var(--chart-1, #6172f3))" }
                        : {}),
                    }}
                  />
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
      {clock.peak ? (
        <p className="mt-2 text-[11px] text-[var(--as-muted-fg)]" data-testid="stats-rhythm-peak">
          {t("marketStats.rhythm.peak", {
            cell: cellLabel(clock.peak.weekday, clock.peak.hour),
          })}
        </p>
      ) : null}
      {summary ? <p className="sr-only">{summary}</p> : null}
    </ChartCard>
  );
}
