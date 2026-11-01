import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  Bookmark,
  Check,
  Clock,
  ExternalLink,
  EyeOff,
  FileText,
  Link2,
  MapPin,
  Sparkles,
} from "lucide-react";

import { hidePosting, markApplied, markPostingsSeen, savePosting } from "@/api/postings";
import { buttonVariants } from "@/components/ui";
import { CardMeta } from "@/components/cards/CardMeta";
import { CardSpec } from "@/components/cards/CardSpec";
import { ChipRow } from "@/components/cards/ChipRow";
import { CardStateMarker, ClosedMark, SeenMark } from "@/components/cards/CardState";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import { postingSpecs } from "@/components/cards/postingSpecs";
import { OrgAvatar } from "@/components/company/OrgAvatar";
import { ScoreBubble } from "@/components/score/ScoreBubble";
import { SkillPeekModal, useSkillPeek } from "@/components/skills/SkillPeekModal";
import { educationChipLabel } from "@/features/catalog/components/JobCard";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";
import { safeExternalUrl } from "@/lib/url";
import type { PostingOut } from "@/types/wire";

const OPEN_STATUSES = new Set(["new", "mapped"]);

const PROVENANCE_ICON = {
  extracted: Sparkles,
  "fast-mapped": Link2,
  raw: FileText,
} as const;

export function provenanceOf(posting: PostingOut): "raw" | "fast-mapped" | "extracted" {
  if (posting.extract_version != null) return "extracted";
  return posting.mapping_method ? "fast-mapped" : "raw";
}

export function isPostingOpen(posting: PostingOut): boolean {
  if (!OPEN_STATUSES.has(posting.status)) return false;
  if (!posting.expires_at) return true;
  return new Date(posting.expires_at).getTime() > Date.now();
}

export { postingSpecs };

export function PostingCard({
  posting,
  onOpen,
  onChanged,
  smartSort = false,
}: {
  posting: PostingOut;
  onOpen?: (posting: PostingOut) => void;
  onChanged?: () => void;
  /** The smart sort is active: a small chip marks the blended ranking. */
  smartSort?: boolean;
}) {
  const { t } = useTranslation();
  const peek = useSkillPeek();
  const [markedSeenId, setMarkedSeenId] = useState<string | null>(null);
  const seenSlotRef = useRef<HTMLSpanElement | null>(null);
  const seen = Boolean(posting.seen) || markedSeenId === posting.id;
  const markSeen = () => {
    setMarkedSeenId(posting.id);
    void markPostingsSeen([posting.id]).catch(() => setMarkedSeenId(null));
  };
  useEffect(() => {
    if (markedSeenId === posting.id) seenSlotRef.current?.focus();
  }, [markedSeenId, posting.id]);
  const open = isPostingOpen(posting);
  const provenance = provenanceOf(posting);
  const ProvenanceIcon = PROVENANCE_ICON[provenance];
  const postedRel = formatRelativeTime(posting.posted_at);
  const postedAt = postedRel
    ? t(postedRel.key, { count: postedRel.count })
    : formatAbsolute(posting.posted_at);
  const applyUrl = safeExternalUrl(posting.url);
  const skills = posting.skills ?? [];
  const location = [posting.location?.city, posting.location?.country]
    .filter(Boolean)
    .join(", ");
  const closedTitle = posting.expires_at
    ? t("card.closedOn", { date: formatAbsolute(posting.expires_at) })
    : t("card.closed");

  return (
    <ItemCardShell
      testId="posting-card"
      state={open ? undefined : "closed"}
      seen={seen}
      onOpen={onOpen ? () => onOpen(posting) : undefined}
      actions={
        <>
          {!open ? <ClosedMark label={t("card.closed")} title={closedTitle} /> : null}
          {applyUrl ? (
            open ? (
              <a
                href={applyUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => {
                  setMarkedSeenId(posting.id);
                  void markPostingsSeen([posting.id]).catch(() => undefined);
                  void markApplied(posting.id, posting.url).catch(() => undefined);
                }}
                className={buttonVariants({ variant: "default", size: "sm" })}
                data-testid="posting-apply"
              >
                <ExternalLink className="w-3 h-3" /> {t("postingCard.apply")}
              </a>
            ) : (
              <span
                className={`${buttonVariants({ variant: "secondary", size: "sm" })} cursor-not-allowed opacity-70`}
                aria-disabled="true"
                data-testid="posting-apply"
              >
                <ExternalLink className="w-3 h-3" /> {t("postingCard.apply")}
              </span>
            )
          ) : null}
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
            className="flex items-center justify-center gap-1 text-xs text-[var(--as-muted-fg)]"
            title={t("postingCard.hideTitle")}
            data-testid="posting-hide"
          >
            <EyeOff className="w-3 h-3" /> {t("postingCard.hide")}
          </button>
        </>
      }
    >
      <div className="flex shrink-0 flex-col items-center gap-0.5 pt-0.5">
        <ScoreBubble score={posting.fit} size={52} />
        <span className="text-[9px] font-semibold uppercase tracking-[0.07em] text-[var(--as-muted-fg)]">
          {t("card.fit")}
        </span>
        {smartSort ? (
          <span
            className="text-[9px] font-semibold uppercase tracking-[0.07em] rounded-full border border-[var(--as-border)] px-1.5 py-px text-[var(--as-muted-fg)]"
            title={t("card.smartBadgeInfo")}
            data-testid="posting-smart-chip"
          >
            {t("card.smartBadge")}
          </span>
        ) : null}
        {posting.coverage != null ? (
          <span
            className="text-[10px] text-[var(--as-muted-fg)]"
            data-testid="posting-coverage"
          >
            {t("card.coverage", { score: Number(posting.coverage).toFixed(1) })}
          </span>
        ) : null}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <button
            type="button"
            className="min-w-0 truncate text-left font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
            data-testid="posting-details"
          >
            <span data-testid="posting-title">{posting.title}</span>
          </button>
          {posting.needs_review ? (
            <CardStateMarker title={t("card.partial")} tone="muted" testId="posting-partial" />
          ) : null}
          {posting.saved ? (
            <Bookmark
              aria-hidden
              className="h-3.5 w-3.5 shrink-0 fill-current text-[var(--as-accent)]"
            />
          ) : null}
        </div>

        <div className="mt-0.5 flex min-w-0 items-center gap-1.5">
          <OrgAvatar name={posting.org} size={20} />
          {posting.org_key ? (
            <Link
              to={`/companies/${posting.org_key}`}
              onClick={(event) => event.stopPropagation()}
              className="truncate text-[13px] font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
              data-testid="posting-company-link"
            >
              {posting.org}
            </Link>
          ) : (
            <span className="truncate text-[13px] font-medium text-[var(--as-fg)]">
              {posting.org}
            </span>
          )}
        </div>

        <CardMeta
          className="mt-1"
          items={[
            ...(location
              ? [{ key: "location", icon: MapPin, text: location }]
              : []),
            {
              key: "posted",
              icon: Clock,
              text: t("postingCard.posted", { date: postedAt }),
              title: formatAbsolute(posting.posted_at),
            },
          ]}
        />

        <CardSpec
          className="mt-1.5 border-t border-[var(--as-border)] pt-1.5"
          items={postingSpecs(posting, t, (level) => educationChipLabel(t, level))}
        />

        {skills.length > 0 ? (
          <div className="mt-2">
            <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
              {t("card.skills")}
            </p>
            <ChipRow
              variant="skill"
              clampRows={2}
              testId="posting-skills"
              itemTestId="skill-tag"
              items={skills.map((skill) => ({
                key: skill.key,
                label: skill.label,
                score: skill.required_level,
                title:
                  skill.required_level != null
                    ? t("card.skillRequires", { level: skill.required_level })
                    : undefined,
                onOpen: (trigger) =>
                  peek.open(skill.key, trigger, skill.required_level ?? null),
              }))}
              moreLabel={(count) => t("card.more", { count })}
              moreAriaLabel={(count) => t("card.moreAria", { count })}
              showLessLabel={t("card.showLess")}
            />
          </div>
        ) : provenance !== "extracted" ? (
          <p className="mt-1.5 text-[11px] text-[var(--as-muted-fg)]" data-testid="posting-details-pending">
            {t("card.detailsPending")}
          </p>
        ) : null}

        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[var(--as-muted-fg)]">
          {seen ? (
            <span ref={seenSlotRef} tabIndex={-1} className="rounded-[4px] outline-none">
              <SeenMark label={t("card.seen")} testId="posting-seen" />
            </span>
          ) : (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                markSeen();
              }}
              className="-my-1 -ml-1 inline-flex items-center gap-1 rounded-[6px] px-1 py-1 transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
              title={t("postingCard.markSeen")}
              data-testid="posting-mark-seen"
            >
              <Check aria-hidden className="h-3 w-3 text-[var(--as-accent)]" />
              {t("postingCard.markSeen")}
            </button>
          )}
          <span className="text-[var(--as-border)]">|</span>
          <span>
            {posting.source_key || posting.ref}
            {posting.source_key && posting.ref ? ` · ${posting.ref}` : ""}
          </span>
          <span className="text-[var(--as-border)]">|</span>
          <span
            className="inline-flex items-center gap-1"
            data-testid="posting-provenance"
            data-tone={provenance === "extracted" ? "success" : "muted"}
            title={t(`postingCard.provenance.${provenance}`, {
              defaultValue: provenance,
            })}
          >
            <ProvenanceIcon aria-hidden className="h-3 w-3" />
            {t(`card.provenanceValue.${provenance}`, { defaultValue: provenance })}
          </span>
          {posting.applied_at ? (
            <>
              <span className="text-[var(--as-border)]">|</span>
              <span className="text-[var(--as-success)]">{t("postingCard.applied")}</span>
            </>
          ) : null}
        </div>
      </div>
      <SkillPeekModal
        skillKey={peek.skillKey}
        highlightLevel={peek.highlightLevel}
        onClose={peek.close}
        returnFocusRef={peek.returnFocusRef}
      />
    </ItemCardShell>
  );
}
