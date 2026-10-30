/**
 * Shared filter-rail bits (plan 141; promoted app-level for Companies in
 * plan 154): the collapsible section and the tri-state include/exclude
 * chip row with optional facet counts. The feed's FilterRail (plan 136),
 * the Explore rail and the Companies page all consume them — one filter
 * language across the product.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";

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

/**
 * The tri-state cycle for one chip: off → include → exclude → off,
 * right-click excludes directly. Include and exclude are mutually
 * exclusive per value.
 */
export function triStateToggle(
  include: string[],
  exclude: string[],
  value: string,
  mode: "include" | "exclude",
): { include: string[]; exclude: string[] } {
  if (mode === "include") {
    return {
      include: include.includes(value) ? include.filter((v) => v !== value) : [...include, value],
      exclude: exclude.filter((v) => v !== value),
    };
  }
  return {
    include: include.filter((v) => v !== value),
    exclude: exclude.includes(value) ? exclude.filter((v) => v !== value) : [...exclude, value],
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
  onToggle: (value: string, mode: "include" | "exclude") => void;
  showCounts?: boolean;
  allowExclude?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map(({ value, label, count, testId }) => {
        const isIncluded = include.includes(value);
        const isExcluded = exclude.includes(value);
        const dimmed = showCounts && count === 0 && !isIncluded && !isExcluded;
        return (
          <button
            key={value}
            type="button"
            data-testid={testId}
            onClick={() =>
              onToggle(value, isIncluded || isExcluded ? (isIncluded ? "exclude" : "include") : "include")
            }
            onContextMenu={
              allowExclude
                ? (e) => {
                    e.preventDefault();
                    onToggle(value, "exclude");
                  }
                : undefined
            }
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
              isIncluded
                ? "border-primary-300 bg-primary-50 text-primary-700 font-medium"
                : isExcluded
                  ? "border-rose-300 bg-rose-50 text-rose-700"
                  : dimmed
                    ? "border-slate-100 bg-white text-slate-300"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            }`}
            title={
              allowExclude
                ? isIncluded
                  ? t("filters.clickToExclude")
                  : isExcluded
                    ? t("filters.clickToIncludeOnly")
                    : t("filters.clickToInclude")
                : t("filters.clickToToggle")
            }
          >
            {isExcluded ? "− " : ""}
            {label}
            {showCounts && count !== undefined ? (
              <span className="ml-1 opacity-70">· {count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
