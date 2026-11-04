import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { useCatalogStore } from "@/stores/catalogStore";
import { JobCard } from "@/features/catalog/components/JobCard";
import { CatalogFilterRail } from "@/features/catalog/components/catalog/CatalogFilterRail";
import { RecentSearches } from "@/features/postings/components/RecentSearches";
import { useSearchHistory } from "@/hooks/useSearchHistory";
import {
  CATALOG_SORT_OPTIONS,
  catalogActiveChips,
  catalogApiParams,
  catalogParams,
  countActiveCatalogFilters,
  parseCatalogParams,
  removeCatalogChip,
} from "@/features/catalog/catalogParams";
import type { SearchRecord } from "@/types/wire";
import type { JobFamilyNode } from "@/types";

export function CatalogTree() {
  const { t } = useTranslation();
  const { families, jobs, total, facets, loadFamilies, loadJobs } = useCatalogStore();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseCatalogParams(searchParams), [searchParams]);
  const paramsKey = catalogParams(filters).toString();
  const [historyKey, setHistoryKey] = useState(0);
  const recordSearch = useSearchHistory("catalog");
  const navigate = useNavigate();

  useEffect(() => {
    void loadFamilies();
  }, [loadFamilies]);

  useEffect(() => {
    void loadJobs(catalogApiParams(filters));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadJobs, paramsKey]);

  useEffect(() => {
    const canonical = catalogParams(parseCatalogParams(searchParams)).toString();
    if (canonical !== searchParams.toString()) {
      setSearchParams(new URLSearchParams(canonical), { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = useCallback(
    (update: Partial<typeof filters>) => {
      setSearchParams(catalogParams({ ...filters, ...update }), { replace: true });
    },
    [filters, setSearchParams]
  );

  useEffect(() => {
    if (filters.q.trim().length < 2 && !filters.family) return;
    recordSearch(filters.q, { family_key: filters.family || null }, total);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.q, filters.family, total]);

  const applySearch = (record: SearchRecord) => {
    const familyKey = (record.filters.family_key as string) || "";
    patch({ q: record.query, family: familyKey });
    setHistoryKey((key) => key + 1);
  };

  const selectFamily = (key: string | null) => {
    patch({ family: key ?? "" });
  };

  const clearAll = () => {
    setSearchParams(new URLSearchParams(), { replace: true });
  };

  const activeNode = useMemo(
    () => findNode(families, filters.family || null),
    [families, filters.family]
  );
  const chips = catalogActiveChips(filters);
  const activeCount = countActiveCatalogFilters(filters);

  return (
    <div className="ca-stats-page" data-testid="catalog-tree">
      <div className="ca-stats-cols">
        <aside className="ca-stats-rail" data-testid="catalog-filter-aside">
          <CatalogFilterRail
            filters={filters}
            facets={facets}
            families={families}
            onChange={patch}
          />
        </aside>

        <div className="ca-card-page min-w-0 space-y-3">
          <input
            placeholder={t("catalog.searchPlaceholder")}
            value={filters.q}
            onChange={(event) => patch({ q: event.target.value })}
            aria-label={t("catalog.searchPlaceholder")}
            data-testid="catalog-search"
            className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] outline-none transition-colors focus:border-[var(--as-primary)]"
          />

          {activeNode && activeNode.children.length > 0 && (
            <div className="flex flex-wrap gap-2" data-testid="catalog-subfamilies">
              {activeNode.children.map((child) => (
                <button
                  key={child.key}
                  type="button"
                  onClick={() => selectFamily(child.key)}
                  data-testid={`subfamily-${child.key}`}
                  className="flex cursor-pointer items-center gap-1.5 rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-1.5 text-xs font-medium text-[var(--as-fg)] transition-colors hover:bg-[var(--as-muted)]"
                >
                  {child.label}
                  <span className="tabular-nums text-[var(--as-muted-fg)]">{child.job_count}</span>
                </button>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--as-muted-fg)]">
            <span data-testid="catalog-result-count">
              {t("catalog.filters.resultCount", { count: total })}
            </span>
            {activeCount > 0 ? (
              <span data-testid="catalog-filter-count">
                {t("catalog.filters.activeCount", { count: activeCount })}
              </span>
            ) : null}
            {chips.length > 0 ? (
              <button
                type="button"
                onClick={clearAll}
                className="text-[var(--as-primary)] hover:underline"
                data-testid="catalog-clear-all"
              >
                {t("catalog.filters.clearAll")}
              </button>
            ) : null}
            <div
              className="ml-auto flex flex-wrap items-center gap-1"
              data-testid="catalog-active-chips"
            >
              {chips.map((chip) => (
                <button
                  key={`${chip.axis}-${chip.kind}-${chip.value}`}
                  type="button"
                  onClick={() => patch(removeCatalogChip(filters, chip))}
                  data-axis={chip.axis}
                  data-kind={chip.kind}
                  data-testid={`catalog-chip-${chip.axis}-${chip.value}`}
                  className="inline-flex items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5"
                >
                  {chip.labelKey
                    ? t(chip.labelKey, { defaultValue: chip.label, value: chip.label })
                    : chip.label}
                  <X aria-hidden className="h-3 w-3" />
                </button>
              ))}
            </div>
            <label className="flex items-center gap-1">
              {t("catalog.filters.sort")}
              <select
                value={filters.sort}
                onChange={(event) => patch({ sort: event.target.value })}
                className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-1 py-1"
                data-testid="catalog-sort"
              >
                {CATALOG_SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.labelKey)}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="ca-card-grid" data-testid="catalog-grid">
            {jobs.map((job) => (
              <JobCard
                key={job.id}
                job={job}
                onSelect={(selected) => navigate(`/jobs/${selected.code}`)}
              />
            ))}
          </div>
        </div>

        <RecentSearches
          scope="catalog"
          onApply={applySearch}
          refreshKey={historyKey}
          max={4}
          hideEmptyFiltersOnly
          rail
        />
      </div>
    </div>
  );
}

function findNode(families: JobFamilyNode[], key: string | null): JobFamilyNode | null {
  if (!key) return null;
  for (const family of families) {
    if (family.key === key) return family;
    const hit = findNode(family.children, key);
    if (hit) return hit;
  }
  return null;
}
