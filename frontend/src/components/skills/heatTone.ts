export type HeatTone = "cold" | "warm" | "hot" | "none";

export const HEAT_COLOR: Record<HeatTone, string> = {
  cold: "var(--as-muted-fg)",
  warm: "var(--as-warning)",
  hot: "var(--ca-heat-hot)",
  none: "var(--as-border)",
};

export function heatTone(score: number | null | undefined): HeatTone {
  if (score == null || Number.isNaN(Number(score))) return "none";
  const value = Number(score);
  if (value >= 7) return "hot";
  if (value >= 4) return "warm";
  return "cold";
}
