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
 *
 * A page that passes a `band` below `wide` (measured on the page container,
 * never the viewport — the chat dock narrows the column without moving the
 * viewport) gets the compact form: one toolbar row (search + a Filters
 * button carrying the active count) and the sections inside a `PanelModal`
 * sheet, with Clear all / Show N jobs in its footer. That keeps the first
 * result card at the top of a narrow page instead of ~700px down.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SlidersHorizontal } from "lucide-react";

import { PanelModal, SearchInput } from "@/components/ui";
import type { ContainerBand } from "@/hooks/useContainerBand";

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
  /** Page-container width band; omit to keep the inline rail at every width. */
  band?: ContainerBand;
  /** Search field for pages whose result set has a text query. */
  search?: React.ReactNode;
  /** Result total for the sheet footer's "Show N jobs" action. */
  resultCount?: number;
  /** Compact toolbar label; defaults to `title` (pages with long rail titles
   * pass the short "Filters"). */
  triggerLabel?: string;
  triggerTestId?: string;
  sheetTestId?: string;
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
  band,
  search,
  resultCount,
  triggerLabel,
  triggerTestId,
  sheetTestId,
  children,
}: FilterRailProps) {
  const { t } = useTranslation();
  const active = activeCount > 0;
  const compact = (band ?? "wide") !== "wide";
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    if (!compact) setSheetOpen(false);
  }, [compact]);

  const shellClass = `ca-stats-rail min-w-0 ${asideClassName ?? ""}`.trim();
  const sheetId = sheetTestId ?? "filters-sheet";

  if (!compact) {
    return (
      <aside
        className={shellClass}
        data-testid={asideTestId}
        data-band={band ?? "wide"}
        data-open={asideOpen === undefined ? undefined : asideOpen ? "true" : "false"}
        aria-label={title}
      >
        <div className="flex flex-col gap-3 pr-2" data-testid={testId}>
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
          {search}
          {children}
        </div>
      </aside>
    );
  }

  return (
    <aside
      className={shellClass}
      data-testid={asideTestId}
      data-band={band}
      aria-label={title}
    >
      <div className="flex flex-wrap items-center gap-2 pr-2" data-testid={testId}>
        {search ? <div className="min-w-0 flex-1">{search}</div> : null}
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={sheetOpen}
          className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-3 text-sm font-medium text-[var(--as-fg)] transition-colors hover:bg-[var(--as-muted)]"
          data-testid={triggerTestId ?? "filters-open"}
        >
          <SlidersHorizontal className="h-4 w-4 text-[var(--as-muted-fg)]" aria-hidden />
          {triggerLabel ?? title}
          {active ? (
            <span
              className="rounded-full bg-[var(--as-accent)] px-1.5 text-[11px] font-semibold leading-4 text-[var(--as-primary-fg)]"
              data-testid={countTestId}
              aria-live="polite"
            >
              {activeCount}
            </span>
          ) : null}
        </button>
      </div>
      <PanelModal
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title={
          <span className="inline-flex flex-wrap items-baseline gap-2">
            {title}
            {active ? (
              <span className="text-xs font-normal text-[var(--as-accent)]">
                {t("filters.activeCount", { count: activeCount })}
              </span>
            ) : null}
          </span>
        }
        closeLabel={t("filters.close")}
        size="md"
        data-testid={sheetId}
        bodyClassName="min-h-0 overflow-y-auto p-5 sm:p-6"
        footer={
          <div className="flex items-center gap-2">
            {active && onClear ? (
              <button
                type="button"
                className="min-h-[44px] rounded-lg border border-[var(--as-border)] px-3 text-sm text-[var(--as-fg)]"
                onClick={onClear}
                data-testid={clearTestId}
              >
                {t("filters.clearAll")}
              </button>
            ) : null}
            <button
              type="button"
              className="ml-auto min-h-[44px] rounded-lg bg-[var(--as-accent)] px-4 text-sm font-medium text-[var(--as-primary-fg)]"
              onClick={() => setSheetOpen(false)}
              data-testid={`${sheetId}-done`}
            >
              {resultCount === undefined
                ? t("filters.done")
                : t("filters.showResults", { count: resultCount })}
            </button>
          </div>
        }
      >
        <div className="flex flex-col gap-3">{children}</div>
      </PanelModal>
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
