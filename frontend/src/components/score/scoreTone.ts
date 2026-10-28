export type ScoreTone = "success" | "warning" | "danger" | "muted";

export const SCORE_COLOR: Record<ScoreTone, string> = {
  success: "var(--as-success)",
  warning: "var(--as-warning)",
  danger: "var(--as-danger)",
  muted: "var(--as-muted-fg)",
};

export function scoreTone(score: number | null | undefined): ScoreTone {
  if (score == null || Number.isNaN(Number(score))) return "muted";
  const value = Number(score);
  if (value >= 7) return "success";
  if (value >= 4) return "warning";
  return "danger";
}

export function scoreColor(score: number | null | undefined): string {
  return SCORE_COLOR[scoreTone(score)];
}
