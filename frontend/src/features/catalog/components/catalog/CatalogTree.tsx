import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Library, X } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";
import { apiDetail } from "@/api/client";
import * as providersApi from "@/api/providers";
import { useCatalogStore } from "@/stores/catalogStore";
import { useAuthStore } from "@/stores/authStore";
import { JobCard } from "@/features/catalog/components/JobCard";
import { CatalogFilterRail } from "@/features/catalog/components/catalog/CatalogFilterRail";
import { RecentSearches } from "@/features/postings/components/RecentSearches";
import { useContainerBand, type ContainerBand } from "@/hooks/useContainerBand";
import { useSearchHistory } from "@/hooks/useSearchHistory";
import {
  CATALOG_SORT_OPTIONS,
  catalogActiveChips,
  catalogApiParams,
  catalogParams,
  parseCatalogParams,
  removeCatalogChip,
} from "@/features/catalog/catalogParams";
import type { SearchRecord } from "@/types/wire";
import type { JobFamilyNode } from "@/types";

export function CatalogTree({ band: bandOverride }: { band?: ContainerBand } = {}) {
  const { t } = useTranslation();
  const { families, jobs, total, facets, loading, error, loadFamilies, loadJobs } =
    useCatalogStore();
  const { ref: bandRef, band } = useContainerBand(bandOverride);
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

  const isAdmin = useAuthStore((state) => state.user?.is_admin ?? false);
  const [installing, setInstalling] = useState(false);
  const [installError, setInstallError] = useState("");
  const catalogEmpty =
    !loading && total === 0 && jobs.length === 0 && families.length === 0;

  const installOfficialCatalog = async () => {
    setInstalling(true);
    setInstallError("");
    try {
      const providers = await providersApi.listAdminProviders();
      const tile = providers.find(
        (provider) =>
          provider.trust_tier === "official" &&
          provider.subpath.endsWith("job-catalog")
      );
      if (!tile) throw new Error(t("catalog.empty.missingTile"));
      await providersApi.installOfficialProvider(tile.id);
      await Promise.all([loadFamilies(), loadJobs(catalogApiParams(filters))]);
    } catch (error) {
      setInstallError(apiDetail(error));
    } finally {
      setInstalling(false);
    }
  };

  if (catalogEmpty) {
    return (
      <div className="ca-stats-page" data-testid="catalog-empty-page" ref={bandRef}>
        <EmptyState
          icon={Library}
          title={t("catalog.empty.title")}
          description={
            isAdmin ? t("catalog.empty.adminBody") : t("catalog.empty.memberBody")
          }
          action={
            isAdmin ? (
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  onClick={() => void installOfficialCatalog()}
                  loading={installing}
                  data-testid="catalog-load-official"
                >
                  {t("catalog.empty.loadOfficial")}
                </Button>
                <Button variant="secondary" asChild>
                  <Link to="/settings/tools?section=sources">
                    {t("catalog.empty.openProviders")}
                  </Link>
                </Button>
              </div>
            ) : null
          }
          data-testid="catalog-empty"
        />
        {installError ? (
          <p
            className="mt-3 text-center text-sm text-[var(--as-danger)]"
            data-testid="catalog-install-error"
          >
            {installError}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="ca-stats-page" data-testid="catalog-tree" data-band={band} ref={bandRef}>
      <div className="ca-stats-cols ca-catalog-cols">
        <CatalogFilterRail
          filters={filters}
          facets={facets}
          families={families}
          total={error ? undefined : total}
          band={band}
          onChange={patch}
          onClear={clearAll}
        />

        <div className="ca-card-page min-w-0 space-y-3">
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

          {error ? (
            <p
              className="text-sm text-[var(--as-danger)]"
              role="alert"
              data-testid="catalog-error"
            >
              {t("catalog.filters.loadFailed")}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--as-muted-fg)]">
            {!error ? (
              <span data-testid="catalog-result-count">
                {t("catalog.filters.resultCount", { count: total })}
              </span>
            ) : null}
            <label className="ml-auto flex items-center gap-1">
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

          {chips.length > 0 ? (
            <div
              className="flex flex-wrap items-center gap-1 text-xs text-[var(--as-muted-fg)]"
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
                  className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5"
                >
                  {chip.labelKey
                    ? t(chip.labelKey, { defaultValue: chip.label, value: chip.label })
                    : chip.label}
                  <X aria-hidden className="h-3 w-3" />
                </button>
              ))}
            </div>
          ) : null}

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
          panelTestId="catalog-recent-panel"
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
