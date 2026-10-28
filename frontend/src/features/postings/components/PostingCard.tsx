import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  Bookmark,
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
import type { SpecItem } from "@/components/cards/specOrder";
import { OrgAvatar } from "@/components/company/OrgAvatar";
import { ScoreBubble } from "@/components/score/ScoreBubble";
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

function compactAmount(value: number): string {
  if (Math.abs(value) >= 10000) return `${Math.round(value / 1000)}k`;
  return Number(value).toLocaleString();
}

function salaryValue(
  posting: PostingOut,
  t: (key: string, opts?: Record<string, unknown>) => string
): string | null {
  const min = posting.salary_min;
  const max = posting.salary_max;
  if (min == null && max == null) return null;
  const range =
    min != null && max != null
      ? `${compactAmount(min)}–${compactAmount(max)}`
      : compactAmount((min ?? max) as number);
  const period = posting.salary_period
    ? t(`postingCard.period.${posting.salary_period}`, {
        defaultValue: posting.salary_period,
      })
    : "";
  const basis = posting.salary_basis
    ? t(`postingCard.salaryBasis.${posting.salary_basis}`, {
        defaultValue: posting.salary_basis,
      })
    : "";
  const base = [posting.salary_currency, `${range}${period ? ` / ${period}` : ""}`, basis]
    .filter(Boolean)
    .join(" ");
  const normalizedMin = posting.salary_normalized_min;
  const normalizedMax = posting.salary_normalized_max;
  if (
    posting.salary_period &&
    posting.salary_period !== "year" &&
    (normalizedMin != null || normalizedMax != null)
  ) {
    const normalizedRange = [normalizedMin, normalizedMax]
      .filter((value): value is number => value != null)
      .map((value) => compactAmount(Number(value)))
      .join("–");
    return `${base} · ${t("card.perYear", {
      range: normalizedRange,
      currency: posting.salary_currency ?? "",
    })}`;
  }
  return base;
}

function hoursValue(posting: PostingOut): string | null {
  if (posting.work_hours) return posting.work_hours;
  const min = posting.hours_per_week_min;
  const max = posting.hours_per_week_max;
  if (min == null && max == null) return null;
  if (min != null && max != null && min !== max) return `${min}–${max} h`;
  return `${min ?? max} h`;
}

function closesInDays(posting: PostingOut): number | null {
  if (!posting.expires_at) return null;
  const diff = new Date(posting.expires_at).getTime() - Date.now();
  if (diff <= 0) return null;
  const days = Math.ceil(diff / 86_400_000);
  return days <= 7 ? days : null;
}

export function postingSpecs(
  posting: PostingOut,
  t: (key: string, opts?: Record<string, unknown>) => string
): SpecItem[] {
  const specs: SpecItem[] = [];
  const mode =
    posting.onsite_policy ?? (posting.location?.remote ? "remote" : undefined);
  if (mode) {
    specs.push({
      key: "mode",
      label: t("card.mode"),
      value: t(`card.modeValue.${mode}`, {
        defaultValue: String(mode).replace(/_/g, " "),
      }),
    });
  }
  if (posting.seniority) {
    specs.push({
      key: "level",
      label: t("card.level"),
      value: t(`autopilot.seniority.${posting.seniority}`, {
        defaultValue: posting.seniority,
      }),
    });
  }
  const contract = posting.employment_type ?? posting.contract_type;
  if (contract) {
    specs.push({
      key: "contract",
      label: t("card.contract"),
      value: t(`explore.facetValue.${contract}`, {
        defaultValue: contract.replace(/_/g, " "),
      }),
    });
  }
  const hours = hoursValue(posting);
  if (hours) specs.push({ key: "hours", label: t("card.hours"), value: hours });
  const salary = salaryValue(posting, t);
  if (salary) specs.push({ key: "salary", label: t("card.salary"), value: salary });
  if (posting.education_level) {
    specs.push({
      key: "education",
      label: t("card.education"),
      value: educationChipLabel(t, posting.education_level),
    });
  }
  const closes = closesInDays(posting);
  if (closes != null) {
    specs.push({
      key: "closes",
      label: t("card.closes"),
      value: t("card.closesIn", { count: closes }),
      tone: "warning",
    });
  }
  return specs;
}

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
      seen={posting.seen}
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

        <CardSpec className="mt-1.5 border-t border-[var(--as-border)] pt-1.5" items={postingSpecs(posting, t)} />

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
          {posting.seen ? (
            <>
              <SeenMark label={t("card.seen")} testId="posting-seen" />
              <span className="text-[var(--as-border)]">|</span>
            </>
          ) : null}
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
    </ItemCardShell>
  );
}
