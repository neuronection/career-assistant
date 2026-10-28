import { useTranslation } from "react-i18next";
import { Bookmark, ExternalLink, EyeOff, MapPin } from "lucide-react";

import { hidePosting, markApplied, markPostingsSeen, savePosting } from "@/api/postings";
import { buttonVariants } from "@/components/ui";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";
import { safeExternalUrl } from "@/lib/url";
import type { PostingOut } from "@/types/wire";

export function provenanceOf(posting: PostingOut): "raw" | "fast-mapped" | "extracted" {
  if (posting.extract_version != null) return "extracted";
  return posting.mapping_method ? "fast-mapped" : "raw";
}

/** The annualized range ("36,000–54,000") when the figure is normalizable. */
function annualRange(posting: PostingOut): string | null {
  const min = posting.salary_normalized_min;
  const max = posting.salary_normalized_max;
  if (min == null && max == null) return null;
  return [min, max]
    .filter((v) => v != null)
    .map((v) => Number(v).toLocaleString())
    .join("–");
}

/**
 * The posting card shared by the Live tab and Explore: the card body
 * opens the posting's detail page, the action column keeps apply/save/
 * hide (apply leads out to the original listing). Source badge,
 * provenance chip and fit/coverage line as before.
 */
export function PostingCard({
  posting,
  onOpen,
  onChanged,
}: {
  posting: PostingOut;
  onOpen?: (posting: PostingOut) => void;
  onChanged?: () => void;
}) {
  const { t } = useTranslation();
  const postedRel = formatRelativeTime(posting.posted_at);
  const postedAt = postedRel
    ? t(postedRel.key, { count: postedRel.count })
    : formatAbsolute(posting.posted_at);
  const applyUrl = safeExternalUrl(posting.url);

  return (
    <div
      className={`bg-white border rounded-xl p-4 flex items-start gap-4 cursor-pointer hover:border-primary-300 ${
        posting.seen ? "border-slate-100 opacity-80" : "border-slate-200"
      }`}
      data-testid="posting-card"
      onClick={() => onOpen?.(posting)}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            className="font-medium text-slate-900 hover:text-primary-700 text-left"
            data-testid="posting-details"
          >
            <span data-testid="posting-title">{posting.title}</span>
          </button>
          <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded">
            {posting.source_key || posting.ref}
          </span>
          {posting.location?.remote && (
            <span className="text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded">
              {t("postingCard.remote")}
            </span>
          )}
          {posting.contract_type && (
            <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
              {t(`explore.facetValue.${posting.contract_type}`, {
                defaultValue: posting.contract_type.replace(/_/g, " "),
              })}
            </span>
          )}
          {posting.seniority && (
            <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
              {t(`autopilot.seniority.${posting.seniority}`, {
                defaultValue: posting.seniority,
              })}
            </span>
          )}
          <span
            className={`text-xs px-2 py-0.5 rounded ${
              provenanceOf(posting) === "extracted"
                ? "bg-emerald-50 text-emerald-700"
                : "bg-slate-100 text-slate-400"
            }`}
            data-testid="posting-provenance"
            title={
              provenanceOf(posting) === "extracted"
                ? t("postingCard.provenance.extracted")
                : provenanceOf(posting) === "fast-mapped"
                  ? t("postingCard.provenance.fastMapped")
                  : t("postingCard.provenance.raw")
            }
          >
            {t(`postingCard.provenanceValue.${provenanceOf(posting)}`, {
              defaultValue: provenanceOf(posting),
            })}
          </span>
          {posting.needs_review && (
            <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded">
              {t("postingCard.needsReview")}
            </span>
          )}
          {posting.saved && <Bookmark className="w-3.5 h-3.5 text-primary-600 fill-primary-600" />}
        </div>
        <p className="text-sm text-slate-500 mt-1">
          {posting.org}
          {posting.location?.city ? (
            <span className="inline-flex items-center gap-1 ml-2">
              <MapPin className="w-3 h-3" /> {posting.location.city}
              {posting.location.country ? `, ${posting.location.country}` : ""}
            </span>
          ) : null}
          {posting.salary_min != null && (
            <span className="ml-2">
              {posting.salary_currency} {Number(posting.salary_min).toLocaleString()}
              {posting.salary_max != null ? `–${Number(posting.salary_max).toLocaleString()}` : ""} ·{" "}
              {posting.salary_period}
              {posting.salary_basis && (
                <span className="text-slate-400">
                  {" "}({t(`postingCard.salaryBasis.${posting.salary_basis}`)})
                </span>
              )}
            </span>
          )}
          {annualRange(posting) && (
            <span className="ml-2 text-slate-500">
              ≈{" "}
              {t("postingCard.perYear", {
                range: annualRange(posting),
                currency: posting.salary_currency ?? "",
              })}
            </span>
          )}
        </p>
        <div className="flex gap-3 mt-1 text-xs text-slate-400">
          {posting.fit != null && posting.fit > 0 && (
            <span>{t("postingCard.fit", { score: posting.fit.toFixed(1) })}</span>
          )}
          {posting.coverage != null && (
            <span data-testid="posting-coverage">
              {t("postingCard.coverage", { score: posting.coverage.toFixed(1) })}
            </span>
          )}
          {posting.posted_at && (
            <span title={formatAbsolute(posting.posted_at)}>
              {t("postingCard.posted", { date: postedAt })}
            </span>
          )}
          {posting.applied_at && (
            <span className="text-emerald-600">{t("postingCard.applied")}</span>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-1.5" onClick={(e) => e.stopPropagation()}>
        {applyUrl && (
          <a
            href={applyUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => {
              void markPostingsSeen([posting.id]).catch(() => undefined);
              void markApplied(posting.id, posting.url).catch(() => undefined);
            }}
            className={buttonVariants({ variant: "default", size: "sm" })}
            data-testid="posting-apply"
          >
            <ExternalLink className="w-3 h-3" /> {t("postingCard.apply")}
          </a>
        )}
        <button
          onClick={() => {
            void savePosting(posting.id, !posting.saved).then(() => onChanged?.());
          }}
          className={buttonVariants({ variant: "outline", size: "sm" })}
          data-testid="posting-save"
        >
          {posting.saved ? t("postingCard.unsave") : t("common.save")}
        </button>
        <button
          onClick={() => {
            void hidePosting(posting.id, true).then(() => onChanged?.());
          }}
          className="text-xs text-slate-400 flex items-center gap-1 justify-center"
          title={t("postingCard.hideTitle")}
          data-testid="posting-hide"
        >
          <EyeOff className="w-3 h-3" /> {t("postingCard.hide")}
        </button>
      </div>
    </div>
  );
}
