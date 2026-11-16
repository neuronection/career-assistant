import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ExternalLink, PackageCheck } from "lucide-react";

import { fetchApplicationKit } from "@/api/applications";
import { apiDetail } from "@/api/client";
import { Button, EmptyState, Spinner } from "@/components/ui";
import { KitView } from "@/features/postings/components/kit/KitView";
import type { ApplicationKit } from "@/types/wire";

/** The application kit page (plan 212 S1.3, `/applications/:id`): the
 * tracker's kit — CV variant, cover letter, answers, checklist and the
 * event timeline — with every document link riding the tracker's own
 * audited endpoints. */
export function ApplicationKitPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [kit, setKit] = useState<ApplicationKit | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (id === undefined) return;
    setError("");
    try {
      setKit(await fetchApplicationKit(id));
    } catch (exc) {
      setError(apiDetail(exc));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (id === undefined) return null;

  if (error !== "") {
    return (
      <div className="ca-workspace" data-testid="application-kit-page">
        <EmptyState
          title={t("applications.kit.loadError")}
          description={error}
          action={
            <Link to="/applications" className="text-sm text-[var(--as-accent)]">
              {t("applications.kit.backToApplications")}
            </Link>
          }
        />
      </div>
    );
  }

  if (kit === null) {
    return (
      <div className="ca-workspace flex min-h-[40vh] items-center justify-center" data-testid="application-kit-page">
        <Spinner />
      </div>
    );
  }

  const openOriginal = kit.posting.url !== "";

  return (
    <div className="ca-workspace flex flex-col gap-3" data-testid="application-kit-page">
      <div className="flex flex-wrap items-start gap-2">
        <Link
          to="/applications"
          className="inline-flex items-center gap-1.5 text-sm text-primary-700 hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {t("applications.kit.backToApplications")}
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
        <div className="ml-auto flex items-center gap-2">
          <Button asChild size="sm" variant="outline">
            <Link to={`/postings/${kit.posting.ref}`} data-testid="kit-open-posting">
              {t("applications.kit.openPosting")}
            </Link>
          </Button>
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
        </div>
      </div>

      <KitView
        kit={kit}
        applicationId={kit.application?.id ?? id}
        onChanged={() => void load()}
      />
    </div>
  );
}
