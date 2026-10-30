import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Building2, Globe, MapPin, Search } from "lucide-react";
import { fetchCompanies, type CompanyQuery } from "@/api/companies";
import { Badge, EmptyState } from "@/components/ui";
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
import type { SpecItem } from "@/components/cards/specOrder";
import { OrgAvatar } from "@/components/company/OrgAvatar";
import type { Company, CompanyFacets } from "@/types/wire";

type StatusFilter = "all" | "new";

const FILTERS: StatusFilter[] = ["all", "new"];

const MIN_OPEN_OPTIONS = [1, 3, 5, 10];

const EMPTY_AXIS: { include: string[]; exclude: string[] } = {
  include: [],
  exclude: [],
};

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
  const [companies, setCompanies] = useState<Company[]>([]);
  const [facets, setFacets] = useState<CompanyFacets | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [workMode, setWorkMode] = useState(EMPTY_AXIS);
  const [seniority, setSeniority] = useState(EMPTY_AXIS);
  const [employment, setEmployment] = useState(EMPTY_AXIS);
  const [industries, setIndustries] = useState<string[]>([]);
  const [minOpen, setMinOpen] = useState(0);
  const [location, setLocation] = useState("");

  const axisParams = useMemo(
    () => ({
      work_mode: workMode.include,
      work_mode_exclude: workMode.exclude,
      seniority: seniority.include,
      seniority_exclude: seniority.exclude,
      employment: employment.include,
      employment_exclude: employment.exclude,
      industry: industries,
      min_open: minOpen || undefined,
      location: location || undefined,
    }),
    [workMode, seniority, employment, industries, minOpen, location]
  );

  const fetchWith = useCallback(
    (params: CompanyQuery) => {
      void fetchCompanies({ ...params, facets: true })
        .then((result) => {
          setCompanies(result.items ?? []);
          setFacets(result.facets ?? null);
          setError("");
        })
        .catch(() => setError(t("companies.loadError")))
        .finally(() => setLoaded(true));
    },
    [t]
  );

  useEffect(() => {
    const handle = setTimeout(() => {
      fetchWith({ q: query, ...axisParams });
    }, 250);
    return () => clearTimeout(handle);
  }, [query, axisParams, fetchWith]);

  const visible =
    filter === "new" ? companies.filter((c) => c.status === "proposed") : companies;
  const searching = query.trim().length > 0;
  const filtersActive =
    workMode.include.length +
    workMode.exclude.length +
    seniority.include.length +
    seniority.exclude.length +
    employment.include.length +
    employment.exclude.length +
    industries.length +
    (minOpen ? 1 : 0) +
    (location ? 1 : 0);

  const facetChips = useCallback(
    (facet: keyof CompanyFacets): FacetChip[] =>
      Object.entries(facets?.[facet] ?? {}).map(([value, count]) => ({
        value,
        label: t(`companies.facet.${facet}.${value}`, { defaultValue: value }),
        count,
      })),
    [facets, t]
  );

  const clearAll = () => {
    setWorkMode(EMPTY_AXIS);
    setSeniority(EMPTY_AXIS);
    setEmployment(EMPTY_AXIS);
    setIndustries([]);
    setMinOpen(0);
    setLocation("");
  };

  return (
    <div className="ca-card-page max-w-6xl mx-auto space-y-6" data-testid="companies">
      <p className="text-sm text-[var(--as-muted-fg)]">{t("companies.subtitle")}</p>

      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-0 flex-1 basis-56">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-[var(--as-muted-fg)]" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("companies.searchPlaceholder")}
            aria-label={t("companies.searchPlaceholder")}
            className="w-full rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] py-2 pl-9 pr-3 text-sm text-[var(--as-fg)] outline-none focus:border-[var(--as-accent)]"
            data-testid="company-search"
          />
        </label>
        <div className="flex gap-1.5" data-testid="company-filter-statuses">
          {FILTERS.map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={filter === mode}
              onClick={() => setFilter(mode)}
              className={`cursor-pointer rounded-full border px-2.5 py-0.5 text-xs ${
                filter === mode
                  ? "border-[var(--as-accent)] bg-[var(--as-accent)] text-white"
                  : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
              }`}
              data-testid={`company-filter-${mode}`}
            >
              {t(`companies.filter.${mode}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2" data-testid="company-filter-rail">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("companies.railTitle")}
          </p>
          {filtersActive > 0 ? (
            <button
              type="button"
              onClick={clearAll}
              className="text-xs text-[var(--as-accent)] underline decoration-transparent transition-colors hover:decoration-current"
              data-testid="company-filters-clear"
            >
              {t("companies.clearFilters", { count: filtersActive })}
            </button>
          ) : null}
        </div>
        <div className="grid gap-2 lg:grid-cols-2">
          <Section
            title={t("companies.facetTitle.work_mode")}
            active={workMode.include.length + workMode.exclude.length > 0}
          >
            <TriStateChips
              values={facetChips("work_mode")}
              include={workMode.include}
              exclude={workMode.exclude}
              onToggle={(value, mode) =>
                setWorkMode((prev) => triStateToggle(prev.include, prev.exclude, value, mode))
              }
              showCounts
            />
          </Section>
          <Section
            title={t("companies.facetTitle.seniority")}
            active={seniority.include.length + seniority.exclude.length > 0}
          >
            <TriStateChips
              values={facetChips("seniority")}
              include={seniority.include}
              exclude={seniority.exclude}
              onToggle={(value, mode) =>
                setSeniority((prev) => triStateToggle(prev.include, prev.exclude, value, mode))
              }
              showCounts
            />
          </Section>
          <Section
            title={t("companies.facetTitle.employment")}
            active={employment.include.length + employment.exclude.length > 0}
          >
            <TriStateChips
              values={facetChips("employment")}
              include={employment.include}
              exclude={employment.exclude}
              onToggle={(value, mode) =>
                setEmployment((prev) => triStateToggle(prev.include, prev.exclude, value, mode))
              }
              showCounts
            />
          </Section>
          <Section
            title={t("companies.facetTitle.industries")}
            active={industries.length > 0}
          >
            <TriStateChips
              values={facetChips("industries")}
              include={industries}
              exclude={[]}
              onToggle={(value) =>
                setIndustries((prev) =>
                  prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]
                )
              }
              showCounts
            />
          </Section>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-[var(--as-muted-fg)]">
            <span className="mb-1 block font-semibold uppercase tracking-wide">
              {t("companies.facetTitle.locations")}
            </span>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder={t("companies.locationPlaceholder")}
              aria-label={t("companies.facetTitle.locations")}
              className="w-44 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2.5 py-1.5 text-sm text-[var(--as-fg)]"
              data-testid="company-filter-location"
            />
          </label>
          <label className="text-xs text-[var(--as-muted-fg)]">
            <span className="mb-1 block font-semibold uppercase tracking-wide">
              {t("companies.facetTitle.minOpen")}
            </span>
            <select
              value={String(minOpen)}
              onChange={(e) => setMinOpen(Number(e.target.value))}
              aria-label={t("companies.facetTitle.minOpen")}
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2.5 py-1.5 text-sm text-[var(--as-fg)]"
              data-testid="company-filter-min-open"
            >
              {MIN_OPEN_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {t("companies.minOpenN", { count: option })}
                </option>
              ))}
            </select>
          </label>
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
            searching || filtersActive > 0 || filter === "new"
              ? t("companies.noMatchTitle")
              : t("companies.noneYetTitle")
          }
          description={
            searching || filtersActive > 0 || filter === "new"
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
