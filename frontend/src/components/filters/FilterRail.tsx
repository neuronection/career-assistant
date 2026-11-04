/**
 * The one filter-rail template for every list page (postings, catalog,
 * companies, autopilot, rankings): one transparent shell, one header
 * (title, active count, Clear all), and the always-visible search field
 * for pages whose result set has a text query.
 *
 * The shell deliberately paints no card of its own — the bordered sections
 * are the only boxes in the rail, so the panel never reads as a card inside
 * a card. Scrolling is owned by `.ca-stats-rail` in `index.css`: above
 * 64rem of page width the rail sticks below the app header and scrolls on
 * its own; below it the rail stacks in normal page flow. Pages must not add
 * their own `sticky`/`max-h`/`overflow-y` classes — nested scroll containers
 * are what made the rails behave differently from page to page.
 */

import { useTranslation } from "react-i18next";

import { SearchInput } from "@/components/ui";

export interface FilterRailProps {
  title: string;
  activeCount?: number;
  onClear?: () => void;
  countTestId?: string;
  clearTestId?: string;
  testId?: string;
  asideTestId?: string;
  asideClassName?: string;
  /** Panel switcher state for rails that collapse below the breakpoint. */
  asideOpen?: boolean;
  children: React.ReactNode;
}

export function FilterRail({
  title,
  activeCount = 0,
  onClear,
  countTestId,
  clearTestId,
  testId,
  asideTestId,
  asideClassName,
  asideOpen,
  children,
}: FilterRailProps) {
  const { t } = useTranslation();
  const active = activeCount > 0;

  return (
    <aside
      className={`ca-stats-rail min-w-0 ${asideClassName ?? ""}`.trim()}
      data-testid={asideTestId}
      data-open={asideOpen === undefined ? undefined : asideOpen ? "true" : "false"}
      aria-label={title}
    >
      <div
        className="flex flex-col gap-3 pr-2"
        data-testid={testId}
      >
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
          <h2 className="text-sm font-semibold text-[var(--as-fg)]">
            {title}
            {active ? (
              <span
                className="ml-2 text-xs font-normal text-[var(--as-accent)]"
                data-testid={countTestId}
                aria-live="polite"
              >
                {t("filters.activeCount", { count: activeCount })}
              </span>
            ) : null}
          </h2>
          {active && onClear ? (
            <button
              type="button"
              className="shrink-0 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)]"
              onClick={onClear}
              data-testid={clearTestId}
            >
              {t("filters.clearAll")}
            </button>
          ) : null}
        </div>
        {children}
      </div>
    </aside>
  );
}

export function FilterRailSearch({
  value,
  onChange,
  placeholder,
  testId,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  testId?: string;
  label?: string;
}) {
  return (
    <div>
      {label ? (
        <span className="mb-1 block text-xs font-medium text-[var(--as-muted-fg)]">
          {label}
        </span>
      ) : null}
      <SearchInput
        ref={(node) => {
          if (node && testId) node.setAttribute("data-testid", testId);
        }}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        ariaLabel={label ?? placeholder}
      />
    </div>
  );
}
