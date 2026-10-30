import type { ReactNode } from "react";

/** One tile of the stat grid (plan 148): a labelled value with an
 * optional hint line. Presentational only — tokens in, no fetching. */
export interface StatTile {
  label: string;
  value: ReactNode;
  hint?: string;
  /** Hover text for the value (e.g. the exact number behind an
   * abbreviated one). */
  title?: string;
  /** Distribution bar share 0–100 (reuses the skill heat ramp tokens). */
  distribution?: number;
}

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
      {tiles.map((tile) => (
        <div
          key={tile.label}
          data-testid="stat-tile"
          className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
        >
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
        </div>
      ))}
    </div>
  );
}
