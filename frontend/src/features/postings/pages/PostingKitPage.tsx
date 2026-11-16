import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Briefcase, ExternalLink, PackageCheck } from "lucide-react";

import { fetchPostingKit } from "@/api/postings";
import { apiDetail } from "@/api/client";
import { Button, EmptyState, Spinner } from "@/components/ui";
import { KitView } from "@/features/postings/components/kit/KitView";
import { MarkAppliedDialog } from "@/features/postings/components/kit/MarkAppliedDialog";
import { listReturnHref, LIST_RETURN_STATE } from "@/lib/listReturn";
import type { PostingKit } from "@/types/wire";

/** The pre-application kit (plan 212 S1.3, `/postings/:ref/kit`): the
 * saved posting as a reviewable application — gap, CV variant, letter,
 * answers, checklist — with "mark as applied" as the one explicit
 * write. No auto-apply, no external submission. */
export function PostingKitPage() {
  const { t } = useTranslation();
  const { ref } = useParams<{ ref: string }>();
  const [kit, setKit] = useState<PostingKit | null>(null);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);

  const load = useCallback(async () => {
    if (ref === undefined) return;
    setError("");
    try {
      setKit(await fetchPostingKit(ref));
    } catch (exc) {
      setError(apiDetail(exc));
    }
  }, [ref]);

  useEffect(() => {
    void load();
  }, [load]);

  if (ref === undefined) return null;

  if (error !== "") {
    return (
      <div className="ca-workspace" data-testid="posting-kit-page">
        <EmptyState
          title={t("applications.kit.loadError")}
          description={error}
          action={
            <Link to={listReturnHref("/postings")} state={LIST_RETURN_STATE} className="text-sm text-[var(--as-accent)]">
              {t("postingDetail.backToPostings")}
            </Link>
          }
        />
      </div>
    );
  }

  if (kit === null) {
    return (
      <div className="ca-workspace flex min-h-[40vh] items-center justify-center" data-testid="posting-kit-page">
        <Spinner />
      </div>
    );
  }

  const openOriginal = kit.posting.url !== "";

  return (
    <div className="ca-workspace flex flex-col gap-3" data-testid="posting-kit-page">
      <div className="flex flex-wrap items-start gap-2">
        <Link
          to={listReturnHref(`/postings/${kit.posting.ref}`)}
          state={LIST_RETURN_STATE}
          className="inline-flex items-center gap-1.5 text-sm text-primary-700 hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {t("applications.kit.backToPosting")}
        </Link>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="flex min-w-0 items-center gap-2 text-lg font-semibold text-[var(--as-fg)]">
          <PackageCheck className="size-5 shrink-0 text-[var(--as-accent)]" aria-hidden />
          <span className="min-w-0 truncate" data-testid="kit-title">
            {kit.posting.title}
          </span>
        </h1>
        <span className="text-sm text-[var(--as-muted-fg)]">{kit.posting.org}</span>
        {kit.application !== undefined && kit.application !== null && (
          <Button asChild size="sm" variant="outline">
            <Link to={`/applications/${kit.application.id}`} data-testid="kit-open-application">
              <Briefcase className="mr-1 size-3.5" aria-hidden />
              {t("applications.kit.openApplication")}
            </Link>
          </Button>
        )}
        <div className="ml-auto flex items-center gap-2">
          {openOriginal && (
            <Button asChild size="sm" variant="outline">
              <a
                href={kit.posting.url}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="kit-open-original"
              >
                <ExternalLink className="mr-1 size-3.5" aria-hidden />
                {t("applications.kit.openOriginal")}
              </a>
            </Button>
          )}
          {kit.application == null && (
            <Button size="sm" onClick={() => setDialogOpen(true)} data-testid="kit-mark-applied">
              {t("applications.kit.markApplied.submit")}
            </Button>
          )}
        </div>
      </div>

      <KitView
        kit={kit}
        applicationId={kit.application?.id ?? null}
        onChanged={() => void load()}
        timelineFallback={
          <Button size="sm" onClick={() => setDialogOpen(true)} data-testid="kit-timeline-mark">
            {t("applications.kit.markApplied.submit")}
          </Button>
        }
      />

      <MarkAppliedDialog kit={kit} open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
