import { HEAT_COLOR, heatTone } from "./heatTone";

export function SkillTag({
  label,
  score,
  unmapped = false,
  title,
  testId,
}: {
  label: string;
  score?: number | null;
  unmapped?: boolean;
  title?: string;
  testId?: string;
}) {
  const heat = heatTone(score);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-1.5 py-px text-xs ${
        unmapped
          ? "border-dashed border-[var(--as-border)] text-[var(--as-muted-fg)]"
          : "border-[var(--as-border)] text-[var(--as-fg)]"
      }`}
      title={title}
      data-testid={testId}
      data-heat={heat}
    >
      <span className="font-medium">{label}</span>
      {score != null ? (
        <>
          <span
            aria-hidden
            className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ background: HEAT_COLOR[heat] }}
            data-testid="skill-heat"
          />
          <span className="text-[10px] tabular-nums text-[var(--as-muted-fg)]">
            {Number(score).toFixed(0)}
          </span>
        </>
      ) : null}
    </span>
  );
}
