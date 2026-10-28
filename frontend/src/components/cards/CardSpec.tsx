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
          <span
            className={
              item.tone === "warning"
                ? "text-[12px] text-[var(--as-warning)]"
                : "text-[12px] text-[var(--as-fg)]"
            }
          >
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
