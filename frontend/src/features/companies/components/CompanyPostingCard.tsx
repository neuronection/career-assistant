import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Clock, ExternalLink, MapPin } from "lucide-react";

import { buttonVariants } from "@/components/ui";
import { CardMeta } from "@/components/cards/CardMeta";
import { CardSpec } from "@/components/cards/CardSpec";
import { ClosedMark } from "@/components/cards/CardState";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import { postingSpecs } from "@/components/cards/postingSpecs";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";
import { safeExternalUrl } from "@/lib/url";
import type { CompanyPosting } from "@/types/wire";

const OPEN_STATUSES = new Set(["new", "mapped"]);

/**
 * One of the company page's postings, in the plan-140 card grammar. The
 * card opens the posting's in-app page (`/postings/:ref`, plan 131); the
 * external board link rides the action column. Company rows carry no
 * personalization plumbing (no fit/saved) by contract — the spec slots
 * share the feed card's vocabulary.
 */
export function CompanyPostingCard({ posting }: { posting: CompanyPosting }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const open = OPEN_STATUSES.has(posting.status);
  const url = safeExternalUrl(posting.url);
  const location = [posting.location?.city, posting.location?.country]
    .filter(Boolean)
    .join(", ");
  const postedRel = formatRelativeTime(posting.posted_at);
  const postedAt = postedRel
    ? t(postedRel.key, { count: postedRel.count })
    : formatAbsolute(posting.posted_at);

  return (
    <ItemCardShell
      testId={`company-posting-${posting.ref}`}
      state={open ? undefined : "closed"}
      onOpen={() => navigate(`/postings/${posting.ref}`)}
      actions={
        <>
          {!open ? <ClosedMark label={t("card.closed")} testId="company-posting-closed" /> : null}
          {url ? (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ variant: "outline", size: "sm" })}
              data-testid="company-posting-view"
            >
              <ExternalLink className="w-3 h-3" /> {t("companyDetail.viewPosting")}
            </a>
          ) : null}
        </>
      }
    >
      <div className="min-w-0 flex-1">
        <button
          type="button"
          className="min-w-0 truncate text-left font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
          data-testid="company-posting-title"
        >
          {posting.title}
        </button>
        <CardMeta
          className="mt-0.5"
          items={[
            ...(location
              ? [{ key: "location", icon: MapPin, text: location }]
              : []),
            ...(postedAt
              ? [
                  {
                    key: "posted",
                    icon: Clock,
                    text: t("postingCard.posted", { date: postedAt }),
                    title: formatAbsolute(posting.posted_at) ?? undefined,
                  },
                ]
              : []),
          ]}
        />
        <CardSpec className="mt-1.5 border-t border-[var(--as-border)] pt-1.5" items={postingSpecs(posting, t)} />
      </div>
    </ItemCardShell>
  );
}
