/**
 * Shared filter-rail bits (plan 141; promoted app-level for Companies in
 * plan 154): the collapsible section and the tri-state include/exclude
 * chip row with optional facet counts. The feed's FilterRail (plan 136),
 * the Explore rail and the Companies page all consume them — one filter
 * language across the product.
 */

import { useState } from "react";
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
  const effectiveOpen = open || active;
  return (
    <div className="border border-slate-100 rounded-lg">
      <button
        type="button"
        className="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={effectiveOpen}
      >
        <span className={active ? "font-medium text-slate-800" : ""}>{title}</span>
        <span className="flex items-center gap-2">
          {count ? (
            <span className="text-xs text-primary-600" data-testid="section-count">
              {count}
            </span>
          ) : null}
          {active ? (
            <span className="w-1.5 h-1.5 rounded-full bg-primary-500" aria-hidden />
          ) : null}
          <ChevronDown
            className={`w-3.5 h-3.5 text-slate-400 transition-transform ${effectiveOpen ? "" : "-rotate-90"}`}
          />
        </span>
      </button>
      {effectiveOpen ? <div className="px-3 pb-3 space-y-2">{children}</div> : null}
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
                ? "border-primary-300 bg-primary-50 text-primary-700"
                : isExcluded
                  ? "border-rose-300 bg-rose-50 text-rose-700"
                  : dimmed
                    ? "border-slate-100 bg-white text-slate-300"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            <button
              type="button"
              data-testid={testId}
              aria-pressed={selected}
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
