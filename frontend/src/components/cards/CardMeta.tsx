import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

export interface MetaItem {
  key: string;
  icon?: LucideIcon;
  text: string;
  title?: string;
  href?: string;
  testId?: string;
}

export function CardMeta({
  items,
  testId,
  className = "",
}: {
  items: MetaItem[];
  testId?: string;
  className?: string;
}) {
  if (items.length === 0) return null;
  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[var(--as-muted-fg)] ${className}`}
      data-testid={testId}
    >
      {items.map((item) => {
        const Icon = item.icon;
        const body = (
          <>
            {Icon ? <Icon aria-hidden className="h-3 w-3 shrink-0" /> : null}
            <span className="truncate">{item.text}</span>
          </>
        );
        if (!item.href) {
          return (
            <span
              key={item.key}
              className="inline-flex min-w-0 items-center gap-1"
              title={item.title}
              data-testid={item.testId}
            >
              {body}
            </span>
          );
        }
        return (
          <Link
            key={item.key}
            to={item.href}
            className="inline-flex min-w-0 items-center gap-1 hover:text-[var(--as-accent)]"
            title={item.title}
            data-testid={item.testId}
            onClick={(event) => event.stopPropagation()}
          >
            {body}
          </Link>
        );
      })}
    </div>
  );
}
