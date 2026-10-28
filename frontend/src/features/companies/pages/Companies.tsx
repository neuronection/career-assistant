import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Building2, Globe, MapPin, Search } from "lucide-react";
import { fetchCompanies } from "@/api/companies";
import { Badge, EmptyState } from "@/components/ui";
import { CardMeta } from "@/components/cards/CardMeta";
import { CardSpec } from "@/components/cards/CardSpec";
import { ChipRow } from "@/components/cards/ChipRow";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import type { SpecItem } from "@/components/cards/specOrder";
import { OrgAvatar } from "@/components/company/OrgAvatar";
import type { Company } from "@/types/wire";

type StatusFilter = "all" | "new";

const FILTERS: StatusFilter[] = ["all", "new"];

function employeesRange(company: Company): string | null {
  const parts = [company.employees_min, company.employees_max].filter(
    (v) => v != null
  );
  return parts.length > 0 ? parts.join("–") : null;
}

export function Companies() {
  const { t } = useTranslation();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const handle = setTimeout(() => {
      const params = query.trim() ? { q: query.trim() } : {};
      void fetchCompanies(params)
        .then(setCompanies)
        .catch(() => setError(t("companies.loadError")))
        .finally(() => setLoaded(true));
    }, 250);
    return () => clearTimeout(handle);
  }, [query, t]);

  const visible =
    filter === "new" ? companies.filter((c) => c.status === "proposed") : companies;
  const searching = query.trim().length > 0;

  return (
    <div className="ca-card-page max-w-4xl mx-auto space-y-6" data-testid="companies">
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
          title={searching || filter === "new" ? t("companies.noMatchTitle") : t("companies.noneYetTitle")}
          description={
            searching || filter === "new"
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
