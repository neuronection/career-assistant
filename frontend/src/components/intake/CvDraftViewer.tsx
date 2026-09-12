import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { EmptyState } from "@neuronection/assistant-ui";
import { FileSearch, ArrowUpRight } from "lucide-react";
import { ReportLines } from "./CvStatus";
import { SuggestionReviewList, sectionViews } from "./SuggestionReviewList";
import type { CvAppliedEntity, CvExtractPayload, DraftHistoryRow } from "@/types/cvIntake";

/** Where each entity type landed in the profile — stable section slugs
 * to workspace/hashed-section URLs, shared by provenance surfaces. */
export const APPLIED_ENTITY_LINKS: Partial<Record<CvAppliedEntity["entity_type"], string>> = {
  basics: "/profile",
  skills: "/profile#skills",
  experience_items: "/profile/experience",
  education_items: "/profile/education",
  certifications: "/profile/education",
  profile_achievements: "/profile/education",
  user_interest: "/profile#interests",
};

const APPLIED_ENTITY_LABELS: Partial<Record<CvAppliedEntity["entity_type"], string>> = {
  basics: "basics",
  skills: "skills",
  experience_items: "experience",
  education_items: "education",
  certifications: "certifications",
  profile_achievements: "achievements",
  user_interest: "interests",
  academics_languages: "languages",
};

/** Deep links to where a CV import's created entities landed,
 * driven by the backend's grouped provenance counts. */
export function LandedLinks({ applied }: { applied: CvAppliedEntity[] }) {
  const { t } = useTranslation();
  if (applied.length === 0) return null;
  return (
    <div className="mt-1" data-testid="cv-applied-links">
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
        {t("profileImport.landedTitle")}
      </p>
      <ul className="mt-1 flex flex-wrap gap-2">
        {applied
          .filter((entry) => APPLIED_ENTITY_LINKS[entry.entity_type])
          .map((entry) => (
            <li key={entry.entity_type}>
              <Link
                to={APPLIED_ENTITY_LINKS[entry.entity_type] ?? "/profile"}
                className="inline-flex items-center gap-1 rounded-lg border border-[var(--as-border)] px-2.5 py-1 text-xs text-[var(--as-fg)] hover:border-[var(--as-accent)]"
                data-testid={`cv-applied-link-${entry.entity_type}`}
              >
                {t(`profileImport.landed.${APPLIED_ENTITY_LABELS[entry.entity_type] ?? entry.entity_type}`, {
                  count: entry.count,
                })}
                <ArrowUpRight className="h-3 w-3" aria-hidden />
              </Link>
            </li>
          ))}
      </ul>
    </div>
  );
}

/** Read-only view of what a processed CV contained: the extracted
 * sections (confidence pills + evidence quotes with source-page
 * grounding) plus the apply report — and, when the server tracked it,
 * links to where the import landed in the profile. Rendered on the
 * per-CV detail route for applied/discarded drafts; pending drafts go
 * through the interactive CvIntakeFlow. */
export function CvDraftViewer({
  payload,
  row,
  documentId,
  applied = [],
  loading = false,
}: {
  payload: CvExtractPayload | null;
  row: DraftHistoryRow;
  documentId: string;
  applied?: CvAppliedEntity[];
  loading?: boolean;
}) {
  const { t } = useTranslation();
  const hasPayload = payload != null && sectionViews(payload).length > 0;
  return (
    <div className="space-y-4" data-testid="cv-draft-viewer">
      {hasPayload ? (
        <>
          <h3 className="text-sm font-semibold text-[var(--as-fg)]">
            {t("profileImport.detail.extractedTitle")}
          </h3>
          <SuggestionReviewList
            payload={payload}
            selected={{}}
            onChange={() => {}}
            documentId={documentId}
            readOnly
          />
        </>
      ) : payload == null && loading ? (
        <p className="text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
      ) : (
        <EmptyState
          icon={FileSearch}
          title={t("intake.emptyTitle")}
          description={t("intake.emptyBody")}
        />
      )}
      <LandedLinks applied={applied} />
      <ReportLines report={row.report} updatedAt={row.updated_at} testid="cv-draft-report" />
    </div>
  );
}
