import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Mail } from "lucide-react";

import { Badge, Button, EmptyState, Spinner } from "@/components/ui";
import { createCoverLetter } from "@/api/cv";
import { apiDetail } from "@/api/client";
import type { ApplicationKit, PostingKit } from "@/types/wire";

/** The kit's cover-letter tab: the posting-scoped letter (or the
 * explicit "create one" action — a user click, never a silent write),
 * the user's other letters and the link-to-application action. */
export function KitLetterTab({
  kit,
  applicationId,
  onLinkDocument,
  onChanged,
}: {
  kit: PostingKit | ApplicationKit;
  applicationId: string | null;
  onLinkDocument: (coverLetterId: string) => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const doc = kit.cover_letter?.doc ?? null;
  const others = (kit.cover_letter?.candidates ?? []).filter(
    (ref) => ref.id !== doc?.id,
  );

  async function create() {
    setBusy(true);
    setError("");
    try {
      await createCoverLetter({ posting_id: kit.posting.id });
      onChanged();
    } catch (exc) {
      setError(apiDetail(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4 py-3" data-testid="kit-letter-tab">
      {doc === null ? (
        <EmptyState
          icon={Mail}
          title={t("applications.kit.letter.noneTitle")}
          description={t("applications.kit.letter.noneBody")}
          action={
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void create()}
              data-testid="kit-letter-create"
            >
              {busy ? <Spinner /> : t("applications.kit.letter.create")}
            </Button>
          }
        />
      ) : (
        <section
          className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
          data-testid="kit-letter-doc"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Mail className="size-4 text-[var(--as-accent)]" aria-hidden />
            <span className="text-sm font-medium text-[var(--as-fg)]">
              {doc.title || t("applications.kit.letter.untitled")}
            </span>
            <Badge variant="default" data-testid="kit-letter-scoped-badge">
              {t("applications.kit.letter.scopedBadge")}
            </Badge>
            <div className="ml-auto flex items-center gap-2">
              <Button asChild size="sm" variant="outline">
                <Link to={`/cv/${doc.id}`} data-testid="kit-letter-open">
                  {t("applications.kit.letter.openInStudio")}
                </Link>
              </Button>
              {applicationId !== null && (
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="kit-letter-link"
                  onClick={() => onLinkDocument(doc.id)}
                >
                  {t("applications.kit.linkToApplication")}
                </Button>
              )}
            </div>
          </div>
          <p className="mt-2 text-xs text-[var(--as-muted-fg)]">
            {t("applications.kit.letter.verifiedNote")}
          </p>
        </section>
      )}

      {others.length > 0 && (
        <section className="space-y-1.5" data-testid="kit-letter-others">
          <h3 className="text-sm font-semibold text-[var(--as-fg)]">
            {t("applications.kit.letter.others")}
          </h3>
          <ul className="space-y-1.5">
            {others.map((ref) => (
              <li
                key={ref.id}
                className="flex flex-wrap items-center gap-2 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2"
              >
                <Link
                  to={`/cv/${ref.id}`}
                  className="min-w-0 flex-1 truncate text-sm text-[var(--as-fg)] hover:underline"
                >
                  {ref.title || t("applications.kit.letter.untitled")}
                </Link>
                {applicationId !== null && (
                  <Button
                    size="sm"
                    variant="ghost"
                    data-testid={`kit-letter-link-${ref.id}`}
                    onClick={() => onLinkDocument(ref.id)}
                  >
                    {t("applications.kit.linkToApplication")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {error !== "" && (
        <p className="text-xs text-rose-600" data-testid="kit-letter-error">
          {error}
        </p>
      )}
    </div>
  );
}
