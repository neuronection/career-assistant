import { useTranslation } from "react-i18next";
import { scoreColor, scoreTone } from "./scoreTone";

export function ScoreBubble({
  score,
  size = 56,
  max = 10,
  testId = "score-ring",
  className = "",
}: {
  score: number | null | undefined;
  size?: number;
  max?: number;
  testId?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const value = score == null ? 0 : Number(score);
  const color = scoreColor(score);
  const stroke = size >= 60 ? 5 : 4;
  const radius = (size - stroke) / 2 - 1;
  const circumference = 2 * Math.PI * radius;
  const fraction = Math.max(0, Math.min(1, value / max));
  return (
    <div
      className={`relative inline-flex shrink-0 items-center justify-center ${className}`}
      style={{ width: size, height: size }}
      data-testid={testId}
      data-score={score ?? undefined}
      data-tone={scoreTone(score)}
      role="img"
      aria-label={
        score == null
          ? t("card.noScore")
          : t("shared.scoreAria", { score: value.toFixed(1) })
      }
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden
        className="-rotate-90"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--as-border)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${circumference * fraction} ${circumference}`}
        />
      </svg>
      <span
        className="absolute inset-0 flex items-center justify-center font-semibold tabular-nums"
        style={{ color, fontSize: Math.round(size * 0.3) }}
      >
        {score == null ? "–" : value.toFixed(1)}
      </span>
    </div>
  );
}
