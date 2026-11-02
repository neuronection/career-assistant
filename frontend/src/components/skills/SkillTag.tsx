import { HEAT_COLOR, heatTone } from "./heatTone";

export function SkillTag({
  label,
  score,
  unmapped = false,
  title,
  testId,
  onOpen,
  onMenu,
}: {
  label: string;
  score?: number | null;
  unmapped?: boolean;
  title?: string;
  testId?: string;
  /** Opt-in peek affordance (plan 149): present → the tag renders as a
   * button that opens the skill peek; absent → an inert span. */
  onOpen?: (trigger: HTMLElement | null) => void;
  /** Opt-in entity-menu affordance (plan 188): click (unmodified) and
   * right-click open the menu; when present it takes precedence over
   * onOpen for plain clicks — the peek stays reachable through the menu. */
  onMenu?: (event: React.MouseEvent<HTMLElement>) => void;
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
  if (!onOpen && !onMenu) {
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
        if (onMenu) {
          if (event.metaKey || event.ctrlKey || event.shiftKey) return;
          event.preventDefault();
          onMenu(event);
          return;
        }
        onOpen?.(event.currentTarget);
      }}
      onContextMenu={
        onMenu
          ? (event) => {
              event.preventDefault();
              event.stopPropagation();
              onMenu(event);
            }
          : undefined
      }
      className={`${classes} cursor-pointer text-left hover:border-[var(--as-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--as-focus-ring)]`}
      title={title}
      data-testid={testId}
      data-heat={heat}
      aria-haspopup={onMenu ? "menu" : "dialog"}
    >
      {content}
    </button>
  );
}
