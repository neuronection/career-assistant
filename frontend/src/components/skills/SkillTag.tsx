import { HEAT_COLOR, heatTone } from "./heatTone";

export function SkillTag({
  label,
  score,
  unmapped = false,
  title,
  testId,
  onOpen,
}: {
  label: string;
  score?: number | null;
  unmapped?: boolean;
  title?: string;
  testId?: string;
  /** Opt-in peek affordance (plan 149): present → the tag renders as a
   * button that opens the skill peek; absent → an inert span. */
  onOpen?: (trigger: HTMLElement | null) => void;
}) {
  const heat = heatTone(score);
  const classes = `inline-flex items-center gap-1.5 rounded-md border px-1.5 py-px text-xs ${
    unmapped
      ? "border-dashed border-[var(--as-border)] text-[var(--as-muted-fg)]"
      : "border-[var(--as-border)] text-[var(--as-fg)]"
  }`;
  const content = (
    <>
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
    </>
  );
  if (!onOpen) {
    return (
      <span className={classes} title={title} data-testid={testId} data-heat={heat}>
        {content}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={(event) => {
        // posting cards are single-click containers — a chip click never
        // navigates to the posting
        event.stopPropagation();
        onOpen(event.currentTarget);
      }}
      className={`${classes} cursor-pointer text-left hover:border-[var(--as-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--as-focus-ring)]`}
      title={title}
      data-testid={testId}
      data-heat={heat}
      aria-haspopup="dialog"
    >
      {content}
    </button>
  );
}
