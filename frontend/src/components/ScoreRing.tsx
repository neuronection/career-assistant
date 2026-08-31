export function ScoreRing({ score, size = 56 }: { score: number | null; size?: number }) {
  const value = score ?? 0;
  const angle = Math.round(value * 36);
  const color = value >= 7 ? "#059669" : value >= 4 ? "#d97706" : "#e11d48";
  return (
    <div
      data-testid="score-ring"
      role="img"
      aria-label={`Score ${value.toFixed(1)} of 10`}
      className="rounded-full flex items-center justify-center font-semibold"
      style={{
        width: size,
        height: size,
        background: `conic-gradient(${color} ${angle}%, #e2e8f0 ${angle}% 100%)`,
        color,
      }}
    >
      <span
        className="rounded-full bg-white flex items-center justify-center"
        style={{ width: size - 10, height: size - 10, fontSize: size * 0.3 }}
      >
        {value.toFixed(1)}
      </span>
    </div>
  );
}
