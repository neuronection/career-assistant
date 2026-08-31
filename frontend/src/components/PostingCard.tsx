import { Bookmark, ExternalLink, EyeOff, MapPin } from "lucide-react";

import { hidePosting, markApplied, markPostingsSeen, savePosting } from "@/api/postings";
import type { JobPostingItem } from "@/types";

export function provenanceOf(posting: JobPostingItem): "raw" | "fast-mapped" | "extracted" {
  if (posting.extract_version != null) return "extracted";
  return posting.mapping_method ? "fast-mapped" : "raw";
}

/**
 * The posting card shared by the Live tab and Explore (plan 32): source
 * badge everywhere (display-only, per plan-21 discipline), provenance
 * chip, fit/coverage line, apply/save/hide actions.
 */
export function PostingCard({
  posting,
  onOpenDetail,
  onChanged,
}: {
  posting: JobPostingItem;
  onOpenDetail?: (posting: JobPostingItem) => void;
  onChanged?: () => void;
}) {
  const openOriginal = () => {
    void markPostingsSeen([posting.id]).catch(() => undefined);
    if (posting.url) {
      void markApplied(posting.id, posting.url).catch(() => undefined);
      window.open(posting.url, "_blank", "noopener");
    }
  };

  return (
    <div
      className={`bg-white border rounded-xl p-4 flex items-start gap-4 ${
        posting.seen ? "border-slate-100 opacity-80" : "border-slate-200"
      }`}
      data-testid="posting-card"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={openOriginal}
            className="font-medium text-slate-900 hover:text-primary-700"
            data-testid="posting-title"
          >
            {posting.title}
          </button>
          <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded">
            {posting.source_key || posting.ref}
          </span>
          {posting.location?.remote && (
            <span className="text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded">remote</span>
          )}
          {posting.seniority && (
            <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
              {posting.seniority}
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
                ? "Deep-extracted: structured skills, salary and responsibilities"
                : provenanceOf(posting) === "fast-mapped"
                  ? "Fast-mapped to the catalog; structured extraction pending"
                  : "Raw posting — not mapped yet"
            }
          >
            {provenanceOf(posting)}
          </span>
          {posting.needs_review && (
            <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded">
              needs review
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
            </span>
          )}
        </p>
        <div className="flex gap-3 mt-1 text-xs text-slate-400">
          {posting.fit != null && posting.fit > 0 && <span>fit {posting.fit.toFixed(1)}</span>}
          {posting.coverage != null && (
            <span data-testid="posting-coverage">coverage {posting.coverage.toFixed(1)}</span>
          )}
          {posting.posted_at && (
            <span>posted {new Date(posting.posted_at).toLocaleDateString()}</span>
          )}
          {posting.applied_at && <span className="text-emerald-600">applied ✓</span>}
          {onOpenDetail && (
            <button
              onClick={() => onOpenDetail(posting)}
              className="text-primary-700 hover:underline"
              data-testid="posting-details"
            >
              details
            </button>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        {posting.url && (
          <a
            href={posting.url}
            target="_blank"
            rel="noreferrer"
            onClick={() => {
              void markPostingsSeen([posting.id]).catch(() => undefined);
              void markApplied(posting.id, posting.url).catch(() => undefined);
            }}
            className="text-xs bg-primary-600 text-white rounded-lg px-3 py-1.5 flex items-center gap-1"
          >
            <ExternalLink className="w-3 h-3" /> Apply
          </a>
        )}
        <button
          onClick={() => {
            void savePosting(posting.id, !posting.saved).then(() => onChanged?.());
          }}
          className="text-xs border border-slate-200 rounded-lg px-3 py-1.5"
        >
          {posting.saved ? "Unsave" : "Save"}
        </button>
        <button
          onClick={() => {
            void hidePosting(posting.id, true).then(() => onChanged?.());
          }}
          className="text-xs text-slate-400 flex items-center gap-1 justify-center"
          title="Hide from the live tab"
        >
          <EyeOff className="w-3 h-3" /> hide
        </button>
      </div>
    </div>
  );
}
