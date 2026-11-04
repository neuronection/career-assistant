import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useLocation,
  useNavigate,
  useNavigationType,
  useSearchParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowUpDown, Building2, Globe, MapPin } from "lucide-react";
import { fetchCompanies } from "@/api/companies";
import { rememberListSearch, isListReturn } from "@/lib/listReturn";
import {
  peekCompaniesList,
  rememberCompaniesList,
  type CompaniesListSnapshot,
} from "@/features/companies/companiesListCache";
import { useProfilesStore } from "@/stores/profilesStore";
import { Badge, EmptyState, SearchableDropdown } from "@/components/ui";
import { CardMeta } from "@/components/cards/CardMeta";
import { CardSpec } from "@/components/cards/CardSpec";
import { ChipRow } from "@/components/cards/ChipRow";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import {
  Section,
  TriStateChips,
  triStateToggle,
  type FacetChip,
} from "@/components/filters/filterBits";
import { FilterRail, FilterRailSearch } from "@/components/filters/FilterRail";
import type { SpecItem } from "@/components/cards/specOrder";
import { OrgAvatar } from "@/components/company/OrgAvatar";
import { CompaniesStatsRail } from "@/components/stats/StatsRail";
import type { Company, CompanyFacets } from "@/types/wire";
import {
  MIN_OPEN_OPTIONS,
  SORT_OPTIONS,
  countActive,
  parseFilters,
  toParams,
  toSearchParams,
  type CompanyFilters,
} from "@/features/companies/companiesParams";
import type { TriStateMode } from "@/components/filters/filterBits";

const STATUS_FILTERS: CompanyFilters["status"][] = ["all", "new"];

function employeesRange(company: Company): string | null {
  const parts = [company.employees_min, company.employees_max].filter(
    (v) => v != null
  );
  return parts.length > 0 ? parts.join("–") : null;
}

/** Companies directory (plan 154): the postings-derived filter language —
 * tri-state chips with facet counts computed over the active positions
 * the companies are hiring with — on top of the busiest-first list.
 * One filter language with Explore via the shared filter bits. */
export function Companies() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);
  const profileEpoch = useProfilesStore((state) => state.epoch);
  const plainKey = useMemo(() => toSearchParams(filters).toString(), [filters]);
  const snapshotKey = `${profileEpoch}|${plainKey}`;
  const navigationType = useNavigationType();
  const locationState = useLocation().state;
  const restorable = navigationType === "POP" || isListReturn(locationState);
  const restoredRef = useRef<CompaniesListSnapshot | null | undefined>(
    undefined
  );
  if (restoredRef.current === undefined) {
    restoredRef.current = restorable ? peekCompaniesList(snapshotKey) : null;
  }
  const restored = restoredRef.current;
  const [companies, setCompanies] = useState<Company[]>(
    () => restored?.companies ?? []
  );
  const [facets, setFacets] = useState<CompanyFacets | null>(
    () => restored?.facets ?? null
  );
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(() => restored !== null);

  const patch = useCallback(
    (update: Partial<CompanyFilters>) => {
      setSearchParams(toSearchParams({ ...filters, ...update }), { replace: true });
    },
    [filters, setSearchParams]
  );

  const toggleAxis = useCallback(
    (
      includeKey: keyof CompanyFilters,
      excludeKey: keyof CompanyFilters,
      value: string,
      mode: TriStateMode
    ) => {
      const next = triStateToggle(
        filters[includeKey] as string[],
        filters[excludeKey] as string[],
        value,
        mode
      );
      patch({ [includeKey]: next.include, [excludeKey]: next.exclude } as Partial<CompanyFilters>);
    },
    [filters, patch]
  );

  const fetchWith = useCallback(
    (current: CompanyFilters) => {
      void fetchCompanies({ ...toParams(current), facets: true })
        .then((result) => {
          const items = result.items ?? [];
          setCompanies(items);
          setFacets(result.facets ?? null);
          setError("");
          rememberCompaniesList(
            `${profileEpoch}|${toSearchParams(current).toString()}`,
            { companies: items, facets: result.facets ?? null }
          );
        })
        .catch(() => setError(t("companies.loadError")))
        .finally(() => setLoaded(true));
    },
    [t, profileEpoch]
  );

  const restoredForRef = useRef<CompanyFilters | null>(null);
  useEffect(() => {
    if (restoredRef.current && restoredForRef.current === null) {
      restoredForRef.current = filters;
      return;
    }
    if (restoredForRef.current === filters) return;
    const handle = setTimeout(() => {
      fetchWith(filters);
    }, 250);
    return () => clearTimeout(handle);
  }, [filters, fetchWith]);

  useEffect(() => {
    rememberListSearch("/companies", plainKey);
  }, [plainKey]);

  useEffect(() => {
    const canonical = toSearchParams(parseFilters(searchParams)).toString();
    if (canonical !== searchParams.toString()) {
      setSearchParams(new URLSearchParams(canonical), { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visible =
    filters.status === "new"
      ? companies.filter((c) => c.status === "proposed")
      : companies;
  const searching = filters.q.trim().length > 0;
  const filtersActive = countActive(filters);

  const facetChips = useCallback(
    (facet: keyof CompanyFacets): FacetChip[] =>
      Object.entries(facets?.[facet] ?? {}).map(([value, count]) => ({
        value,
        label: t(`companies.facet.${facet}.${value}`, { defaultValue: value }),
        count,
        testId: `company-${facet}-${value}`,
      })),
    [facets, t]
  );

  const clearAll = () => setSearchParams(new URLSearchParams(), { replace: true });

  return (
    <div className="ca-stats-page space-y-4" data-testid="companies">
      <p className="text-sm text-[var(--as-muted-fg)]">{t("companies.subtitle")}</p>

      <div className="ca-stats-cols">
        <FilterRail
          title={t("companies.railTitle")}
          activeCount={filtersActive}
          onClear={clearAll}
          countTestId="company-filter-count"
          clearTestId="company-filters-clear"
          asideTestId="company-filters"
          testId="company-filter-rail"
        >
          <FilterRailSearch
            value={filters.q}
            onChange={(q) => patch({ q })}
            placeholder={t("companies.searchPlaceholder")}
            testId="company-search"
          />

            <div data-testid="company-filter-statuses">
              <p className="pt-1 text-xs font-medium text-[var(--as-muted-fg)]">
                {t("companies.statusTitle")}
              </p>
              <div className="flex flex-wrap gap-1 pt-1">
                {STATUS_FILTERS.map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={filters.status === mode}
                    onClick={() => patch({ status: mode })}
                    className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                      filters.status === mode
                        ? "border-[var(--as-accent)] bg-[var(--as-muted)] font-medium text-[var(--as-accent)]"
                        : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-fg)] hover:bg-[var(--as-muted)]"
                    }`}
                    data-testid={`company-filter-${mode}`}
                  >
                    {t(`companies.filter.${mode}`)}
                  </button>
                ))}
              </div>
            </div>
          <Section
            title={t("companies.facetTitle.work_mode")}
            active={filters.workMode.length + filters.workModeExclude.length > 0}
          >
            <TriStateChips
              values={facetChips("work_mode")}
              include={filters.workMode}
              exclude={filters.workModeExclude}
              onToggle={(value, mode) => toggleAxis("workMode", "workModeExclude", value, mode)}
              showCounts
            />
          </Section>
          <Section
            title={t("companies.facetTitle.seniority")}
            active={filters.seniority.length + filters.seniorityExclude.length > 0}
          >
            <TriStateChips
              values={facetChips("seniority")}
              include={filters.seniority}
              exclude={filters.seniorityExclude}
              onToggle={(value, mode) => toggleAxis("seniority", "seniorityExclude", value, mode)}
              showCounts
            />
          </Section>
          <Section
            title={t("companies.facetTitle.employment")}
            active={filters.employment.length + filters.employmentExclude.length > 0}
          >
            <TriStateChips
              values={facetChips("employment")}
              include={filters.employment}
              exclude={filters.employmentExclude}
              onToggle={(value, mode) => toggleAxis("employment", "employmentExclude", value, mode)}
              showCounts
            />
          </Section>
          <Section
            title={t("companies.facetTitle.industries")}
            active={filters.industries.length + filters.industriesExclude.length > 0}
          >
            <TriStateChips
              values={facetChips("industries")}
              include={filters.industries}
              exclude={filters.industriesExclude}
              onToggle={(value, mode) =>
                toggleAxis("industries", "industriesExclude", value, mode)
              }
              showCounts
            />
          </Section>
          <div className="space-y-2 pt-1">
            <label className="block text-xs">
              <span className="mb-1 block font-medium text-[var(--as-muted-fg)]">
                {t("companies.facetTitle.locations")}
              </span>
              <input
                value={filters.location}
                onChange={(e) => patch({ location: e.target.value })}
                placeholder={t("companies.locationPlaceholder")}
                aria-label={t("companies.facetTitle.locations")}
                className="w-full rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-[var(--as-fg)]"
                data-testid="company-filter-location"
              />
            </label>
            <label className="block text-xs">
              <span className="mb-1 block font-medium text-[var(--as-muted-fg)]">
                {t("companies.facetTitle.minOpen")}
              </span>
              <select
                value={String(filters.minOpen)}
                onChange={(e) => patch({ minOpen: Number(e.target.value) })}
                aria-label={t("companies.facetTitle.minOpen")}
                className="w-full rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-[var(--as-fg)]"
                data-testid="company-filter-min-open"
              >
                <option value={0}>{t("companies.minOpenAny")}</option>
                {MIN_OPEN_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {t("companies.minOpenN", { count: option })}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </FilterRail>

        <div className="flex-1 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500" data-testid="company-count">
          {loaded ? t("companies.count", { count: visible.length }) : ""}
        </p>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <ArrowUpDown aria-hidden className="h-3.5 w-3.5" />
          <span>{t("companies.sortBy")}</span>
          <div className="w-48">
            <SearchableDropdown
              options={SORT_OPTIONS.map((option) => ({
                value: option.value,
                label: t(option.labelKey),
              }))}
              value={filters.sort}
              onChange={(value) => patch({ sort: value })}
              label={t("companies.sortBy")}
              hideLabel
            />
          </div>
        </div>
      </div>
      {error && <p className="text-sm text-[var(--as-danger)]">{error}</p>}

      {!loaded ? (
        <div className="ca-card-grid" data-testid="company-skeleton">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="cv-shimmer h-36 rounded-[var(--as-radius-lg)]" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          icon={Building2}
          compact
          title={
            searching || filtersActive > 0 || filters.status === "new"
              ? t("companies.noMatchTitle")
              : t("companies.noneYetTitle")
          }
          description={
            searching || filtersActive > 0 || filters.status === "new"
              ? t("companies.noMatchBody")
              : t("companies.noneYetBody")
          }
        />
      ) : (
        <div className="ca-card-grid">
          {visible.map((company) => (
            <CompanyCard key={company.key} company={company} />
          ))}
        </div>
      )}
        </div>

        <CompaniesStatsRail
          onNewCompanies={() => patch({ status: "new" })}
          onIndustry={(key) =>
            toggleAxis(
              "industries",
              "industriesExclude",
              key,
              filters.industries.includes(key) ? "clear" : "include"
            )
          }
          onCompany={(key) => navigate(`/companies/${key}`)}
        />
      </div>
    </div>
  );
}

function companySpecs(company: Company, t: (key: string, opts?: Record<string, unknown>) => string): SpecItem[] {
  const specs: SpecItem[] = [];
  if (company.company_type) {
    specs.push({
      key: "type",
      label: t("card.type"),
      value: t(`companies.type.${company.company_type}`, {
        defaultValue: String(company.company_type),
      }),
    });
  }
  const size = employeesRange(company);
  if (size) specs.push({ key: "size", label: t("card.size"), value: size });
  if (company.founded_year) {
    specs.push({ key: "founded", label: t("card.founded"), value: String(company.founded_year) });
  }
  return specs;
}

function CompanyCard({ company }: { company: Company }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const hq = [company.hq_city, company.hq_country].filter(Boolean).join(", ");
  return (
    <ItemCardShell
      testId={`company-card-${company.key}`}
      onOpen={() => navigate(`/companies/${company.key}`)}
    >
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <OrgAvatar name={company.name} size={28} />
          <button
            type="button"
            className="min-w-0 truncate text-left font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
            data-testid="company-details"
          >
            <span data-testid="company-title">{company.name}</span>
          </button>
          {company.status === "proposed" ? (
            <Badge
              variant="outline"
              className="ml-auto shrink-0"
              data-testid={`company-proposed-${company.key}`}
            >
              {t("companies.proposed")}
            </Badge>
          ) : null}
        </div>

        {hq || company.domain ? (
          <CardMeta
            className="mt-1"
            items={[
              ...(hq
                ? [
                    {
                      key: "hq",
                      icon: MapPin,
                      text: hq,
                    },
                  ]
                : []),
              ...(company.domain
                ? [{ key: "domain", icon: Globe, text: company.domain }]
                : []),
            ]}
          />
        ) : null}

        <CardSpec className="mt-1.5 border-t border-[var(--as-border)] pt-1.5" items={companySpecs(company, t)} />

        {(company.industry_tags ?? []).length > 0 ? (
          <ChipRow
            className="mt-1.5"
            testId="company-industries"
            max={3}
            moreLabel={(count) => t("card.more", { count })}
            moreAriaLabel={(count) => t("card.moreAria", { count })}
            showLessLabel={t("card.showLess")}
            items={(company.industry_tags ?? []).map((tag) => ({
              key: tag,
              label: tag,
            }))}
          />
        ) : null}

        <p className="mt-2 text-xs font-medium text-[var(--as-accent)]">
          {t("companies.openPostings", { count: company.open_postings })}
        </p>
      </div>
    </ItemCardShell>
  );
}
