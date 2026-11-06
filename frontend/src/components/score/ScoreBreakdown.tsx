import { scoreColor } from "./scoreTone";

export interface BreakdownDimension {
  key: string;
  label: string;
  score: number;
  weight?: number;
  detail?: string;
  neutral?: boolean;
}

export function ScoreBreakdown({
  dimensions,
  tone = "banded",
  defaultWeight,
  alwaysShowWeight = false,
  showDetails = false,
  detailsLayout = "inline",
  max = 10,
  testId,
  detailsTestId,
  labelWidth = "7rem",
  className = "",
}: {
  dimensions: BreakdownDimension[];
  tone?: "banded" | "neutral";
  defaultWeight?: number;
  alwaysShowWeight?: boolean;
  showDetails?: boolean;
  detailsLayout?: "inline" | "lines";
  max?: number;
  testId?: string;
  detailsTestId?: string;
  labelWidth?: string;
  className?: string;
}) {
  if (dimensions.length === 0) return null;
  const detailed = showDetails
    ? dimensions.filter((dimension) => dimension.detail)
    : [];
  return (
    <div data-capture="fit-breakdown" className={`space-y-1.5 ${className}`} data-testid={testId}>
      {dimensions.map((dimension) => {
        const width = Math.max(
          0,
          Math.min(100, (Number(dimension.score) / max) * 100)
        );
        const color =
          tone === "neutral"
            ? dimension.neutral
              ? "var(--as-border)"
              : "var(--as-accent)"
            : scoreColor(dimension.score);
        const showWeight =
          alwaysShowWeight || defaultWeight == null || dimension.weight !== defaultWeight;
        return (
          <div key={dimension.key} className="flex items-center gap-2 text-xs">
            <span
              className="shrink-0 text-[var(--as-muted-fg)]"
              style={{ width: labelWidth }}
            >
              {dimension.label}
            </span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--as-muted)]">
              <span
                className="block h-1.5 rounded-full"
                style={{ width: `${width}%`, background: color }}
              />
            </span>
            <span className="w-8 shrink-0 text-right tabular-nums text-[var(--as-fg)]">
              {Number(dimension.score).toFixed(1)}
            </span>
            {showWeight ? (
              <span className="w-10 shrink-0 text-right tabular-nums text-[var(--as-muted-fg)]">
                ×{dimension.weight ?? 1}
              </span>
            ) : null}
          </div>
        );
      })}
      {detailed.length > 0 && detailsLayout === "lines" ? (
        <div className="space-y-0.5 pt-1" data-testid={detailsTestId}>
          {detailed.map((dimension) => (
            <p key={dimension.key} className="text-[11px] text-[var(--as-muted-fg)]">
              <span className="font-medium text-[var(--as-fg)]">
                {dimension.label}:{" "}
              </span>
              {dimension.detail}
            </p>
          ))}
        </div>
      ) : null}
      {detailed.length > 0 && detailsLayout === "inline" ? (
        <p
          className="pt-0.5 text-[11px] text-[var(--as-muted-fg)]"
          data-testid={detailsTestId}
        >
          {detailed
            .map((dimension) => `${dimension.label}: ${dimension.detail}`)
            .join(" · ")}
        </p>
      ) : null}
    </div>
  );
}
