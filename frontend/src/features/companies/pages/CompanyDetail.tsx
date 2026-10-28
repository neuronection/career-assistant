import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { fetchCompany } from "@/api/companies";
import { fetchPostings } from "@/api/postings";
import { Badge, EmptyState } from "@/components/ui";
import { OrgAvatar } from "@/components/company/OrgAvatar";
import { PostingCard } from "@/features/postings/components/PostingCard";
import { apiDetail } from "@/api/client";
import { safeExternalUrl } from "@/lib/url";
import type { CompanyDetail } from "@/types/wire";
import type { PostingOut } from "@/types/wire";

export function CompanyDetail() {
  const { key = "" } = useParams();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [postings, setPostings] = useState<PostingOut[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    void fetchCompany(key)
      .then(setCompany)
      .catch((err) => setError(apiDetail(err)));
    void fetchPostings({ company: key, sort: "fresh" })
      .then((res) => setPostings(res.items))
      .catch(() => setPostings([]));
  }, [key]);

  useEffect(() => {
    setError("");
    setCompany(null);
    load();
  }, [load]);

  if (error) {
    return (
      <div className="max-w-4xl mx-auto space-y-4" data-testid="company-detail">
        <BackLink />
        <p className="text-sm text-[var(--as-danger)]">{error}</p>
      </div>
    );
  }
  if (!company) {
    return (
      <div className="max-w-4xl mx-auto space-y-6" data-testid="company-detail">
        <BackLink />
        <div className="cv-shimmer h-16 rounded-[var(--as-radius-lg)]" />
        <div className="cv-shimmer h-24 rounded-[var(--as-radius-lg)]" />
        <div className="cv-shimmer h-64 rounded-[var(--as-radius-lg)]" />
      </div>
    );
  }

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
      <header className="space-y-1.5">
        <div className="flex min-w-0 items-center gap-3">
          <OrgAvatar name={company.name} size={40} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold text-[var(--as-fg)]">{company.name}</h1>
              {company.status === "proposed" && (
                <Badge variant="outline" data-testid="company-proposed-badge">
                  {t("companyDetail.proposed")}
                </Badge>
              )}
              {company.needs_review && (
                <Badge variant="secondary" data-testid="company-needs-review">
                  {t("companyDetail.needsReview")}
                </Badge>
              )}
            </div>
            {company.company_type ? (
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
                {t(`companies.type.${company.company_type}`, {
                  defaultValue: String(company.company_type),
                })}
              </p>
            ) : null}
          </div>
        </div>
        {(company.aliases?.length ?? 0) > 0 && (
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="company-aliases">
            {t("companyDetail.alsoKnownAs")} {(company.aliases ?? []).join(" · ")}
          </p>
        )}
        {company.description && (
          <p className="text-sm text-[var(--as-fg)]">{company.description}</p>
        )}
      </header>

      <section
        className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4 space-y-2"
        data-testid="company-facts"
      >
        <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-2">
          {facts.map(([label, value]) =>
            value ? (
              <div key={label} className="flex gap-2 text-sm">
                <dt className="w-24 shrink-0 text-[var(--as-muted-fg)]">{label}</dt>
                <dd className="text-[var(--as-fg)]">{value}</dd>
              </div>
            ) : null,
          )}
        </dl>
        {(company.links ?? []).length > 0 && (
          <div className="flex flex-wrap gap-3 pt-1">
            {(company.links ?? []).map((link) => {
              const url = safeExternalUrl(link.url);
              return url ? (
                <a
                  key={link.url}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-[var(--as-accent)] inline-flex items-center gap-1 hover:underline"
                >
                  {link.label} <ExternalLink className="w-3.5 h-3.5" />
                </a>
              ) : null;
            })}
          </div>
        )}
      </section>

      {(company.financials ?? []).length > 0 && (
        <section className="space-y-2" data-testid="company-financials">
          <h2 className="font-semibold text-[var(--as-fg)]">{t("companyDetail.financials")}</h2>
          <div className="grid md:grid-cols-2 gap-3">
            {(company.financials ?? []).map((claim, index) => (
              <div
                key={`${claim.kind}-${index}`}
                className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
              >
                <p className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
                  {t(`companyDetail.claimKind.${claim.kind}`)}
                </p>
                <p className="font-medium text-[var(--as-fg)]">
                  {formatMoney(claim.amount, claim.currency)}
                  {claim.as_of && (
                    <span className="text-xs font-normal text-[var(--as-muted-fg)]"> · {claim.as_of}</span>
                  )}
                </p>
                {claim.source && (
                  <p className="mt-1 text-xs text-[var(--as-muted-fg)]">{claim.source}</p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <DerivedStats company={company} />

      <section className="space-y-3" data-testid="company-postings">
        <h2 className="font-semibold text-[var(--as-fg)]">
          {t("companyDetail.postingsTitle", { count: company.open_postings })}
        </h2>
        {postings.length === 0 ? (
          <EmptyState
            compact
            title={t("companyDetail.noPostings")}
            description={t("companyDetail.noPostingsBody")}
          />
        ) : (
          <ul className="space-y-2">
            {postings.map((posting) => (
              <li key={posting.id}>
                <PostingCard
                  posting={posting}
                  onOpen={(item) => navigate(`/postings/${item.ref}`)}
                  onChanged={load}
                />
              </li>
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
    <section
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4 space-y-3"
      data-testid="company-derived"
    >
      <h2 className="font-semibold text-sm text-[var(--as-fg)]">{t("companyDetail.hiringSignal")}</h2>
      <div className="grid sm:grid-cols-2 gap-4 text-sm">
        {Object.keys(seniority).length > 0 && (
          <div>
            <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
              {t("companyDetail.bySeniority")}
            </p>
            <div className="flex flex-wrap gap-1">
              {Object.entries(seniority).map(([level, count]) => (
                <span
                  key={level}
                  className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-xs text-[var(--as-muted-fg)]"
                >
                  {t(`autopilot.seniority.${level}`, { defaultValue: level })} · {count}
                </span>
              ))}
            </div>
          </div>
        )}
        {Object.keys(onsite).length > 0 && (
          <div>
            <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
              {t("companyDetail.byOnsite")}
            </p>
            <div className="flex flex-wrap gap-1">
              {Object.entries(onsite).map(([policy, count]) => (
                <span
                  key={policy}
                  className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-xs text-[var(--as-muted-fg)]"
                >
                  {t(`companyDetail.onsite.${policy}`, {
                    defaultValue: policy.replace(/_/g, " "),
                  })}{" "}
                  · {count}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      {locations.length > 0 && (
        <div className="text-sm">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
            {t("companyDetail.topLocations")}
          </p>
          <p className="text-[var(--as-fg)]">
            {locations
              .map((spot) => [spot.city, spot.country].filter(Boolean).join(", ") + ` (${spot.count})`)
              .join(" · ")}
          </p>
        </div>
      )}
    </section>
  );
}

function BackLink() {
  const { t } = useTranslation();
  return (
    <Link
      to="/companies"
      className="text-sm text-[var(--as-accent)] inline-flex items-center gap-1 hover:underline"
    >
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
