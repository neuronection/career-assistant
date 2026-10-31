import type { ReactNode } from "react";

/** One tile of the stat grid (plan 148): a labelled value with an
 * optional hint line. Presentational only — tokens in, no fetching.
 * Plan 170 extended the tile with optional interaction (`onClick`,
 * `active`) and a sparkline slot; still presentational, tracking and
 * fetching stay with the page. */
export interface StatTile {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  /** Hover text for the value (e.g. the exact number behind an
   * abbreviated one). */
  title?: string;
  /** Distribution bar share 0–100 (reuses the skill heat ramp tokens). */
  distribution?: number;
  /** Makes the tile a button — the page decides what a click applies. */
  onClick?: () => void;
  /** Selected look for a clickable tile. */
  active?: boolean;
  /** Daily counts (latest last) rendered as the inline sparkline. */
  sparkline?: { count: number }[];
}

const ACCENT = "var(--as-accent, var(--chart-1, #6172f3))";

/** The reusable stat grid (plan 148): label/value tiles with optional
 * per-tile distribution bars (skill-heat-ramp colors). Composable by any
 * page; recorded as a promotion candidate until a second family app
 * needs it (two-app rule). */
export function StatTiles({
  tiles,
  testId = "stat-tiles",
  columns = 5,
  layout = "fixed",
}: {
  tiles: StatTile[];
  testId?: string;
  columns?: number;
  /** `auto` wraps tiles on narrow containers (audit dashboard, plan 151);
   * `fixed` keeps the historic exact-grid behavior. */
  layout?: "fixed" | "auto";
}) {
  if (tiles.length === 0) return null;
  return (
    <div
      data-testid={testId}
      className={`grid gap-3${layout === "auto" ? " grid-cols-[repeat(auto-fit,minmax(7rem,1fr))]" : ""}`}
      style={
        layout === "fixed"
          ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }
          : undefined
      }
    >
      {tiles.map((tile) => {
        const body: ReactNode = (
          <>
            {tile.sparkline && tile.sparkline.length > 1 ? (
              <TileSparkline counts={tile.sparkline.map((point) => point.count)} />
            ) : null}
            <p className="text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {tile.label}
            </p>
            <p
              className="mt-0.5 text-lg font-semibold tabular-nums text-[var(--as-fg)]"
              data-testid="stat-tile-value"
              title={tile.title}
            >
              {tile.value}
            </p>
            {tile.hint ? (
              <p className="text-xs text-[var(--as-muted-fg)]">{tile.hint}</p>
            ) : null}
            {tile.distribution != null ? (
              <div
                className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-[var(--as-muted)]"
                role="presentation"
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.max(0, Math.min(100, tile.distribution))}%`,
                    background: "var(--ca-heat-hot)",
                  }}
                />
              </div>
            ) : null}
          </>
        );
        const shared = {
          "data-testid": tile.onClick ? "stat-tile-action" : "stat-tile",
          className: `rounded-[var(--as-radius)] border p-3 text-left ${
            tile.onClick
              ? "cursor-pointer border-[var(--as-border)] bg-[var(--as-surface)] transition-colors hover:bg-[var(--as-surface-raised)]"
              : "border-[var(--as-border)] bg-[var(--as-surface)]"
          } ${
            tile.active
              ? "border-[var(--as-accent,var(--chart-1,#6172f3))] shadow-[0_0_0_1px_var(--as-accent,var(--chart-1,#6172f3))]"
              : ""
          }`,
        };
        if (tile.onClick) {
          return (
            <button
              key={tile.label}
              type="button"
              aria-pressed={!!tile.active}
              onClick={(event) => {
                event.stopPropagation();
                tile.onClick?.();
              }}
              {...shared}
            >
              {body}
            </button>
          );
        }
        return (
          <div key={tile.label} {...shared}>
            {body}
          </div>
        );
      })}
    </div>
  );
}

function TileSparkline({ counts }: { counts: number[] }) {
  const width = 64;
  const height = 16;
  const max = Math.max(1, ...counts);
  const step = counts.length > 1 ? width / (counts.length - 1) : width;
  const points = counts
    .map((count, index) => {
      const x = (index * step).toFixed(1);
      const y = (height - (count / max) * (height - 2)).toFixed(1);
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="ml-auto block h-4 w-16"
      role="presentation"
      aria-hidden
    >
      <polyline
        points={points}
        fill="none"
        stroke={ACCENT}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
