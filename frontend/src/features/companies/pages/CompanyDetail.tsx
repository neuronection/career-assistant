import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { fetchCompany, fetchCompanyPostings } from "@/api/companies";
import { EmptyState } from "@/components/ui";
import { apiDetail } from "@/api/client";
import type { CompanyDetail, CompanyPosting } from "@/types/wire";

export function CompanyDetail() {
  const { key = "" } = useParams();
  const { t } = useTranslation();
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [postings, setPostings] = useState<CompanyPosting[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    void fetchCompany(key)
      .then(setCompany)
      .catch((err) => setError(apiDetail(err)));
    void fetchCompanyPostings(key)
      .then(setPostings)
      .catch(() => setPostings([]));
  }, [key]);

  if (error) {
    return (
      <div className="max-w-4xl mx-auto space-y-4" data-testid="company-detail">
        <BackLink />
        <p className="text-sm text-rose-600">{error}</p>
      </div>
    );
  }
  if (!company) return <p>{t("common.loading")}</p>;

  const facts: Array<[string, string | null | undefined]> = [
    [t("companyDetail.hq"), [company.hq_city, company.hq_country].filter(Boolean).join(", ")],
    [
      t("companyDetail.employees"),
      company.employees_min != null || company.employees_max != null
        ? [company.employees_min, company.employees_max].filter((v) => v != null).join("–")
        : null,
    ],
    [t("companyDetail.founded"), company.founded_year ? String(company.founded_year) : null],
    [t("companyDetail.industry"), (company.industry_tags ?? []).join(" · ") || null],
    [t("companyDetail.domain"), company.domain],
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="company-detail">
      <BackLink />
      <header className="space-y-1">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">{company.name}</h1>
          {company.status === "proposed" && (
            <span
              className="text-xs bg-sky-100 text-sky-700 px-2 py-1 rounded-full"
              data-testid="company-proposed-badge"
            >
              {t("companyDetail.proposed")}
            </span>
          )}
          {company.company_type && (
            <span className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-full">
              {t(`companies.type.${company.company_type}`)}
            </span>
          )}
          {company.needs_review && (
            <span className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-full">
              {t("companyDetail.needsReview")}
            </span>
          )}
        </div>
        {(company.aliases?.length ?? 0) > 0 && (
          <p className="text-xs text-slate-400" data-testid="company-aliases">
            {t("companyDetail.alsoKnownAs")} {(company.aliases ?? []).join(" · ")}
          </p>
        )}
        {company.description && <p className="text-sm text-slate-600">{company.description}</p>}
      </header>

      <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-2">
        <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-2">
          {facts.map(([label, value]) =>
            value ? (
              <div key={label} className="flex gap-2 text-sm">
                <dt className="text-slate-400 w-24 shrink-0">{label}</dt>
                <dd className="text-slate-700">{value}</dd>
              </div>
            ) : null,
          )}
        </dl>
        {(company.links ?? []).length > 0 && (
          <div className="flex flex-wrap gap-3 pt-1">
            {(company.links ?? []).map((link) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-primary-700 inline-flex items-center gap-1"
              >
                {link.label} <ExternalLink className="w-3.5 h-3.5" />
              </a>
            ))}
          </div>
        )}
      </section>

      {(company.financials ?? []).length > 0 && (
        <section className="space-y-2" data-testid="company-financials">
          <h2 className="font-semibold">{t("companyDetail.financials")}</h2>
          <div className="grid md:grid-cols-2 gap-3">
            {(company.financials ?? []).map((claim, index) => (
              <div key={`${claim.kind}-${index}`} className="bg-white border border-slate-200 rounded-xl p-4">
                <p className="text-xs uppercase tracking-wide text-slate-400">
                  {t(`companyDetail.claimKind.${claim.kind}`)}
                </p>
                <p className="font-medium">
                  {formatMoney(claim.amount, claim.currency)}
                  {claim.as_of && (
                    <span className="text-xs text-slate-400 font-normal"> · {claim.as_of}</span>
                  )}
                </p>
                {claim.source && <p className="text-xs text-slate-400 mt-1">{claim.source}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      <DerivedStats company={company} />

      <section className="space-y-3" data-testid="company-postings">
        <h2 className="font-semibold">
          {t("companyDetail.postingsTitle", { count: company.open_postings })}
        </h2>
        {postings.length === 0 ? (
          <EmptyState compact title={t("companyDetail.noPostings")} />
        ) : (
          <ul className="space-y-2">
            {postings.map((posting) => (
              <PostingRow key={posting.id} posting={posting} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function DerivedStats({ company }: { company: CompanyDetail }) {
  const { t } = useTranslation();
  const derived = company.derived;
  if (!derived || derived.open_postings === 0) return null;
  const seniority = derived.by_seniority ?? {};
  const onsite = derived.by_onsite_policy ?? {};
  const locations = derived.top_locations ?? [];
  return (
    <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-3">
      <h2 className="font-semibold text-sm">{t("companyDetail.hiringSignal")}</h2>
      <div className="grid sm:grid-cols-2 gap-4 text-sm">
        {Object.keys(seniority).length > 0 && (
          <div>
            <p className="text-xs text-slate-400 mb-1">{t("companyDetail.bySeniority")}</p>
            <div className="flex flex-wrap gap-1">
              {Object.entries(seniority).map(([level, count]) => (
                <span key={level} className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-full">
                  {level} · {count}
                </span>
              ))}
            </div>
          </div>
        )}
        {Object.keys(onsite).length > 0 && (
          <div>
            <p className="text-xs text-slate-400 mb-1">{t("companyDetail.byOnsite")}</p>
            <div className="flex flex-wrap gap-1">
              {Object.entries(onsite).map(([policy, count]) => (
                <span key={policy} className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-full">
                  {t(`companyDetail.onsite.${policy}`)} · {count}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      {locations.length > 0 && (
        <div className="text-sm">
          <p className="text-xs text-slate-400 mb-1">{t("companyDetail.topLocations")}</p>
          <p className="text-slate-600">
            {locations
              .map((spot) =>
                [spot.city, spot.country].filter(Boolean).join(", ") + ` (${spot.count})`,
              )
              .join(" · ")}
          </p>
        </div>
      )}
    </section>
  );
}

function PostingRow({ posting }: { posting: CompanyPosting }) {
  const { t } = useTranslation();
  const location = posting.location
    ? [posting.location.city, posting.location.country].filter(Boolean).join(", ")
    : "";
  return (
    <li className="bg-white border border-slate-200 rounded-xl p-4 flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <p className="font-medium text-sm truncate">{posting.title}</p>
        <p className="text-xs text-slate-400">
          {[
            location || t("companies.locationUnknown"),
            posting.seniority,
            posting.onsite_policy ? t(`companyDetail.onsite.${posting.onsite_policy}`) : null,
            posting.posted_at ? new Date(posting.posted_at).toLocaleDateString() : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      {posting.url && (
        <a
          href={posting.url}
          target="_blank"
          rel="noreferrer"
          className="text-sm text-primary-700 inline-flex items-center gap-1 whitespace-nowrap"
        >
          {t("companyDetail.viewPosting")} <ExternalLink className="w-3.5 h-3.5" />
        </a>
      )}
    </li>
  );
}

function BackLink() {
  const { t } = useTranslation();
  return (
    <Link to="/companies" className="text-sm text-primary-700 inline-flex items-center gap-1">
      <ArrowLeft className="w-4 h-4" /> {t("companyDetail.back")}
    </Link>
  );
}

function formatMoney(amount: string | number, currency: string): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value} ${currency}`;
  }
}
