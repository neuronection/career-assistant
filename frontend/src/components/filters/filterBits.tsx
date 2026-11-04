/**
 * Shared filter-rail bits (plan 141; promoted app-level for Companies in
 * plan 154): the collapsible section and the tri-state include/exclude
 * chip row with optional facet counts. Every filter rail pairs them with
 * `FilterRail`/`FilterRailSearch` — one filter language, one chrome.
 * The chip contract lives in `docs/dev/ui-conventions.md` §2i.
 */

import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, X } from "lucide-react";

export function Section({
  title,
  active,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  active: boolean;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(active || defaultOpen);
  const bodyId = useId();
  const effectiveOpen = open || active;
  return (
    <div className="rounded-[var(--as-radius)] border border-[var(--as-border)]">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 rounded-[var(--as-radius)] px-3 py-2 text-sm text-[var(--as-fg)] transition-colors hover:bg-[var(--as-muted)]"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={effectiveOpen}
        aria-controls={bodyId}
      >
        <span className={active ? "font-semibold" : ""}>{title}</span>
        <span className="flex items-center gap-2">
          {count ? (
            <span
              className="text-xs tabular-nums text-[var(--as-accent)]"
              data-testid="section-count"
            >
              {count}
            </span>
          ) : null}
          {active ? (
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--as-accent)]" aria-hidden />
          ) : null}
          <ChevronDown
            className={`h-3.5 w-3.5 text-[var(--as-muted-fg)] transition-transform ${
              effectiveOpen ? "" : "-rotate-90"
            }`}
          />
        </span>
      </button>
      {effectiveOpen ? (
        <div id={bodyId} className="space-y-2 px-3 pb-3">
          {children}
        </div>
      ) : null}
    </div>
  );
}

export interface FacetChip {
  value: string;
  label: string;
  count?: number;
  testId?: string;
}

export type TriStateMode = "include" | "exclude" | "clear";

/**
 * The tri-state cycle for one chip: off → include → exclude → off,
 * right-click excludes directly. Include and exclude are mutually
 * exclusive per value (every mode drops the value from the other list).
 */
export function triStateToggle(
  include: string[],
  exclude: string[],
  value: string,
  mode: TriStateMode,
): { include: string[]; exclude: string[] } {
  if (mode === "clear") {
    return {
      include: include.filter((v) => v !== value),
      exclude: exclude.filter((v) => v !== value),
    };
  }
  if (mode === "exclude") {
    return {
      include: include.filter((v) => v !== value),
      exclude: [...exclude.filter((v) => v !== value), value],
    };
  }
  return {
    include: [...include.filter((v) => v !== value), value],
    exclude: exclude.filter((v) => v !== value),
  };
}

export function TriStateChips({
  values,
  include,
  exclude,
  onToggle,
  showCounts = false,
  allowExclude = true,
}: {
  values: FacetChip[];
  include: string[];
  exclude: string[];
  onToggle: (value: string, mode: TriStateMode) => void;
  showCounts?: boolean;
  allowExclude?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map(({ value, label, count, testId }) => {
        const isIncluded = include.includes(value);
        const isExcluded = exclude.includes(value);
        const selected = isIncluded || isExcluded;
        const dimmed = showCounts && count === 0 && !selected;
        const nextMode: TriStateMode = !selected
          ? "include"
          : isIncluded && allowExclude
            ? "exclude"
            : "clear";
        const title = !selected
          ? allowExclude
            ? t("filters.clickToInclude")
            : t("filters.clickToToggle")
          : isIncluded && allowExclude
            ? t("filters.clickToExclude")
            : t("filters.clickToClear");
        return (
          <span
            key={value}
            data-state={isIncluded ? "include" : isExcluded ? "exclude" : undefined}
            className={`inline-flex items-stretch overflow-hidden rounded-full border text-xs transition-colors ${
              isIncluded
                ? "border-[var(--as-accent)] bg-[var(--as-muted)] text-[var(--as-accent)]"
                : isExcluded
                  ? "border-[var(--as-danger)] bg-[color-mix(in_srgb,var(--as-danger)_12%,transparent)] text-[var(--as-danger)]"
                  : dimmed
                    ? "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-muted-fg)] opacity-50"
                    : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-fg)] hover:bg-[var(--as-muted)]"
            }`}
          >
            <button
              type="button"
              data-testid={testId}
              aria-pressed={selected}
              aria-disabled={dimmed || undefined}
              disabled={dimmed}
              onClick={() => onToggle(value, nextMode)}
              onContextMenu={
                allowExclude
                  ? (e) => {
                      e.preventDefault();
                      onToggle(value, "exclude");
                    }
                  : undefined
              }
              className={`py-1 pl-2.5 ${selected ? "pr-1" : "pr-2.5"} ${
                isIncluded ? "font-medium" : ""
              }`}
              title={title}
            >
              {isExcluded ? "− " : ""}
              {label}
              {showCounts && count !== undefined ? (
                <span className="ml-1 opacity-70">· {count}</span>
              ) : null}
            </button>
            {selected ? (
              <button
                type="button"
                onClick={() => onToggle(value, "clear")}
                data-testid={testId ? `${testId}-clear` : undefined}
                aria-label={t("filters.removeValue", { value: label })}
                title={t("filters.clickToClear")}
                className="py-1 pl-0.5 pr-1.5 opacity-70 transition-opacity hover:opacity-100"
              >
                <X aria-hidden className="h-3 w-3" />
              </button>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}
