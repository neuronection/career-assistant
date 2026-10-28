import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Building2, Search } from "lucide-react";
import { fetchCompanies } from "@/api/companies";
import { Badge, EmptyState } from "@/components/ui";
import { ChipRow } from "@/components/cards/ChipRow";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import { OrgAvatar } from "@/components/company/OrgAvatar";
import type { Company } from "@/types/wire";

export function Companies() {
  const { t } = useTranslation();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [query, setQuery] = useState("");
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

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="companies">
      <p className="text-slate-500">{t("companies.subtitle")}</p>

      <label className="relative block">
        <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("companies.searchPlaceholder")}
          aria-label={t("companies.searchPlaceholder")}
          className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm focus:border-primary-400 focus:outline-none"
          data-testid="company-search"
        />
      </label>
      {error && <p className="text-sm text-rose-600">{error}</p>}

      {loaded && companies.length === 0 ? (
        <EmptyState
          icon={Building2}
          compact
          title={t("companies.noneYetTitle")}
          description={t("companies.noneYetBody")}
        />
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
          {companies.map((company) => (
            <CompanyCard key={company.key} company={company} />
          ))}
        </div>
      )}
    </div>
  );
}

function CompanyCard({ company }: { company: Company }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const min = company.employees_min;
  const max = company.employees_max;
  const employees =
    min != null || max != null ? [min, max].filter((v) => v != null).join("–") : null;
  return (
    <ItemCardShell
      testId={`company-card-${company.key}`}
      onOpen={() => navigate(`/companies/${company.key}`)}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <OrgAvatar name={company.name} size={24} />
            <Link
              to={`/companies/${company.key}`}
              onClick={(event) => event.stopPropagation()}
              className="truncate font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
            >
              {company.name}
            </Link>
          </div>
          {company.company_type ? (
            <Badge variant="secondary">
              {t(`companies.type.${company.company_type}`)}
            </Badge>
          ) : null}
        </div>
        <p className="mt-1 text-sm text-[var(--as-muted-fg)]">
          {[company.hq_city, company.hq_country].filter(Boolean).join(", ") ||
            t("companies.locationUnknown")}
        </p>
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
        <div className="mt-2 flex items-center gap-3 text-xs text-[var(--as-muted-fg)]">
          <span className="font-medium text-[var(--as-accent)]">
            {t("companies.openPostings", { count: company.open_postings })}
          </span>
          {employees ? <span>{t("companies.employees", { range: employees })}</span> : null}
        </div>
      </div>
    </ItemCardShell>
  );
}
