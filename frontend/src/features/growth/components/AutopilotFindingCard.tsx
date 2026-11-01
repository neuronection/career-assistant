import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  BadgeCheck,
  BriefcaseBusiness,
  MapPin,
  Quote,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";

import { markApplied } from "@/api/postings";
import type { AutopilotFindingFeedItem } from "@/api/autopilot";
import { buttonVariants } from "@/components/ui";
import { CardMeta } from "@/components/cards/CardMeta";
import { CardSpec } from "@/components/cards/CardSpec";
import { CardStateMarker, ClosedMark } from "@/components/cards/CardState";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import { postingSpecs, type SpecSource } from "@/components/cards/postingSpecs";
import { OrgAvatar } from "@/components/company/OrgAvatar";
import { ScoreBubble } from "@/components/score/ScoreBubble";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";
import { safeExternalUrl } from "@/lib/url";

const OPEN_STATUSES = new Set(["new", "mapped"]);

export function isFeedPostingOpen(posting: AutopilotFindingFeedItem["posting"]): boolean {
  if (!OPEN_STATUSES.has(posting.status)) return false;
  if (!posting.expires_at) return true;
  return new Date(posting.expires_at).getTime() > Date.now();
}

function specSourceOf(posting: AutopilotFindingFeedItem["posting"]): SpecSource {
  return {
    onsite_policy: posting.remote,
    seniority: posting.seniority,
    salary_currency: posting.salary?.currency ?? null,
    salary_min: posting.salary?.min ?? null,
    salary_max: posting.salary?.max ?? null,
    salary_period: posting.salary?.period ?? null,
  };
}

export function AutopilotFindingCard({
  item,
  onFeedback,
  onApplied,
}: {
  item: AutopilotFindingFeedItem;
  onFeedback: (id: string, kind: "more_like_this" | "hide_like_this") => void;
  onApplied?: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [markedApplied, setMarkedApplied] = useState(false);
  const posting = item.posting;
  const open = isFeedPostingOpen(posting);
  const dismissed = item.dismissed_at != null;
  const applied = item.applied || markedApplied;
  const applyUrl = safeExternalUrl(posting.url);
  const location = [posting.location?.city, posting.location?.country]
    .filter(Boolean)
    .join(", ");
  const postedRel = formatRelativeTime(posting.posted_at);
  const postedAt = postedRel
    ? t(postedRel.key, { count: postedRel.count })
    : formatAbsolute(posting.posted_at);
  const runRel = formatRelativeTime(item.created_at);
  const runDate = runRel
    ? t(runRel.key, { count: runRel.count })
    : formatAbsolute(item.created_at);
  const coverage =
    item.must_coverage && item.must_coverage.total > 0 ? item.must_coverage : null;
  const detailsPending = !posting.extracted;

  const markThisApplied = () => {
    setMarkedApplied(true);
    void markApplied(posting.id, posting.url)
      .then(() => onApplied?.(item.id))
      .catch(() => setMarkedApplied(false));
  };

  return (
    <ItemCardShell
      testId={`finding-card-${item.id}`}
      state={open ? undefined : "closed"}
      className={dismissed ? "opacity-55" : ""}
      actions={
        <>
          {!open ? <ClosedMark label={t("card.closed")} /> : null}
          {applyUrl ? (
            <a
              href={applyUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ variant: "outline", size: "sm" })}
              data-testid={`finding-open-${item.id}`}
            >
              <BriefcaseBusiness className="h-3 w-3" /> {t("autopilot.workspace.viewPosting")}
            </a>
          ) : null}
          <button
            type="button"
            disabled={applied}
            onClick={markThisApplied}
            className={`${buttonVariants({ variant: applied ? "secondary" : "default", size: "sm" })} ${
              applied ? "cursor-not-allowed opacity-70" : ""
            }`}
            data-testid={`finding-apply-${item.id}`}
          >
            {applied ? t("autopilot.workspace.applied") : t("autopilot.workspace.markApplied")}
          </button>
          <div className="flex items-center gap-1">
            <button
              type="button"
              className={buttonVariants({
                variant: item.feedback === "more_like_this" ? "default" : "ghost",
                size: "icon",
              })}
              aria-label={t("autopilot.moreLikeThis")}
              title={t("autopilot.moreLikeThis")}
              disabled={dismissed}
              onClick={() => onFeedback(item.id, "more_like_this")}
              data-testid={`feedback-more-${item.id}`}
            >
              <ThumbsUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              className={buttonVariants({
                variant: item.feedback === "hide_like_this" ? "destructive" : "ghost",
                size: "icon",
              })}
              aria-label={t("autopilot.hideLikeThis")}
              title={t("autopilot.hideLikeThis")}
              onClick={() => onFeedback(item.id, "hide_like_this")}
              data-testid={`feedback-hide-${item.id}`}
            >
              <ThumbsDown className="h-4 w-4" />
            </button>
          </div>
        </>
      }
    >
      <div className="flex shrink-0 flex-col items-center gap-0.5 pt-0.5">
        <ScoreBubble score={item.score} size={52} />
        <span className="text-[9px] font-semibold uppercase tracking-[0.07em] text-[var(--as-muted-fg)]">
          {t("card.fit")}
        </span>
        {coverage ? (
          <span
            className="rounded-lg bg-[var(--as-muted)] px-2 py-0.5 text-xs font-medium tabular-nums text-[var(--as-muted-fg)]"
            data-testid={`coverage-${item.id}`}
            title={t("autopilot.fitScore")}
          >
            {t("autopilot.mustHaves", {
              hits: coverage.hits,
              total: coverage.total,
            })}
          </span>
        ) : null}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <Link
            to={`/postings/${posting.ref}`}
            className="min-w-0 truncate text-left font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
            data-testid={`finding-title-${item.id}`}
            onClick={(event) => event.stopPropagation()}
          >
            {posting.title}
          </Link>
          {!open ? (
            <CardStateMarker title={t("card.closed")} tone="muted" testId={`finding-state-${item.id}`} />
          ) : null}
          {applied ? (
            <BadgeCheck
              aria-hidden
              className="h-3.5 w-3.5 shrink-0 text-[var(--as-success)]"
            />
          ) : null}
        </div>

        <div className="mt-0.5 flex min-w-0 items-center gap-1.5">
          <OrgAvatar name={posting.org} size={20} />
          <span className="truncate text-[13px] font-medium text-[var(--as-fg)]">
            {posting.org}
          </span>
        </div>

        <CardMeta
          className="mt-1"
          items={[
            ...(location ? [{ key: "location", icon: MapPin, text: location }] : []),
            ...(posting.posted_at
              ? [
                  {
                    key: "posted",
                    text: t("postingCard.posted", { date: postedAt }),
                    title: formatAbsolute(posting.posted_at),
                  },
                ]
              : []),
          ]}
        />

        <CardSpec
          className="mt-1.5 border-t border-[var(--as-border)] pt-1.5"
          items={postingSpecs(specSourceOf(posting), t)}
        />

        <div className="mt-2 rounded-lg bg-[var(--as-muted)] p-2.5" data-testid={`finding-evidence-${item.id}`}>
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className="rounded-full bg-[var(--as-surface)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-[var(--as-muted-fg)]"
              data-testid={`finding-verified-${item.id}`}
              data-verified={item.quotes.length > 0 ? "true" : undefined}
            >
              {t("autopilot.workspace.evidence")}
            </span>
            {coverage ? (
              <span className="text-[11px] tabular-nums text-[var(--as-muted-fg)]">
                {t("autopilot.mustHaves", { hits: coverage.hits, total: coverage.total })}
              </span>
            ) : null}
            {item.disabled_dims > 0 ? (
              <span
                className="text-[11px] text-[var(--as-muted-fg)]"
                data-testid={`finding-disabled-dims-${item.id}`}
              >
                {t("autopilot.workspace.disabledDims", { count: item.disabled_dims })}
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-[13px] text-[var(--as-fg)]">{item.why}</p>
          {item.quotes.map((quote, index) => (
            <blockquote
              key={index}
              className="mt-1.5 flex items-start gap-1.5 border-l-2 border-[var(--as-accent)] pl-2 text-xs italic text-[var(--as-muted-fg)]"
            >
              <Quote aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
              <span>{quote}</span>
            </blockquote>
          ))}
          {detailsPending ? (
            <p
              className="mt-1.5 text-[11px] text-[var(--as-muted-fg)]"
              data-testid={`finding-estimate-${item.id}`}
            >
              {t("autopilot.workspace.estimateFootnote")}
            </p>
          ) : null}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[var(--as-muted-fg)]">
          <span data-testid={`finding-run-provenance-${item.id}`}>
            {t("autopilot.workspace.runProvenance", { date: runDate })}
          </span>
          <span className="text-[var(--as-border)]">|</span>
          <span>{item.goal_text.length > 48 ? `${item.goal_text.slice(0, 48)}…` : item.goal_text}</span>
          <span className="text-[var(--as-border)]">|</span>
          <span>
            {posting.source}
            {posting.ref ? ` · ${posting.ref}` : ""}
          </span>
          {applied ? (
            <>
              <span className="text-[var(--as-border)]">|</span>
              <span className="text-[var(--as-success)]" data-testid={`finding-applied-${item.id}`}>
                {t("postingCard.applied")}
              </span>
            </>
          ) : null}
        </div>
      </div>
    </ItemCardShell>
  );
}
