import { Bookmark, Compass } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui";
import { CardSpec } from "@/components/cards/CardSpec";
import { ChipRow } from "@/components/cards/ChipRow";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import { SeenMark } from "@/components/cards/CardState";
import { DemandBadge } from "@/features/postings/components/DemandBadge";
import type { Job } from "@/types/wire";

export const EDUCATION_CHIP: Record<string, string> = {
  no_formal: "education.chip.no_formal",
  middle_school: "education.chip.middle_school",
  high_school: "education.chip.high_school",
  vocational: "education.chip.vocational",
  bachelor: "education.chip.bachelor",
  master: "education.chip.master",
  doctorate: "education.chip.doctorate",
};

export function educationChipLabel(
  t: (key: string, opts?: Record<string, unknown>) => string,
  level: string
): string {
  return t(EDUCATION_CHIP[level] ?? level, { defaultValue: level });
}

export function JobCard({
  job,
  onSelect,
  seen = false,
  saved = false,
  notes,
  exploration = false,
}: {
  job: Job;
  onSelect?: (job: Job) => void;
  seen?: boolean;
  saved?: boolean;
  notes?: string;
  exploration?: boolean;
}) {
  const { t } = useTranslation();
  const education = job.attributes?.education?.level;
  return (
    <ItemCardShell
      testId="job-card"
      onOpen={onSelect ? () => onSelect(job) : undefined}
      seen={seen}
      className="w-full text-left"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <button
            type="button"
            data-testid="job-title"
            className="min-w-0 truncate text-left font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
          >
            {job.title}
          </button>
          <div className="flex shrink-0 items-center gap-1.5">
            {seen ? <SeenMark label={t("jobCard.seen")} testId="job-seen" /> : null}
            {saved ? (
              <Bookmark
                aria-hidden
                className="h-3.5 w-3.5 fill-current text-[var(--as-accent)]"
              />
            ) : null}
            <DemandBadge outlook={job.attributes?.demand?.outlook} />
          </div>
        </div>
        <p className="mt-1 line-clamp-2 text-sm text-[var(--as-muted-fg)]">
          {job.short_description}
        </p>
        {notes ? (
          <p
            className="mt-1 line-clamp-1 text-xs italic text-[var(--as-muted-fg)]"
            data-testid="job-card-notes"
          >
            {notes}
          </p>
        ) : null}
        <CardSpec
          className="mt-1.5"
          items={
            education
              ? [
                  {
                    key: "education",
                    label: t("card.education"),
                    value: educationChipLabel(t, education),
                    testId: "education-chip",
                  },
                ]
              : []
          }
        />
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          <ChipRow
            testId="job-interests"
            max={3}
            moreLabel={(count) => t("card.more", { count })}
            moreAriaLabel={(count) => t("card.moreAria", { count })}
            showLessLabel={t("card.showLess")}
            items={(job.interests ?? []).map((interest) => ({
              key: interest.key,
              label: interest.label,
            }))}
          />
          {exploration ? (
            <Badge variant="ai">
              <Compass aria-hidden /> {t("jobCard.explore")}
            </Badge>
          ) : null}
        </div>
      </div>
    </ItemCardShell>
  );
}
