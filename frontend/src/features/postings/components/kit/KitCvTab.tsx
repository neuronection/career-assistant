import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { CheckCircle2, FileText, GraduationCap, Sparkles } from "lucide-react";

import { Badge, Button, EmptyState, Spinner } from "@/components/ui";
import { GapCard } from "@/features/postings/components/posting-detail/GapCard";
import type { ApplicationKit, KitPrepare, PostingKit } from "@/types/wire";

function docTitle(t: (key: string) => string, ref: { title: string }): string {
  return ref.title || t("applications.kit.cv.untitled");
}

/** The kit's CV tab: the working document, the deterministic prep
 * (review cards — apply means "open it in CV Studio", dismiss hides the
 * card locally; nothing is ever auto-applied) and the S1.1 gap report. */
export function KitCvTab({
  kit,
  applicationId,
  prepare,
  prepareBusy,
  onPrepare,
  onLinkDocument,
  dismissed,
  onDismiss,
}: {
  kit: PostingKit | ApplicationKit;
  applicationId: string | null;
  prepare: KitPrepare | null;
  prepareBusy: boolean;
  onPrepare: () => void;
  onLinkDocument: (cvId: string) => void;
  dismissed: string[];
  onDismiss: (sourceKey: string) => void;
}) {
  const { t } = useTranslation();
  if (kit.cv?.needs_cv) {
    return (
      <div className="py-6" data-testid="kit-cv-needs-cv">
        <EmptyState
          icon={GraduationCap}
          title={t("applications.kit.cv.needsCvTitle")}
          description={t("applications.kit.cv.needsCvBody")}
          action={
            <Link
              to="/cv"
              className="text-sm font-medium text-[var(--as-accent)] hover:underline"
              data-testid="kit-cv-studio-cta"
            >
              {t("applications.kit.cv.openCvStudio")}
            </Link>
          }
        />
      </div>
    );
  }
  const working = kit.cv?.variant ?? kit.cv?.candidates?.[0] ?? null;
  const sectionGaps = (prepare?.section_gaps ?? []).filter(
    (gap) => !dismissed.includes(`section:${gap.source_key}`),
  );
  const coverage = prepare?.coverage ?? null;
  const coveredCount = coverage?.covered?.length ?? 0;
  const missingCount = coverage?.missing?.length ?? 0;
  return (
    <div className="space-y-4 py-3" data-testid="kit-cv-tab">
      {working !== null && (
        <section
          className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
          data-testid="kit-cv-working"
        >
          <div className="flex flex-wrap items-center gap-2">
            <FileText className="size-4 text-[var(--as-accent)]" aria-hidden />
            <span className="text-sm font-medium text-[var(--as-fg)]">
              {docTitle(t, working)}
            </span>
            {kit.cv?.variant !== null && kit.cv?.variant !== undefined && (
              <Badge variant="default" data-testid="kit-cv-variant-badge">
                {t("applications.kit.cv.variantBadge")}
              </Badge>
            )}
            <div className="ml-auto flex items-center gap-2">
              <Button asChild size="sm" variant="outline">
                <Link to={`/cv/${working.id}`} data-testid="kit-cv-open">
                  {t("applications.kit.cv.openInStudio")}
                </Link>
              </Button>
              {applicationId !== null && (
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="kit-cv-link"
                  onClick={() => onLinkDocument(working.id)}
                >
                  {t("applications.kit.linkToApplication")}
                </Button>
              )}
            </div>
          </div>
          {(kit.cv?.candidates?.length ?? 0) > 1 && (
            <p className="mt-2 text-xs text-[var(--as-muted-fg)]" data-testid="kit-cv-candidates">
              {t("applications.kit.cv.candidates", { count: kit.cv?.candidates?.length ?? 0 })}
            </p>
          )}
        </section>
      )}

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-[var(--as-fg)]">
            {t("applications.kit.cv.prepHeading")}
          </h3>
          {prepare === null ? (
            <Button
              size="sm"
              disabled={prepareBusy}
              onClick={onPrepare}
              data-testid="kit-cv-prepare"
            >
              <Sparkles className="mr-1 size-3.5" aria-hidden />
              {prepareBusy ? t("applications.kit.cv.preparing") : t("applications.kit.cv.prepare")}
            </Button>
          ) : (
            <span className="text-xs text-[var(--as-muted-fg)]" data-testid="kit-coverage-summary">
              {t("applications.kit.cv.coverageSummary", { covered: coveredCount, missing: missingCount })}
            </span>
          )}
        </div>
        {prepareBusy && prepare === null && (
          <div className="flex justify-center py-3">
            <Spinner />
          </div>
        )}
        {prepare !== null && !prepare.extract_ready && (
          <p
            className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)] p-2 text-xs text-[var(--as-muted-fg)]"
            data-testid="kit-prep-no-extract"
          >
            {t("applications.kit.cv.noExtract")}
          </p>
        )}
        {prepare !== null && sectionGaps.length > 0 && (
          <ul className="space-y-2" data-testid="kit-section-gaps">
            {sectionGaps.map((gap) => (
              <li
                key={gap.source_key}
                className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
                data-testid={`kit-section-gap-${gap.source_key}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <CheckCircle2 className="size-4 text-[var(--as-accent)]" aria-hidden />
                  <span className="text-sm font-medium text-[var(--as-fg)]">{gap.label}</span>
                  <span className="text-xs text-[var(--as-muted-fg)]">
                    {t("applications.kit.cv.sectionCandidates", { count: gap.candidate_count })}
                  </span>
                </div>
                <p className="mt-1 text-xs text-[var(--as-muted-fg)]">{gap.message}</p>
                <div className="mt-2 flex items-center gap-2">
                  {prepare.cv_id !== null && (
                    <Button asChild size="sm" variant="outline">
                      <Link to={`/cv/${prepare.cv_id}`} data-testid={`kit-section-apply-${gap.source_key}`}>
                        {t("applications.kit.review.apply")}
                      </Link>
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    data-testid={`kit-section-dismiss-${gap.source_key}`}
                    onClick={() => onDismiss(`section:${gap.source_key}`)}
                  >
                    {t("applications.kit.review.dismiss")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {prepare !== null && sectionGaps.length === 0 && prepare.extract_ready && (
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="kit-section-gaps-none">
            {t("applications.kit.cv.sectionsOk")}
          </p>
        )}
      </section>

      <GapCard gap={kit.gap ?? null} />
    </div>
  );
}
