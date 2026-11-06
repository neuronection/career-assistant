import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";
import { ChevronRight, Tag } from "lucide-react";
import { CheckIndicator } from "@neuronection/assistant-ui";
import { Badge, EmptyState, SearchInput } from "@/components/ui";

/** Normalized row view-model — the list is shape-agnostic; the caller
 * maps its rows onto this (plan 150). */
export interface TaxonomyRowView {
  id: string;
  key: string;
  label: string;
  category: string;
  /** Alias or description hint line under the label (also searched). */
  hint?: string;
  status: "active" | "proposed" | "deprecated";
}

export interface TaxonomyGroup {
  key: string;
  labelKey: string;
  icon: LucideIcon;
}

export interface TaxonomyFilterOption {
  value: string;
  labelKey: string;
}

type TaxonomyStatus = TaxonomyRowView["status"];

const STATUS_VARIANT: Record<TaxonomyStatus, "success" | "secondary" | "warning"> = {
  active: "success",
  proposed: "secondary",
  deprecated: "warning",
};

/** The one filter predicate: the list renders it and the page derives the
 * `matching` selection scope from it (plan 200) — never two copies. */
export function filterTaxonomyRows<T>(
  rows: T[],
  toView: (row: T) => TaxonomyRowView,
  filter: string,
  query: string
): T[] {
  const searched = query.trim().toLowerCase();
  return rows.filter((row) => {
    const view = toView(row);
    if (filter !== "all" && view.status !== filter) return false;
    if (!searched) return true;
    return [view.label, view.key, view.category, view.hint ?? ""]
      .join(" ")
      .toLowerCase()
      .includes(searched);
  });
}

interface TaxonomyListProps<T> {
  /** The full, unfiltered dataset — emptiness of THIS decides empty vs no-match. */
  rows: T[];
  toView: (row: T) => TaxonomyRowView;
  /** Ordered collapsible groups; empty groups (after search/filter) are hidden. */
  groups: TaxonomyGroup[];
  groupOf: (row: T) => string;
  /** Single-select status chips, first entry is the default ("all"). */
  filters: TaxonomyFilterOption[];
  filter: string;
  onFilterChange: (value: string) => void;
  /** Controlled search — the page owns it so it can reveal hidden rows. */
  query: string;
  onQueryChange: (value: string) => void;
  selectMode?: boolean;
  selected?: ReadonlySet<string>;
  onToggleSelect?: (id: string, options?: { shift?: boolean }) => void;
  /** Group-header tri-state; `selected` is the target state for the group. */
  onSetGroupSelected?: (ids: string[], selected: boolean) => void;
  onOpen: (row: T) => void;
  /** Per-row icon (usually the row's category icon). */
  iconOf?: (row: T) => LucideIcon;
  searchPlaceholder: string;
  toolbarSlot?: ReactNode;
  /** The active selection bar — rendered directly under the toolbar row so
   * the entry control and the bar stay in one visual block (plan 200). */
  selectionBar?: ReactNode;
  emptyIcon: LucideIcon;
  emptyTitle: string;
  testidPrefix?: string;
}

/** Shared taxonomy listing (plan 150, selection contract plan 200):
 * controlled search + status filter chips + collapsible groups of
 * iconified rows. In select mode the row body toggles, a trailing button
 * opens the details drawer, and group headers carry a tri-state checkbox.
 * The checkbox is a SIBLING of the row button — a button must not nest a
 * button. */
export function TaxonomyList<T>({
  rows,
  toView,
  groups,
  groupOf,
  filters,
  filter,
  onFilterChange,
  query,
  onQueryChange,
  selectMode = false,
  selected,
  onToggleSelect,
  onSetGroupSelected,
  onOpen,
  iconOf,
  searchPlaceholder,
  toolbarSlot,
  selectionBar,
  emptyIcon,
  emptyTitle,
  testidPrefix = "taxonomy",
}: TaxonomyListProps<T>) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const visible = filterTaxonomyRows(rows, toView, filter, query);

  const counts = new Map<string, number>();
  for (const row of rows) {
    const status = toView(row).status;
    counts.set(status, (counts.get(status) ?? 0) + 1);
  }
  const totalCount = rows.length;

  const grouped = groups
    .map((group) => ({
      group,
      rows: visible.filter((row) => groupOf(row) === group.key),
    }))
    .filter((entry) => entry.rows.length > 0);

  return (
    <div className="ca-tax-list space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1 basis-64" data-testid={`${testidPrefix}-search`}>
          <SearchInput
            value={query}
            onChange={onQueryChange}
            placeholder={searchPlaceholder}
            ariaLabel={searchPlaceholder}
            clearLabel={t("common.clear")}
          />
        </div>
        <div className="flex flex-wrap gap-1.5" data-testid={`${testidPrefix}-filters`}>
          {filters.map((option) => {
            const count =
              option.value === "all" ? totalCount : (counts.get(option.value) ?? 0);
            const active = filter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => onFilterChange(option.value)}
                className={`cursor-pointer rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                  active
                    ? "border-[var(--as-accent)] bg-[var(--as-accent)] text-white"
                    : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                }`}
                data-testid={`${testidPrefix}-filter-${option.value}`}
              >
                {t(option.labelKey, { defaultValue: option.value })}
                <span className="ml-1 tabular-nums opacity-80">{count}</span>
              </button>
            );
          })}
        </div>
        {toolbarSlot}
      </div>

      {selectionBar}

      {rows.length === 0 ? (
        <EmptyState icon={emptyIcon} compact title={emptyTitle} />
      ) : visible.length === 0 ? (
        <EmptyState
          icon={emptyIcon}
          compact
          title={t("taxonomy.noMatch")}
          description={t("taxonomy.noMatchBody")}
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)]">
          {grouped.map(({ group, rows: groupRows }, index) => {
            const GroupIcon = group.icon;
            const isCollapsed = collapsed.has(group.key);
            const groupIds = groupRows.map((row) => toView(row).id);
            let groupSelected = 0;
            for (const id of groupIds) {
              if (selected?.has(id)) groupSelected += 1;
            }
            const groupChecked = groupIds.length > 0 && groupSelected === groupIds.length;
            return (
              <div
                key={group.key}
                className={index > 0 ? "border-t border-[var(--as-border)]" : undefined}
                data-testid={`${testidPrefix}-group-${group.key}`}
              >
                <div className="flex items-center gap-2 bg-[var(--as-muted)] px-3 py-2">
                  {selectMode && onSetGroupSelected && (
                    <span
                      className="flex shrink-0 items-center"
                      data-testid={`${testidPrefix}-group-select-${group.key}`}
                    >
                      <CheckIndicator
                        checked={groupChecked}
                        mixed={groupSelected > 0 && !groupChecked}
                        label={t("taxonomy.bulk.selectGroup", {
                          count: groupIds.length,
                          group: t(group.labelKey, { defaultValue: group.key }),
                        })}
                        onToggle={() => onSetGroupSelected(groupIds, !groupChecked)}
                      />
                    </span>
                  )}
                  <button
                    type="button"
                    aria-expanded={!isCollapsed}
                    onClick={() =>
                      setCollapsed((prev) => {
                        const next = new Set(prev);
                        if (next.has(group.key)) next.delete(group.key);
                        else next.add(group.key);
                        return next;
                      })
                    }
                    className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left"
                    data-testid={`${testidPrefix}-group-toggle-${group.key}`}
                  >
                    <GroupIcon
                      className="h-3.5 w-3.5 shrink-0 text-[var(--as-accent)]"
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate text-xs font-semibold text-[var(--as-fg)]">
                      {t(group.labelKey, { defaultValue: group.key })}
                    </span>
                    <span
                      className="rounded-full bg-[var(--as-surface)] px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-[var(--as-muted-fg)]"
                      data-testid={`${testidPrefix}-group-count-${group.key}`}
                    >
                      {groupRows.length}
                    </span>
                    <ChevronRight
                      className={`h-3.5 w-3.5 text-[var(--as-muted-fg)] transition-transform ${
                        isCollapsed ? "" : "rotate-90"
                      }`}
                      aria-hidden
                    />
                  </button>
                </div>
                {!isCollapsed && (
                  <ul className="divide-y divide-[var(--as-border)]">
                    {groupRows.map((row) => {
                      const view = toView(row);
                      const RowIcon = iconOf?.(row) ?? Tag;
                      return (
                        <li key={view.id} className="flex items-center">
                          {selectMode && (
                            <div className="flex shrink-0 items-center pl-3">
                              <CheckIndicator
                                checked={selected?.has(view.id) ?? false}
                                label={t("taxonomy.bulk.selectOne", { label: view.label })}
                                onToggle={() => onToggleSelect?.(view.id)}
                              />
                            </div>
                          )}
                          <button
                            type="button"
                            onClick={(event) =>
                              selectMode
                                ? onToggleSelect?.(view.id, { shift: event.shiftKey })
                                : onOpen(row)
                            }
                            className={`flex min-w-0 flex-1 cursor-pointer items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-[var(--as-muted)] focus-visible:bg-[var(--as-muted)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
                              selectMode ? "pl-2" : ""
                            }`}
                            data-testid={`${testidPrefix}-row-${view.key}`}
                          >
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--as-muted)]">
                              <RowIcon
                                className="h-4 w-4 text-[var(--as-accent)]"
                                aria-hidden
                              />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="flex min-w-0 items-baseline gap-2">
                                <span className="truncate text-sm font-medium text-[var(--as-fg)]">
                                  {view.label}
                                </span>
                                {view.hint ? (
                                  <span className="ca-tax-hint min-w-0 truncate text-xs text-[var(--as-muted-fg)]">
                                    {view.hint}
                                  </span>
                                ) : null}
                              </span>
                              <span className="ca-tax-key block truncate font-mono text-[11px] text-[var(--as-muted-fg)]">
                                {view.key}
                              </span>
                            </span>
                            <Badge
                              variant={STATUS_VARIANT[view.status]}
                              className="shrink-0"
                            >
                              {t(`taxonomy.${view.status}`)}
                            </Badge>
                            {!selectMode && (
                              <ChevronRight
                                className="h-4 w-4 shrink-0 text-[var(--as-muted-fg)]"
                                aria-hidden
                              />
                            )}
                          </button>
                          {selectMode && (
                            <button
                              type="button"
                              onClick={() => onOpen(row)}
                              aria-label={t("taxonomy.openDetails", { label: view.label })}
                              className="mr-2 flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
                              data-testid={`${testidPrefix}-row-open-${view.key}`}
                            >
                              <ChevronRight className="h-4 w-4" aria-hidden />
                            </button>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
