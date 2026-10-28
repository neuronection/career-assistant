import type { SpecItem } from "./specOrder";

/**
 * The spec source fields `postingSpecs` reads. Both `PostingOut` (the feed
 * card) and `CompanyPostingOut` (the company page's row) satisfy it — one
 * spec vocabulary, never a per-surface re-derivation.
 */
export interface SpecSource {
  onsite_policy?: string | null;
  location?: { remote?: boolean | null } | null;
  seniority?: string | null;
  employment_type?: string | null;
  contract_type?: string | null;
  work_hours?: string | null;
  hours_per_week_min?: number | null;
  hours_per_week_max?: number | null;
  salary_currency?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_period?: string | null;
  salary_basis?: string | null;
  salary_normalized_min?: number | null;
  salary_normalized_max?: number | null;
  education_level?: string | null;
  expires_at?: string | null;
}

export type SpecT = (key: string, opts?: Record<string, unknown>) => string;

function compactAmount(value: number): string {
  if (Math.abs(value) >= 10000) return `${Math.round(value / 1000)}k`;
  return Number(value).toLocaleString();
}

export function salaryValue(posting: SpecSource, t: SpecT): string | null {
  const min = posting.salary_min;
  const max = posting.salary_max;
  if (min == null && max == null) return null;
  const range =
    min != null && max != null
      ? `${compactAmount(min)}–${compactAmount(max)}`
      : compactAmount((min ?? max) as number);
  const period = posting.salary_period
    ? t(`postingCard.period.${posting.salary_period}`, {
        defaultValue: posting.salary_period,
      })
    : "";
  const basis = posting.salary_basis
    ? t(`postingCard.salaryBasis.${posting.salary_basis}`, {
        defaultValue: posting.salary_basis,
      })
    : "";
  const base = [posting.salary_currency, `${range}${period ? ` / ${period}` : ""}`, basis]
    .filter(Boolean)
    .join(" ");
  const normalizedMin = posting.salary_normalized_min;
  const normalizedMax = posting.salary_normalized_max;
  if (
    posting.salary_period &&
    posting.salary_period !== "year" &&
    (normalizedMin != null || normalizedMax != null)
  ) {
    const normalizedRange = [normalizedMin, normalizedMax]
      .filter((value): value is number => value != null)
      .map((value) => compactAmount(Number(value)))
      .join("–");
    return `${base} · ${t("card.perYear", {
      range: normalizedRange,
      currency: posting.salary_currency ?? "",
    })}`;
  }
  return base;
}

function hoursValue(posting: SpecSource): string | null {
  if (posting.work_hours) return posting.work_hours;
  const min = posting.hours_per_week_min;
  const max = posting.hours_per_week_max;
  if (min == null && max == null) return null;
  if (min != null && max != null && min !== max) return `${min}–${max} h`;
  return `${min ?? max} h`;
}

function closesInDays(posting: SpecSource): number | null {
  if (!posting.expires_at) return null;
  const diff = new Date(posting.expires_at).getTime() - Date.now();
  if (diff <= 0) return null;
  const days = Math.ceil(diff / 86_400_000);
  return days <= 7 ? days : null;
}

export function postingSpecs(
  posting: SpecSource,
  t: SpecT,
  educationLabel?: (level: string) => string
): SpecItem[] {
  const specs: SpecItem[] = [];
  const mode = posting.onsite_policy ?? (posting.location?.remote ? "remote" : undefined);
  if (mode) {
    specs.push({
      key: "mode",
      label: t("card.mode"),
      value: t(`card.modeValue.${mode}`, {
        defaultValue: String(mode).replace(/_/g, " "),
      }),
    });
  }
  if (posting.seniority) {
    specs.push({
      key: "level",
      label: t("card.level"),
      value: t(`autopilot.seniority.${posting.seniority}`, {
        defaultValue: posting.seniority,
      }),
    });
  }
  const contract = posting.employment_type ?? posting.contract_type;
  if (contract) {
    specs.push({
      key: "contract",
      label: t("card.contract"),
      value: t(`explore.facetValue.${contract}`, {
        defaultValue: contract.replace(/_/g, " "),
      }),
    });
  }
  const hours = hoursValue(posting);
  if (hours) specs.push({ key: "hours", label: t("card.hours"), value: hours });
  const salary = salaryValue(posting, t);
  if (salary) specs.push({ key: "salary", label: t("card.salary"), value: salary });
  if (posting.education_level) {
    const labeler =
      educationLabel ??
      ((level: string) =>
        t(`explore.facetValue.${level}`, { defaultValue: level.replace(/_/g, " ") }));
    specs.push({
      key: "education",
      label: t("card.education"),
      value: labeler(posting.education_level),
    });
  }
  const closes = closesInDays(posting);
  if (closes != null) {
    specs.push({
      key: "closes",
      label: t("card.closes"),
      value: t("card.closesIn", { count: closes }),
      tone: "warning",
    });
  }
  return specs;
}
