import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Building2, Search } from "lucide-react";
import { fetchCompanies } from "@/api/companies";
import { EmptyState } from "@/components/ui";
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
  const min = company.employees_min;
  const max = company.employees_max;
  const employees =
    min != null || max != null ? [min, max].filter((v) => v != null).join("–") : null;
  return (
    <Link
      to={`/companies/${company.key}`}
      className="block bg-white border border-slate-200 rounded-xl p-4 hover:border-primary-400"
      data-testid={`company-card-${company.key}`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium">{company.name}</p>
        {company.company_type && (
          <span className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-full whitespace-nowrap">
            {t(`companies.type.${company.company_type}`)}
          </span>
        )}
      </div>
      <p className="text-sm text-slate-500">
        {[company.hq_city, company.hq_country].filter(Boolean).join(", ") ||
          t("companies.locationUnknown")}
      </p>
      {(company.industry_tags ?? []).length > 0 && (
        <p className="text-xs text-slate-400 mt-1">{(company.industry_tags ?? []).join(" · ")}</p>
      )}
      <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
        <span className="font-medium text-primary-700">
          {t("companies.openPostings", { count: company.open_postings })}
        </span>
        {employees && <span>{t("companies.employees", { range: employees })}</span>}
      </div>
    </Link>
  );
}
