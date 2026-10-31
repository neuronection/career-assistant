import type { StatsSparkPoint } from "@/api/stats";
import { ACCENT } from "./chartKit";

/** The 14-day volume sparkline (§A): an inline SVG polyline — no
 * recharts, jsdom-friendly, token accent only. */
export function Sparkline({
  points,
  width = 120,
  height = 28,
  testId = "stats-sparkline",
}: {
  points: StatsSparkPoint[];
  width?: number;
  height?: number;
  testId?: string;
}) {
  if (points.length < 2) return null;
  const counts = points.map((point) => point.count);
  const max = Math.max(1, ...counts);
  const step = width / (points.length - 1);
  const line = counts
    .map((count, index) => {
      const x = (index * step).toFixed(1);
      const y = (height - 2 - (count / max) * (height - 4)).toFixed(1);
      return `${x},${y}`;
    })
    .join(" ");
  const area = `0,${height} ${line} ${width},${height}`;
  return (
    <svg
      data-testid={testId}
      viewBox={`0 0 ${width} ${height}`}
      className="block h-7 w-full max-w-52"
      preserveAspectRatio="none"
      role="presentation"
      aria-hidden
    >
      <polygon points={area} fill={ACCENT} opacity="0.12" />
      <polyline
        points={line}
        fill="none"
        stroke={ACCENT}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
