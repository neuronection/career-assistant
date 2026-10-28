import type { SpecItem } from "./specOrder";
import { orderSpecs } from "./specOrder";

export function CardSpec({
  items,
  testId,
  className = "",
}: {
  items: SpecItem[];
  testId?: string;
  className?: string;
}) {
  const ordered = orderSpecs(items.filter((item) => item.value));
  if (ordered.length === 0) return null;
  return (
    <div
      className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 ${className}`}
      data-testid={testId}
    >
      {ordered.map((item, index) => (
        <span
          key={item.key}
          className="inline-flex items-baseline gap-1 whitespace-nowrap"
          data-spec={item.key}
          data-testid={item.testId}
          title={item.hint}
        >
          <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
            {item.label}
          </span>
          {item.scale ? (
            <span
              className="inline-flex items-center gap-0.5"
              aria-hidden
              data-testid={`spec-scale-${item.key}`}
              data-filled={item.scale.filled}
            >
              {Array.from({ length: item.scale.total }, (_, dot) => (
                <span
                  key={dot}
                  className={`h-1 w-1 rounded-full ${
                    dot < item.scale!.filled
                      ? "bg-[var(--as-accent)]"
                      : "bg-[var(--as-border)]"
                  }`}
                />
              ))}
            </span>
          ) : null}
          <span
            className={
              item.tone === "warning"
                ? "text-[12px] text-[var(--as-warning)]"
                : "text-[12px] text-[var(--as-fg)]"
            }
          >
            {item.icon ? <item.icon aria-hidden className="mr-0.5 inline h-3 w-3 align-[-2px] text-[var(--as-muted-fg)]" /> : null}
            {item.value}
          </span>
          {index < ordered.length - 1 && (
            <span aria-hidden className="ml-0.5 text-[10px] text-[var(--as-border)]">
              ·
            </span>
          )}
        </span>
      ))}
    </div>
  );
}
