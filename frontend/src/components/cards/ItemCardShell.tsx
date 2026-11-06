import type { ReactNode } from "react";

export type CardDensity = "compact" | "full";

export function ItemCardShell({
  testId,
  density = "full",
  state,
  seen,
  onOpen,
  actions,
  children,
  className = "",
  actionsClassName = "",
}: {
  testId: string;
  density?: CardDensity;
  state?: "closed";
  seen?: boolean;
  onOpen?: () => void;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  actionsClassName?: string;
}) {
  const closed = state === "closed";
  const interactive = Boolean(onOpen);
  return (
    <article
      data-testid={testId}
      data-density={density}
      data-seen={seen ? "true" : undefined}
      data-state={state}
      onClick={onOpen}
      className={[
        "ca-item-card flex flex-wrap items-start gap-4 rounded-[var(--as-radius-lg)] border p-4 transition-colors",
        closed
          ? "border-[var(--as-border)] bg-[var(--as-muted)]"
          : "border-[var(--as-border)] bg-[var(--as-surface)]",
        interactive && !closed
          ? "cursor-pointer hover:border-[var(--as-accent)] hover:bg-[var(--as-surface-raised)] focus-within:ring-2 focus-within:ring-[var(--as-focus-ring)]"
          : "",
        className,
      ].join(" ")}
    >
      {children}
      {actions ? (
        <div
          className={`ca-item-actions flex shrink-0 flex-col items-stretch gap-1.5 ${actionsClassName}`}
          onClick={(event) => event.stopPropagation()}
        >
          {actions}
        </div>
      ) : null}
    </article>
  );
}
